"""Run every registered measured-repeat comparison, preserving full event evidence."""
import argparse
import math
import time
from concurrent.futures import ProcessPoolExecutor,as_completed
from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo
from sail.data import speed_vector,failure_node,bandwidth_for_ccr
from sail.simulator import Simulator
from sail.model import Platform,Failure,Plan
from sail.scheduling import initial_heft
from revision_r2.dispatch import SkipUnready
from revision_r6.clock_executor import ClockExecutor,predict
from revision_r6.common import original_choices,dispatch_choices,save
from revision_r6.run_holdout import snapshot_at,audit_saved
from revision_r6.audit_dispatch_order import audit as audit_dispatch
from revision_r7.common import *


def verify_registration():
    for name in ['registration.json','execution_registration.json']:
        for p,h in read(OUT/name)['files'].items():
            assert sha(ROOT/p)==h,p


def evaluate(w,p,truth,initial,fault,snapshot,context,original,pool,b2,envelopes=None):
    refs,runs,metadata,forecasts,pool_forecasts = {},{},{},{},{}
    # Construct every online decision before any offline candidate continuation.
    plans={}
    for net in NETWORKS:
        for rule in RULES:
            key=net+'/'+rule;envelope=envelopes[key] if envelopes else None
            new,selected,rows,info=dispatch_choices(snapshot,context,initial,pool,b2,rule,net,eta=envelope['eta'] if envelope else None)
            if envelope:
                extra,chosen,guardinfo=paired_choices(context,rows,selected['DispatchMinAWCT'],1.05*predict(snapshot,b2,rule,net).awct,envelope)
                new.update(extra);selected.update(chosen);info['paired_guards']=guardinfo
            metadata[key]=info
            forecasts[key]={name:{'workflow_completion':dict(c['forecast'].workflow_finishes),'cdi':c['cdi'],'selected_name':c['name']} for name,c in selected.items()}
            pool_forecasts[key]=[{'name':c['name'],'plan':jsonable(c['plan']),'churn':c['churn'],'awct':c['awct'],'cdi':c['cdi'],'workflow_completion':dict(c['forecast'].workflow_finishes)} for c in rows]
            plans[key]={**original,**new}
    for key,choices in plans.items():
        net,rule=key.split('/')
        refs[key]={'clock':jsonable(ClockExecutor(w,p,initial.plan,truth=truth,rule=rule,network=net,switch_time=fault.time).run())}
        cls=Simulator if rule=='strict' else SkipUnready
        kw={} if rule=='strict' else {'switch_time':fault.time}
        if net=='independent':
            refs[key]['original']=jsonable(cls(w,p,initial.plan,realized_work=truth,**kw).run())
        for name,decision in choices.items():
            def fixed(s,c,decision=decision):
                assert c==context
                return decision
            result={'clock':jsonable(ClockExecutor(w,p,initial.plan,truth=truth,rule=rule,network=net,switch_time=fault.time,failure=fault,repair=fixed).run())}
            if net=='independent':
                result['original']=jsonable(cls(w,p,initial.plan,realized_work=truth,failure=fault,repair=fixed,**kw).run())
            runs[key+'/'+name]=result
    actual_views=tuple(replace(v,estimated_remaining=max(1e-12,truth[v.id]/p.speeds[v.node]-(snapshot.time-v.observed_start))) if v.status=='RUNNING' else v for v in snapshot.tasks)
    actual_snapshot=replace(snapshot,tasks=actual_views)
    continuations=[]
    for key,rows in pool_forecasts.items():
        net,rule=key.split('/')
        for c in rows:
            plan=Plan(tuple(tuple(q) for q in c['plan']['queues']))
            actual=ClockExecutor(w,p,plan,truth=truth,rule=rule,network=net,snapshot=actual_snapshot).run()
            finishes=dict(actual.workflow_finishes)
            continuations.append({'condition':key,'candidate':c['name'],'plan':c['plan'],'predicted':c['workflow_completion'],'realized':finishes,'continuation':jsonable(actual)})
            for runkey,value in runs.items():
                if runkey.startswith(key+'/') and value['clock']['applied_plan']==c['plan']:
                    assert all(math.isclose(t,dict(value['clock']['workflow_finishes'])[g],abs_tol=1e-8,rel_tol=1e-10) for g,t in finishes.items())
    return {'references':refs,'runs':runs,'metadata':metadata,'predictions':forecasts,'pool_forecasts':pool_forecasts,'candidate_continuations':continuations}


def candidate_samples(doc):
    result=[]
    for key in doc['metadata']:
        cand=[c for c in doc['candidate_continuations'] if c['condition']==key]
        ref=next(c for c in cand if c['candidate']==doc['metadata'][key]['reference_name'])
        for c in cand:
            for g,t in c['predicted'].items():
                result.append({'condition':key,'candidate':c['candidate'],'workflow':g,'root':doc['root'],'predicted':t,'realized':c['realized'][g],'reference_predicted':ref['predicted'][g],'reference_realized':ref['realized'][g]})
    return result


