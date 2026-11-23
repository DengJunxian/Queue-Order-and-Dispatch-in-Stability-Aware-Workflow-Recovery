"""Observed-repeat prediction/calibration/evaluation with locked split roles."""
import argparse,math,time
from dataclasses import replace
from concurrent.futures import ProcessPoolExecutor,as_completed
from datetime import datetime
from zoneinfo import ZoneInfo
from sail.data import speed_vector,failure_node,bandwidth_for_ccr
from sail.simulator import Simulator
from sail.model import Plan
from revision_r6.common import *
from revision_r6.run_holdout import snapshot_at,evaluate_case,audit_saved,verify_registration

def observed_workload(repeat):
    corpus=Corpus(ROOT);parts=[];truth={};sources=[];runtime_ratios=[]
    for k,size in enumerate(['20a','30a','40a']):
        ids=[f'srasearch-chameleon-{size}-{r:03d}' for r in range(1,6)]
        for identity in ids:
            record=corpus.records[identity]
            assert sha(ROOT/record['raw_path'])==record['raw_sha256'] and sha(ROOT/record['parsed_path'])==record['parsed_sha256']
        parsed=[read(ROOT/corpus.records[i]['parsed_path']) for i in ids]
        task_ids=[[t['id'] for t in d['tasks']] for d in parsed]
        assert all(ids==task_ids[0] for ids in task_ids)
        edges=lambda d:sorted((e['source'],e['target']) for e in d['edges'])
        topology=lambda d:sorted((tuple(sorted(f['producers'])),tuple(sorted(f['consumers']))) for f in d['files'])
        assert all(edges(d)==edges(parsed[0]) and topology(d)==topology(parsed[0]) for d in parsed)
        wid=f'w{k:02d}';raw=corpus.load(ids[0],wid,normalize=False)
        times=[{t['id']:t['runtime_seconds'] for t in d['tasks']} for d in parsed]
        prediction={v:(times[0][v]+times[1][v])/2 for v in times[0]};scale=sum(prediction.values())/len(prediction)
        tasks=tuple(replace(t,work=prediction[t.id.split('::',1)[1]]/scale) for t in raw.tasks)
        parts.append(Workload(tasks,raw.files))
        for t in tasks:
            v=t.id.split('::',1)[1];truth[t.id]=times[repeat-1][v]/scale;runtime_ratios.append(truth[t.id]/t.work)
        sources.extend({'id':i,'raw_sha256':corpus.records[i]['raw_sha256'],'parsed_sha256':corpus.records[i]['parsed_sha256'],'role':'prediction' if j<2 else 'calibration' if j==2 else 'evaluation'} for j,i in enumerate(ids))
    w=Workload(tuple(t for part in parts for t in part.tasks),tuple(f for part in parts for f in part.files))
    return w,truth,{'sources':sources,'runtime_ratio_min':min(runtime_ratios),'runtime_ratio_max':max(runtime_ratios),'runtime_ratio_mean':sum(runtime_ratios)/len(runtime_ratios),'work_scale':'prediction mean fixed across all repeats','network_input':'repeat001 producer-consumer file sizes retained to isolate observed runtime variation; file names vary across repeats but canonical producer/consumer incidence matches'}

