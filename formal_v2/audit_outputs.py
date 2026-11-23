"""Independent reconstruction from every persisted physical v2 event log."""
import csv
import hashlib
import json
import math
import sys
from collections import Counter,defaultdict
from functools import lru_cache
from pathlib import Path
from time import perf_counter
from datetime import datetime,timezone

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from sail.audit import audit_result
from sail.development import dump
from sail.experiment import workload_from_json
from sail.frozen import result_from_json
from sail.model import Failure,Platform
from sail.simulator import content_hash
from v2_preparation.frozen import verify_v2,sha


def close(a,b):
    if a is None or b is None:return a is b
    return math.isclose(a,b,rel_tol=1e-9,abs_tol=1e-9)


def write_csv(path,rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)


def independent_order(context,plan):
    # Fenwick counts, separate from the sealed merge-sort metric implementation.
    old=dict(context.old_assignment);new=plan.assignment;inversions=pairs=retained=0
    for node,q in enumerate(context.original_queues):
        kept=[v for v in q if v in context.Q-context.F and new[v]==old[v]];rank={v:i+1 for i,v in enumerate(kept)}
        sequence=[rank[v] for v in plan.queues[node] if v in rank];n=len(kept);tree=[0]*(n+1);seen=0
        assert len(sequence)==n
        for value in sequence:
            i=value;before=0
            while i:before+=tree[i];i-=i&-i
            inversions+=seen-before;i=value
            while i<=n:tree[i]+=1;i+=i&-i
            seen+=1
        pairs+=n*(n-1)//2;retained+=n
    return {'queue_inversions':inversions,'comparable_pairs':pairs,'retained_tasks':retained,'order_disturbance':inversions/pairs if pairs else None}


