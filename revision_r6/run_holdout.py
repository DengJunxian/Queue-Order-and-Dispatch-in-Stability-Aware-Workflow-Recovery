"""Execute the complete registered holdout, cross-implementation and link study."""
import argparse,math,time
from concurrent.futures import ProcessPoolExecutor,as_completed
from datetime import datetime
from zoneinfo import ZoneInfo
from statistics import mean
from sail.simulator import Simulator
from sail.data import speed_vector,failure_node,bandwidth_for_ccr
from sail.audit import audit_result
from sail.frozen import result_from_json
from revision_r2.audit_dispatch import audit_result as audit_skip
from revision_r2.dispatch import SkipUnready
from revision_r2.common import Capture,SnapshotReady
from revision_r6.common import *
from revision_r6.audit_clock import audit as audit_second

def verify_registration():
    for reg in ['registration.json','execution_registration.json']:
        for p,h in read(OUT/reg)['files'].items():assert sha(ROOT/p)==h,p

def compare_documents(a,b):
    maximum=0.;count=0
    for field in ['starts','finishes','workflow_finishes']:
        x,y=dict(a[field]),dict(b[field]);assert x.keys()==y.keys()
        for v in x:
            assert math.isclose(x[v],y[v],rel_tol=1e-10,abs_tol=1e-8),(field,v,x[v],y[v])
            maximum=max(maximum,abs(x[v]-y[v]));count+=1
    assert a['context']==b['context']
    return count,maximum

def snapshot_at(w,p,truth,initial,fault):
    capture=Capture(w,p,initial.plan,realized_work=truth,failure=fault,repair=lambda *_:None)
    try:capture.run()
    except SnapshotReady:pass
    return capture.public_snapshot,capture.original_context

def from_doc(doc,ref,w):
    P=doc['context']['P'];ss,rr=dict(doc['starts']),dict(ref['starts']);delta=[(ss[v]-rr[v])/w.pbar for v in P]
    return {'awct':mean(dict(doc['workflow_finishes']).values()),'cdi':mean(max(0.,d) for d in delta) if P else None,'signed':mean(delta) if P else None,'absolute':mean(abs(d) for d in delta) if P else None,'max_positive':max([0.,*delta]) if P else None,'late_fraction':mean(d>1e-8 for d in delta) if P else None,'P':len(P),'F':len(doc['context']['F']),'Q':len(doc['context']['Q']),'churn':doc['churn'],'workflow_completion':dict(doc['workflow_finishes'])}

def evaluate_case(w,p,truth,initial,fault,original,pool,b2,snapshot,context,networks,eta=None,strict_reference=None):
    refs={};runs={};metadata={};forecasts={};poolforecasts={}
    for network in networks:
        for rule in ['strict','skip-unready']:
            key=network+'/'+rule
            refs[key]={'clock':jsonable(ClockExecutor(w,p,initial.plan,truth=truth,rule=rule,network=network,switch_time=fault.time).run())}
            cls=Simulator if rule=='strict' else SkipUnready;kw={} if rule=='strict' else {'switch_time':fault.time}
            if network=='independent':refs[key]['original']=jsonable(strict_reference if rule=='strict' and strict_reference is not None else cls(w,p,initial.plan,realized_work=truth,**kw).run())
            new,selected,rows,info=dispatch_choices(snapshot,context,initial,pool,b2,rule,network,eta=eta.get(rule) if eta is not None else None)
            metadata[key]=info;forecasts[key]={name:{'workflow_completion':dict(c['forecast'].workflow_finishes),'cdi':c['cdi']} for name,c in selected.items()}
            poolforecasts[key]=[{'name':c['name'],'plan':jsonable(c['plan']),'workflow_completion':dict(c['forecast'].workflow_finishes)} for c in rows]
            for name,decision in {**original,**new}.items():
                def fixed(s,c,decision=decision):
                    assert c==context;return decision
                out={'clock':jsonable(ClockExecutor(w,p,initial.plan,truth=truth,rule=rule,network=network,switch_time=fault.time,failure=fault,repair=fixed).run())}
                if network=='independent':out['original']=jsonable(cls(w,p,initial.plan,realized_work=truth,failure=fault,repair=fixed,**kw).run())
                runs[key+'/'+name]=out
    return {'references':refs,'runs':runs,'metadata':metadata,'predictions':forecasts,'pool_forecasts':poolforecasts}