def task(spec):
    repeat,root,eta=spec;stage='calibration' if repeat==3 else 'evaluation';sid=f'repeat{repeat:03d}-r{root}'
    target=OUT/'measured'/stage/'cases'/f'{sid}.json'
    if target.exists():
        old=read(target);assert sha(ROOT/old['event_file'])==old['event_sha256'];return old
    started=time.perf_counter();w,truth,provenance=observed_workload(repeat)
    p=Platform(speed_vector(root,'R6-observed-SRA',4),bandwidth_for_ccr(w,2));initial=initial_heft(w,p)
    ref=Simulator(w,p,initial.plan,realized_work=truth).run();fault=Failure(.6*ref.makespan,failure_node(root,'R6-observed-SRA',4))
    snapshot,context=snapshot_at(w,p,truth,initial,fault);original,pool,b2=original_choices(snapshot,context,initial)
    d=evaluate_case(w,p,truth,initial,fault,original,pool,b2,snapshot,context,['independent'],eta=eta,strict_reference=ref)
    calibration=[]
    if stage=='calibration':
        actual_views=tuple(replace(v,estimated_remaining=max(1e-12,truth[v.id]/p.speeds[v.node]-(snapshot.time-v.observed_start))) if v.status=='RUNNING' else v for v in snapshot.tasks)
        # Latent work is used here only for offline calibration, never passed to
        # original_choices or dispatch_choices. Every candidate is retained.
        actual_snapshot=replace(snapshot,tasks=actual_views)
        for key,candidates in d['pool_forecasts'].items():
            rule=key.split('/')[1]
            for c in candidates:
                plan=Plan(tuple(tuple(q) for q in c['plan']['queues']))
                actual=ClockExecutor(w,p,plan,truth=truth,rule=rule,network='independent',snapshot=actual_snapshot).run()
                wf=dict(actual.workflow_finishes);errors={g:abs(c['workflow_completion'][g]/wf[g]-1) for g in wf}
                calibration.append({'rule':rule,'candidate':c['name'],'plan':c['plan'],'predicted':c['workflow_completion'],'realized':wf,'relative_prediction_errors':errors,'continuation':jsonable(actual)})
                for runkey,value in d['runs'].items():
                    if runkey.startswith(key+'/') and value['clock']['applied_plan']==c['plan']:
                        assert all(math.isclose(t,dict(value['clock']['workflow_finishes'])[g],abs_tol=1e-8,rel_tol=1e-10) for g,t in wf.items())
    d.update({'workload':jsonable(w),'platform':jsonable(p),'truth':truth,'initial':jsonable(initial.plan),'failure':jsonable(fault),'public_snapshot':jsonable(snapshot),'provenance':provenance,'repeat':repeat,'root':root,'calibration_candidates':calibration})
    path=OUT/'measured'/stage/'events'/f'{sid}.json.gz';digest=save(path,d);loaded=read(path)
    rows,checks=audit_saved(loaded,w,p,truth,fault)
    for row in rows:row.update({'case_id':sid,'repeat':repeat,'root':root,'stage':stage,'nodes':4,'ccr':2})
    errors={rule:max(x for c in calibration if c['rule']==rule for x in c['relative_prediction_errors'].values()) for rule in ['strict','skip-unready']} if calibration else None
    result={'status':'PASS','case_id':sid,'event_file':str(path.relative_to(ROOT)),'event_sha256':digest,'rows':rows,'checks':checks,'calibration_eta':errors,'offline_candidate_continuations':len(calibration),'seconds':time.perf_counter()-started}
    dump(target,result);return result

def main(stage,workers=2):
    verify_registration()
    for p,h in read(OUT/'measured_registration.json')['files'].items():assert sha(ROOT/p)==h,p
    eta=None
    if stage=='calibration':repeats=[3]
    else:
        calibration=read(OUT/'measured/calibration.json');eta=calibration['eta'];repeats=[4,5]
        reg=OUT/'measured/evaluation_registration.json'
        if not reg.exists():dump(reg,{'registered_at':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),'calibration_sha256':sha(OUT/'measured/calibration.json'),'evaluation_executions_before_registration':0})
        assert sha(OUT/'measured/calibration.json')==read(reg)['calibration_sha256']
    jobs=[(repeat,root,eta) for repeat in repeats for root in range(92000,92012)];done=[]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures=[pool.submit(task,x) for x in jobs]
        try:
            for f in as_completed(futures):
                d=f.result();done.append(d);print(f'Observed {stage} {len(done)}/{len(jobs)}',flush=True)
        except Exception as e:
            for f in futures:f.cancel()
            dump(OUT/'measured'/stage/'failure.json',{'status':'STOPPED','error':repr(e)});raise
    rows=[r for d in sorted(done,key=lambda d:d['case_id']) for r in d['rows']]
    journal=OUT/'measured'/stage/'metrics.jsonl';journal.write_text(''.join(json.dumps(r,allow_nan=False)+'\n' for r in rows))
    totals={k:sum(d['checks'][k] for d in done) for k in done[0]['checks'] if k!='cross_implementation_max_abs_difference'}
    totals['cross_implementation_max_abs_difference']=max(d['checks']['cross_implementation_max_abs_difference'] for d in done)
    expected=240 if stage=='calibration' else 528;assert len(rows)==expected
    dump(OUT/'measured'/stage/'receipt.json',{'status':'PASS','cases':len(done),'observed_runtime_vectors':len(repeats),'new_exploratory_repair_executions':len(rows),'offline_candidate_continuations':sum(d['offline_candidate_continuations'] for d in done),'new_confirmatory_samples':0,**totals,'metrics_sha256':sha(journal)})
    if stage=='calibration':
        eta={rule:max(d['calibration_eta'][rule] for d in done) for rule in ['strict','skip-unready']}
        dump(OUT/'measured/calibration.json',{'status':'FROZEN_BEFORE_EVALUATION','eta':eta,'definition':'Maximum observed absolute relative workflow-completion prediction error across all original-pool candidates, workflows and12 calibration environments','source_repeat':3,'methodology':'Empirical margin; no distribution-free guarantee for future runtime vectors','calibration_metrics_sha256':sha(journal),'registered_at':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()})
        print('Frozen empirical completion error',eta,flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['calibration','evaluation']);p.add_argument('--workers',type=int,default=2);a=p.parse_args();main(a.stage,a.workers)