def main():
    began=perf_counter()
    freeze=ROOT/'freeze/g2_v2_20261025';out=ROOT/'results/g2_v2_20261025';folder=ROOT/'formal_v2/reports'
    cfg,mf=verify_v2(ROOT,freeze);summary=json.loads((out/'execution_summary.json').read_text())
    rows=[json.loads(x) for x in (out/'metrics.jsonl').read_text().splitlines()];byid={r['job_id']:r for r in rows};jobs={j['id']:j for j in mf['jobs']}
    assert summary['all_complete'] and len(rows)==len(byid)==len(jobs)==15780 and set(byid)==set(jobs)
    assert not list((out/'failures').glob('*.json'))
    assert summary['freeze_id']==sha(freeze/'inputs_manifest.json')==json.loads((out/'RUN_MANIFEST.json').read_text())['freeze_id']
    assert Counter(r['status'] for r in rows)=={'COMPLETE':15660,'ALIAS':120}
    state=json.loads((ROOT/'progress/current.json').read_text());state.update({'stage':'V2_INDEPENDENT_LOG_AUDIT','audit_labels_completed':0});dump(ROOT/'progress/current.json',state)
    unique={}
    for r in rows:
        path=r['event_file'];assert path not in unique or unique[path]==r['event_sha256'];unique[path]=r['event_sha256']
    assert len(unique)==15660
    for path,expected in unique.items():assert sha(out/path)==expected,path
    bases={b['id']:b for b in mf['bases']};scenarios={s['id']:s for s in mf['scenarios']}
    @lru_cache(maxsize=10)
    def load(jid):return result_from_json(json.loads((out/byid[jid]['event_file']).read_text()))
    @lru_cache(maxsize=8)
    def inputs(bid):
        b=bases[bid];w=workload_from_json(json.loads((freeze/b['workload_file']).read_text()));p=Platform(tuple(b['speeds']),b['bandwidth'])
        return w,p,json.loads((freeze/b['truth_file']).read_text()),load('ref-'+bid)
    references=[];processed=[];workflows=[];contexts=defaultdict(set);events=physical=budget_checks=0;recomputed={}
    families={'A':['Montage','Epigenomics','SRA Search'],'B':['Montage','Montage','Epigenomics'],'C':['Epigenomics','SRA Search','SRA Search']}
    for i,row in enumerate(rows):
        jid=row['job_id'];job=jobs[jid];assert row['kind']==job['kind'] and row['base_id']==job['base_id']
        w,p,truth,ref=inputs(row['base_id']);actual=load(jid)
        if row['kind']=='reference':
            a=audit_result(actual,w,p,realized_work=truth);assert close(a['makespan'],row['makespan'])
            references.append({**bases[row['base_id']],'awct':a['awct'],'makespan':a['makespan'],'tasks':len(w.tasks),'events_checked':a['events_checked']})
            events+=a['events_checked'];physical+=1
        else:
            s=scenarios[job['scenario_id']];assert row['method']==job['method'] and row['scenario_id']==s['id']
            for key in ('root_seed','mix','nodes','ccr','failure_fraction','variant'):assert row[key]==s[key]
            fault=Failure(ref.makespan*s['failure_fraction'],s['failed_node'],s['control_delay_pbar_units']*w.pbar)
            if row['status']=='ALIAS':
                source=byid[job['execution_alias_of']];assert row['execution_alias_of']==job['execution_alias_of']
                assert row['event_file']==source['event_file'] and row['event_sha256']==source['event_sha256'] and row['full_application_seconds'] is None
                for key in ('awct','makespan','churn','cdi','protected_count','quality_feasible'):assert row.get(key)==source.get(key)
                recomputed[jid]=recomputed[job['execution_alias_of']]
            else:
                a=audit_result(actual,w,p,realized_work=truth,expected_failure=fault,reference=ref)
                events+=a['events_checked'];physical+=1
                for key in ('awct','makespan','churn','cdi'):assert close(row[key],a[key]),(jid,key)
                recomputed[jid]={k:a[k] for k in ('awct','makespan','cdi')}
            ctx=actual.context;assert ctx.time==fault.time and ctx.failed_node==fault.node
            assert [e for e in actual.events if e['time']<fault.time]==[e for e in ref.events if e['time']<fault.time]
            b0=load(job['reference_b0_job']);assert ctx==b0.context
            scope=set(next(e for e in actual.events if e['kind']=='PLAN_APPLIED')['details']['scope'])
            old=dict(ctx.old_assignment);new=actual.applied_plan.assignment;moves=sum(new[v]!=old[v] for v in ctx.Q-ctx.F)
            assert close(row['churn'],moves/max(1,len(ctx.Q)))
            factory=job.get('factory_method',job['method'])
            if factory=='B0':assert scope==set(ctx.F)
            elif factory in ('B1','LegacySAIL'):
                reach=set(ctx.F);successors=defaultdict(set)
                for u,v in w.edges:successors[u].add(v)
                front=set(ctx.F);bounded=[set(ctx.F)]
                while front:
                    following=set().union(*(successors[v] for v in front))-reach;reach|=following;front=following
                    if len(bounded)<3:bounded.append(reach&set(ctx.Q))
                while len(bounded)<3:bounded.append(bounded[-1])
                if factory=='B1':assert scope==reach&set(ctx.Q)
                else:assert scope in bounded
            else:assert scope==set(ctx.Q)
            if factory in ('BudgetHEFT10','BudgetSelect10','PoolMinAWCT10','QueueRepair0','B0AssignmentReorder','B0'):
                theta=0 if factory in ('B0','QueueRepair0','B0AssignmentReorder') else job.get('budget_theta',.1)
                assert moves<=math.floor(theta*max(1,len(ctx.Q)));budget_checks+=1
            if factory=='B0AssignmentReorder':assert actual.applied_plan.assignment==b0.applied_plan.assignment
            order=independent_order(ctx,actual.applied_plan)
            for key,value in order.items():assert close(row[key],value),(jid,key)
            start,base,b0start=dict(actual.starts),dict(ref.starts),dict(b0.starts)
            cdi=sum(max(0,start[v]-base[v]) for v in ctx.P)/len(ctx.P)/w.pbar if ctx.P else None
            signed=sum(start[v]-b0start[v] for v in ctx.P)/len(ctx.P)/w.pbar if ctx.P else None
            assert close(cdi,row['cdi'])
            if factory!='B0':assert close(signed,row['same_fault_signed_delay'])
            b2id=job['reference_b0_job'].removesuffix('-B0')+'-B2';b2=load(b2id)
            contexts[s['id']].add(content_hash(ctx))
            processed.append({**{k:row[k] for k in ('job_id','scenario_id','base_id','method','root_seed','mix','nodes','ccr','failure_fraction','variant','status','budget_theta')},
                'awct':recomputed[jid]['awct'],'makespan':recomputed[jid]['makespan'],'cdi':recomputed[jid]['cdi'],'churn':moves/max(1,len(ctx.Q)),
                'protected_count':len(ctx.P),'pending_count':len(ctx.Q),'F_count':len(ctx.F),'protected_fraction':len(ctx.P)/len(ctx.Q) if ctx.Q else None,
                'optional_moves':moves,'same_fault_signed_delay':signed,**order,'tasks':len(w.tasks),'repair_scope_size':len(scope),
                'quality_feasible':row.get('quality_feasible'),'selected_candidate':row.get('selected_candidate'),
                'actual_AWCT_gt_1.05_B2':actual.awct>1.05*b2.awct,'actual_AWCT_gt_1.05_B2_tolerant':actual.awct>1.05*b2.awct+1e-9,
                'full_application_seconds':row['full_application_seconds'],'execution_alias_of':row.get('execution_alias_of'),
                'cpu_seconds':actual.cpu_seconds,'wasted_cpu_seconds':actual.wasted_cpu_seconds,'wasted_work':actual.wasted_work,
                'transfer_bytes':actual.transfer_bytes,'total_attempts':sum(n for v,n in actual.attempts),'restarted_tasks':sum(n>1 for v,n in actual.attempts),
                'context_sha256':content_hash(ctx)})
            refwf=dict(ref.workflow_finishes)
            for wid,finish in actual.workflow_finishes:
                workflows.append({'job_id':jid,'scenario_id':s['id'],'method':row['method'],'variant':s['variant'],'mix':s['mix'],'root_seed':s['root_seed'],
                    'workflow':wid,'family':families[s['mix']][int(wid[1:])],'completion':finish,'reference_completion':refwf[wid],'slowdown':finish/refwf[wid]})
        if (i+1)%500==0:
            print(f'persisted v2 audit {i+1}/{len(rows)}',flush=True)
            state.update({'audit_labels_completed':i+1,'updated_at':datetime.now(timezone.utc).isoformat()});dump(ROOT/'progress/current.json',state)
    assert physical==15660 and len(references)==840 and len(processed)==14940 and len(workflows)==44820
    assert len(contexts)==1920 and all(len(h)==1 for h in contexts.values())
    for r in processed:
        if r['method'].startswith('BudgetSelect'):
            peer=r['method'].replace('BudgetSelect','PoolMinAWCT')
            match=next(x for x in processed if x['scenario_id']==r['scenario_id'] and x['method']==peer)
            assert r['quality_feasible']==match['quality_feasible']
    write_csv(folder/'data/run_metrics.csv',processed);dump(folder/'data/run_metrics.json',processed)
    write_csv(folder/'data/workflow_slowdowns.csv',workflows);dump(folder/'data/reference_metrics.json',references)
    coverage={}
    for variant in sorted({r['variant'] for r in processed}):
        group=[r for r in processed if r['variant']==variant and r['method'].startswith('BudgetSelect')]
        coverage[variant]={'scenarios':len(group),'F_empty':sum(r['F_count']==0 for r in group),'P_empty':sum(r['protected_count']==0 for r in group)}
    result={'status':'PASS','nominal_labels':15780,'physical_executions':physical,'alias_records':120,'reference_jobs':840,'failure_label_rows':14940,
        'unique_event_files':len(unique),'event_records_independently_recomputed':events,'shared_context_conditions':1920,'hard_budget_checks':budget_checks,
        'hard_budget_violations':0,'locked_assignment_mismatches':0,'same_pool_quality_flag_mismatches':0,'coverage':coverage,
        'raw_metrics_sha256':sha(out/'metrics.jsonl'),'freeze_id':summary['freeze_id'],
        'audit_wall_seconds':perf_counter()-began,
        'note':'Raw rows unchanged; B0 own signed delay derived as zero on nonempty P. Order statistic independently recomputed with Fenwick counts.'}
    dump(folder/'audit_summary.json',result);print(json.dumps(result,ensure_ascii=False))
    state.update({'stage':'V2_AUDIT_COMPLETE_STATS_PENDING','audit_labels_completed':15780,'updated_at':datetime.now(timezone.utc).isoformat()});dump(ROOT/'progress/current.json',state)


if __name__=='__main__':main()