def task(spec):
    composition,repeat,root,envelopes=spec
    stage='calibration' if repeat==3 else 'evaluation'
    sid=f'{composition}-repeat{repeat:03d}-r{root}'
    target=OUT/stage/'cases'/f'{sid}.json'
    if target.exists():
        old=read(target);assert sha(ROOT/old['event_file'])==old['event_sha256'];return old
    start=time.perf_counter();w,truth,source=observed_workload(composition,repeat)
    p=Platform(speed_vector(root,'R7-'+composition,4),bandwidth_for_ccr(w,2))
    initial=initial_heft(w,p)
    ref=Simulator(w,p,initial.plan,realized_work=truth).run()
    fault=Failure(.6*ref.makespan,failure_node(root,'R7-'+composition,4))
    snapshot,context=snapshot_at(w,p,truth,initial,fault)
    original,pool,b2=original_choices(snapshot,context,initial)
    doc=evaluate(w,p,truth,initial,fault,snapshot,context,original,pool,b2,envelopes)
    doc.update({'composition':composition,'repeat':repeat,'root':root,'provenance':source,'workload':jsonable(w),'platform':jsonable(p),'truth':truth,'initial':jsonable(initial.plan),'failure':jsonable(fault),'public_snapshot':jsonable(snapshot)})
    path=OUT/stage/'events'/f'{sid}.json.gz';digest=save(path,doc)
    reopened=read(path);rows,checks=audit_saved(reopened,w,p,truth,fault)
    checks['dispatch_choices']=0;checks['plan_applications']=0
    for collection in ['references','runs']:
        for key,value in reopened[collection].items():
            d=audit_dispatch(value['clock'],key.split('/')[1],fault.time)
            for field in d:checks[field]+=d[field]
    for row in rows:
        row.update({'case_id':sid,'composition':composition,'repeat':repeat,'root':root,'stage':stage})
        row['guard_metadata']=doc['metadata'][row['network']+'/'+row['rule']]
    result={'status':'PASS','case_id':sid,'composition':composition,'repeat':repeat,'root':root,'event_file':str(path.relative_to(ROOT)),'event_sha256':digest,'rows':rows,'checks':checks,'candidate_samples':candidate_samples(doc),'offline_candidate_continuations':len(doc['candidate_continuations']),'seconds':time.perf_counter()-start}
    dump(target,result)
    return result


def main(stage,workers):
    verify_registration()
    protocol=read(OUT/'protocol.json');margins=None
    if stage=='evaluation':
        margins=read(OUT/'calibration/margins.json')
        registration=OUT/'evaluation_registration.json'
        if not registration.exists():
            dump(registration,{'registered_at':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),'margins_sha256':sha(OUT/'calibration/margins.json'),'evaluation_repairs_before_registration':0})
        assert sha(OUT/'calibration/margins.json')==read(registration)['margins_sha256']
    repeats=[3] if stage=='calibration' else [4,5]
    jobs=[(mix,repeat,root,margins['cells'][mix] if margins else None) for mix in protocol['data']['compositions'] for repeat in repeats for root in protocol['design']['roots']]
    done=[]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures=[pool.submit(task,j) for j in jobs]
        try:
            for f in as_completed(futures):
                value=f.result();done.append(value)
                dump(OUT/stage/'progress.json',{'completed':len(done),'expected':len(jobs),'last':value['case_id']})
                print(f'R7 {stage} {len(done)}/{len(jobs)} {value["seconds"]:.1f}s',flush=True)
        except Exception as error:
            for f in futures:f.cancel()
            dump(OUT/stage/'failure.json',{'status':'STOPPED','error':repr(error),'saved_case_ids':[d['case_id'] for d in done]})
            raise
    done.sort(key=lambda d:d['case_id'])
    rows=[r for d in done for r in d['rows']]
    expected=protocol['design'][stage+'_repairs'];assert len(rows)==expected
    journal=OUT/stage/'metrics.jsonl';journal.write_text(''.join(__import__('json').dumps(r,allow_nan=False)+'\n' for r in rows))
    totals={k:sum(d['checks'][k] for d in done) for k in done[0]['checks'] if k!='cross_implementation_max_abs_difference'}
    totals['cross_implementation_max_abs_difference']=max(d['checks']['cross_implementation_max_abs_difference'] for d in done)
    dump(OUT/stage/'receipt.json',{'status':'PASS','cases':len(done),'new_exploratory_repairs':len(rows),'new_confirmatory_samples':0,'offline_candidate_continuations':sum(d['offline_candidate_continuations'] for d in done),'metrics_sha256':sha(journal),**totals})
    if stage=='calibration':
        cells={}
        for mix in protocol['data']['compositions']:
            samples=[s for d in done if d['composition']==mix for s in d['candidate_samples']]
            cells[mix]={net+'/'+rule:fit_envelope([s for s in samples if s['condition']==net+'/'+rule]) for net in NETWORKS for rule in RULES}
        target=OUT/'calibration/margins.json';assert not target.exists()
        dump(target,{'status':'FROZEN_BEFORE_EVALUATION','registered_at':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),'source_metrics_sha256':sha(journal),'cells':cells,'future_coverage_guarantee':False})
    print(f'R7 {stage} PASS {len(rows)} repairs',flush=True)


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('stage',choices=['calibration','evaluation']);ap.add_argument('--workers',type=int,default=4)
    a=ap.parse_args();main(a.stage,a.workers)