def audit_saved(doc,w,p,truth,fault):
    checks={'original_events':0,'clock_events':0,'cross_implementation_fields':0,'cross_implementation_max_abs_difference':0.,'metric_fields':0,'budget_checks':0,'reference_executions':0,'repair_executions':0,'clock_validation_executions':0}
    for key,r in doc['references'].items():
        network,rule=key.split('/');a=audit_second(r['clock'],w,p,truth,network,fault.time);checks['clock_events']+=a['events'];checks['reference_executions']+=1
        if 'original' in r:
            fun=audit_result if rule=='strict' else audit_skip
            b=fun(result_from_json(r['original']),w,p,realized_work=truth,**({'dispatch_switch_time':fault.time} if rule!='strict' else {}));checks['original_events']+=b['events_checked']
            count,diff=compare_documents(r['original'],r['clock']);checks['cross_implementation_fields']+=count;checks['cross_implementation_max_abs_difference']=max(checks['cross_implementation_max_abs_difference'],diff);checks['clock_validation_executions']+=1
    rows=[]
    for key,r in doc['runs'].items():
        network,rule,name=key.split('/');ref=doc['references'][network+'/'+rule]
        a=audit_second(r['clock'],w,p,truth,network,fault.time);checks['clock_events']+=a['events'];checks['repair_executions']+=1
        if 'original' in r:
            fun=audit_result if rule=='strict' else audit_skip
            b=fun(result_from_json(r['original']),w,p,realized_work=truth,expected_failure=fault,reference=result_from_json(ref['original']),**({'dispatch_switch_time':fault.time} if rule!='strict' else {}));checks['original_events']+=b['events_checked']
            count,diff=compare_documents(r['original'],r['clock']);checks['cross_implementation_fields']+=count;checks['cross_implementation_max_abs_difference']=max(checks['cross_implementation_max_abs_difference'],diff);checks['clock_validation_executions']+=1
        m=from_doc(r['clock'],ref['clock'],w)
        P=r['clock']['context']['P'];cdi=mean(max(0.,a['starts'][v]-dict(ref['clock']['starts'])[v])/w.pbar for v in P) if P else None
        assert cdi is None if m['cdi'] is None else math.isclose(cdi,m['cdi'],abs_tol=1e-9)
        assert math.isclose(mean(a['workflow_completion'].values()),m['awct'],abs_tol=1e-9);checks['metric_fields']+=5
        ctx=r['clock']['context'];old=dict(ctx['old_assignment']);new={v:j for j,q in enumerate(r['clock']['applied_plan']['queues']) for v in q}
        moves=sum(old[v]!=new[v] for v in set(ctx['Q'])-set(ctx['F']));assert moves<=math.floor(.1*max(1,len(ctx['Q'])));checks['budget_checks']+=1
        if name=='ProtectedSubsequence' and rule=='strict' and network=='independent':assert m['max_positive'] is None or m['max_positive']<=1e-8
        rows.append({'network':network,'rule':rule,'method':name,**m,'optional_moves':moves,'guard_metadata':doc['metadata'][network+'/'+rule] if name.startswith('Dispatch') or name=='CalibratedGuard' else None})
    return rows,checks

def task(spec):
    identity,root,nodes,ccr=spec;sid=f'{identity}-r{root}-n{nodes}-c{ccr}'
    target=OUT/'holdout/cases'/f'{sid}.json'
    if target.exists():
        old=read(target);assert sha(ROOT/old['event_file'])==old['event_sha256'];return old
    begin=time.perf_counter();corpus=HoldoutCorpus();w=corpus.workload(identity)
    p=Platform(speed_vector(root,identity,nodes),bandwidth_for_ccr(w,ccr));truth={t.id:t.work for t in w.tasks};initial=initial_heft(w,p)
    ref=Simulator(w,p,initial.plan,realized_work=truth).run();fault=Failure(.6*ref.makespan,failure_node(root,identity,nodes))
    snapshot,context=snapshot_at(w,p,truth,initial,fault);original,pool,b2=original_choices(snapshot,context,initial)
    networks=['independent']+(['shared'] if nodes==4 and ccr==2 else [])
    doc=evaluate_case(w,p,truth,initial,fault,original,pool,b2,snapshot,context,networks,strict_reference=ref)
    doc.update({'spec':spec,'workload':jsonable(w),'platform':jsonable(p),'truth':truth,'initial':jsonable(initial.plan),'failure':jsonable(fault),'public_snapshot':jsonable(snapshot)})
    path=OUT/'holdout/events'/f'{sid}.json.gz';digest=save(path,doc)
    reopened=read(path);rows,checks=audit_saved(reopened,w,p,truth,fault)
    for row in rows:row.update({'case_id':sid,'graph_id':identity,'family':corpus.records[identity]['family'],'root':root,'nodes':nodes,'ccr':ccr})
    result={'case_id':sid,'status':'PASS','event_file':str(path.relative_to(ROOT)),'event_sha256':digest,'rows':rows,'checks':checks,'seconds':time.perf_counter()-begin}
    dump(target,result);return result

def main(workers=4):
    verify_registration();corpus=HoldoutCorpus();jobs=[(identity,root,nodes,ccr) for identity in sorted(corpus.records) for root in range(91000,91004) for nodes in [4,8] for ccr in [.5,2]]
    done=[]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        future={pool.submit(task,j):j for j in jobs}
        try:
            for f in as_completed(future):
                result=f.result();done.append(result)
                dump(OUT/'holdout/progress.json',{'completed':len(done),'expected':len(jobs),'last_case':result['case_id'],'last_seconds':result['seconds']})
                print(f'R6 holdout {len(done)}/{len(jobs)} {result["seconds"]:.1f}s',flush=True)
        except Exception as e:
            for f in future:f.cancel()
            dump(OUT/'holdout/failure.json',{'status':'STOPPED','error':repr(e),'completed_case_ids':[r['case_id'] for r in done]});raise
    rows=[r for x in sorted(done,key=lambda x:x['case_id']) for r in x['rows']]
    (OUT/'holdout/metrics.jsonl').write_text(''.join(json.dumps(r,allow_nan=False)+'\n' for r in rows))
    totals={k:sum(x['checks'][k] for x in done) for k in done[0]['checks'] if k!='cross_implementation_max_abs_difference'}
    totals['cross_implementation_max_abs_difference']=max(x['checks']['cross_implementation_max_abs_difference'] for x in done)
    assert len(rows)==4800 and len(done)==192
    dump(OUT/'holdout/receipt.json',{'status':'PASS','completed_at':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),'cases':192,'new_exploratory_repair_executions':4800,'new_confirmatory_samples':0,'new_graphs':12,**totals,'metrics_sha256':sha(OUT/'holdout/metrics.jsonl')})
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--workers',type=int,default=4);main(p.parse_args().workers)
