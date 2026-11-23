"""Observed-repeat adaptation and paired-error admission, isolated from latent work."""
import math
from collections import defaultdict
from dataclasses import replace
from pathlib import Path
from sail.data import Corpus
from sail.model import Workload, RepairDecision
from revision_r6.common import read, dump, sha, jsonable

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'revision_r7'
RULES = ['strict','skip-unready']
NETWORKS = ['independent','shared']


class RepeatCorpus(Corpus):
    def __init__(self):
        self.root = ROOT
        self.manifest = read(OUT/'data/manifest.json')
        self.records = {r['id']:r for r in self.manifest['records']}


def observed_workload(composition, repeat):
    corpus = RepeatCorpus()
    series = read(OUT/'protocol.json')['data']['compositions'][composition]
    parts, truth, provenance = [], {}, []
    for k, group in enumerate(series):
        records = [corpus.records[f'{group}-{r:03d}'] for r in range(1,6)]
        for row in records:
            for kind in ['raw','parsed']:
                assert sha(ROOT/row[kind+'_path']) == row[kind+'_sha256']
        docs = [read(ROOT/r['parsed_path']) for r in records]
        times = [{t['id']:t['runtime_seconds'] for t in d['tasks']} for d in docs]
        assert all(set(t)==set(times[0]) for t in times)
        prediction = {v:(times[0][v]+times[1][v])/2 for v in times[0]}
        scale = sum(prediction.values())/len(prediction)
        raw = corpus.load(records[0]['id'],f'w{k:02d}',normalize=False)
        tasks = tuple(replace(t,work=prediction[t.id.split('::',1)[1]]/scale) for t in raw.tasks)
        parts.append(Workload(tasks,raw.files))
        truth.update({t.id:times[repeat-1][t.id.split('::',1)[1]]/scale for t in tasks})
        provenance.append({'series':group,'workflow':f'w{k:02d}','tasks':len(tasks),'prediction_mean_seconds':scale,'prediction_ids':[records[0]['id'],records[1]['id']],'realized_id':records[repeat-1]['id'],'file_model_id':records[0]['id']})
    return Workload(tuple(t for w in parts for t in w.tasks),tuple(f for w in parts for f in w.files)),truth,provenance


def fit_envelope(samples):
    """Fit fixed empirical maxima; samples are offline calibration observations."""
    assert samples
    eta, delta = 0., 0.
    groups = defaultdict(list)
    for s in samples:
        assert s['predicted']>0 and s['realized']>0 and s['reference_predicted']>0 and s['reference_realized']>0
        error = abs(s['predicted']/s['realized']-1)
        z = math.log(s['realized']/s['reference_realized'])-math.log(s['predicted']/s['reference_predicted'])
        eta=max(eta,error);delta=max(delta,z)
        groups[s['candidate']+'|'+s['workflow']].append((z,s['root']))
    conditional={name:{'delta':max(0.,max(x[0] for x in values)),'distinct_roots':len({x[1] for x in values}),'observations':len(values)} for name,values in sorted(groups.items())}
    return {'eta':eta,'global_delta':delta,'conditional':conditional,'observations':len(samples),'conditional_minimum_roots':3}


def paired_choices(context, rows, reference, mean_limit, envelope):
    """Select from public forecasts and frozen margins; accepts no latent truth."""
    admissible=[c for c in rows if c['awct']<=mean_limit] or rows
    assert reference in admissible
    ref=dict(reference['forecast'].workflow_finishes)
    decisions, selected, metadata = {}, {}, {}
    key=lambda c:(c['cdi'],c['awct'],c['churn'],c['name'],c['plan'].queues)
    for method in ['PairedRatioGuard','ConditionalRatioGuard']:
        admitted=[];diagnostics=[]
        for c in admissible:
            if c['plan']==reference['plan']:
                continue
            bounds={};covered=True
            for g,t in c['forecast'].workflow_finishes:
                if method=='PairedRatioGuard':
                    delta=envelope['global_delta']
                else:
                    group=envelope['conditional'].get(c['name']+'|'+g)
                    if group is None or group['distinct_roots']<envelope['conditional_minimum_roots']:
                        covered=False;break
                    delta=group['delta']
                bounds[g]=math.log(t/ref[g])+delta
            passes=covered and all(x<=math.log(1.05)+1e-12 for x in bounds.values())
            diagnostics.append({'name':c['name'],'covered':covered,'log_ratio_upper':bounds,'admitted':passes})
            if passes:admitted.append(c)
        chosen=min(admitted,key=key) if admitted else reference
        decisions[method]=RepairDecision(context.Q,chosen['plan'])
        selected[method]=chosen
        metadata[method]={'reference_fallback':not bool(admitted),'nonreference_selected':chosen['plan']!=reference['plan'],'selected_name':chosen['name'],'reference_name':reference['name'],'admissible_count':len(admissible),'admitted_nonreference_count':len(admitted),'candidate_admission':diagnostics}
    return decisions,selected,metadata
