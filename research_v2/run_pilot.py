"""Run all predeclared exploratory controls on the already-seen v1 scenarios."""
import hashlib
import json
import math
import sys
from datetime import datetime,timezone
from functools import lru_cache
from pathlib import Path
from time import perf_counter

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from research_v2.policies import BudgetPolicy,BudgetSelect
from sail.audit import audit_result
from sail.development import dump
from sail.experiment import workload_from_json
from sail.frozen import result_from_json,verify_freeze
from sail.metrics import paired_metrics
from sail.model import Failure,Platform
from sail.policy import OnlineReference
from sail.scheduling import initial_heft
from sail.simulator import Simulator,content_hash


def main():
    freeze=ROOT/'freeze/g2_v1_20261025';old=ROOT/'results/g2_v1_20261025';out=ROOT/'research_v2/pilot'
    _,manifest=verify_freeze(ROOT,freeze);spec=json.loads((ROOT/'research_v2/pilot_spec.json').read_text())
    assert json.loads((ROOT/'research_v2/reports/pytest_summary.json').read_text())['failed']==0
    out.mkdir(parents=True,exist_ok=True)
    sources={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [ROOT/'research_v2/policies.py',ROOT/'research_v2/pilot_spec.json',ROOT/'research_v2/run_pilot.py']}
    marker=out/'RUN_MANIFEST.json'
    if marker.exists():assert json.loads(marker.read_text())['source_sha256']==sources
    else:dump(marker,{'purpose':spec['purpose'],'source_sha256':sources,'scenarios':900,'method_labels':2700,'new_independent_test_sets':0})
    legacy={r['job_id']:r for r in [json.loads(x) for x in (old/'metrics.jsonl').read_text().splitlines()]}
    bases={b['id']:b for b in manifest['bases']}
    @lru_cache(maxsize=8)
    def load_old(job_id):return result_from_json(json.loads((old/legacy[job_id]['event_file']).read_text()))
    @lru_cache(maxsize=8)
    def inputs(base_id):
        b=bases[base_id];w=workload_from_json(json.loads((freeze/b['workload_file']).read_text()))
        return w,Platform(tuple(b['speeds']),b['bandwidth']),json.loads((freeze/b['truth_file']).read_text()),initial_heft(w,Platform(tuple(b['speeds']),b['bandwidth'])),load_old('ref-'+base_id)
    journal=out/'metrics.jsonl';rows={}
    if journal.exists():
        for line in journal.read_text().splitlines():
            r=json.loads(line);assert r['job_id'] not in rows and hashlib.sha256((out/r['event_file']).read_bytes()).hexdigest()==r['event_sha256'];rows[r['job_id']]=r
    start=perf_counter();began=datetime.now(timezone.utc).isoformat();events=0
    with journal.open('a') as f:
        for i,s in enumerate(manifest['scenarios']):
            w,p,truth,initial,ref=inputs(s['base_id']);b0=load_old(f"run-{s['id']}-B0")
            failure=Failure(ref.makespan*s['failure_fraction'],s['failed_node'],s['control_delay_pbar_units']*w.pbar)
            for method in spec['new_methods']:
                jid=s['id']+'-'+method
                if jid in rows:continue
                policy=BudgetSelect(OnlineReference.from_initial(initial)) if method=='BudgetSelect10' else BudgetPolicy(0 if method=='QueueRepair0' else .1)
                t=perf_counter()
                run=Simulator(w,p,initial.plan,realized_work=truth,failure=failure,repair=policy).run()
                execution_seconds=perf_counter()-t
                independent=audit_result(run,w,p,realized_work=truth,expected_failure=failure,reference=ref);events+=independent['events_checked']
                assert run.context==b0.context and [e for e in run.events if e['time']<failure.time]==[e for e in ref.events if e['time']<failure.time]
                metrics=paired_metrics(run,ref,w,same_fault_b0=b0)
                theta=0 if method=='QueueRepair0' else .1;count=sum(run.applied_plan.assignment[v]!=dict(run.context.old_assignment)[v] for v in run.context.Q-run.context.F)
                assert count<=math.floor(theta*max(1,len(run.context.Q)))
                assert metrics['cdi'] is None and independent['cdi'] is None or math.isclose(metrics['cdi'],independent['cdi'],rel_tol=1e-9,abs_tol=1e-9)
                event_file=f'events/{jid}.json';dump(out/event_file,run)
                row={'job_id':jid,'scenario_id':s['id'],**{k:s[k] for k in ('base_id','root_seed','mix','nodes','ccr','failure_fraction','variant')},
                     'method':method,'status':'COMPLETE',**metrics,'budget_theta':theta,'optional_moves':count,'budget_cap':math.floor(theta*max(1,len(run.context.Q))),
                     'quality_feasible':policy.last_quality_feasible if method=='BudgetSelect10' else None,
                     'selected_candidate':policy.last_selected['name'] if method=='BudgetSelect10' else None,
                     'simulation_wall_seconds':execution_seconds,'event_file':event_file,'event_sha256':hashlib.sha256((out/event_file).read_bytes()).hexdigest(),
                     'events_checked':independent['events_checked'],'context_sha256':content_hash(run.context),'purpose':'EXPLORATORY_POST_G3'}
                f.write(json.dumps(row,allow_nan=False)+'\n');f.flush();rows[jid]=row
            if (i+1)%30==0:print(f'exploratory scenarios {i+1}/900; labels {len(rows)}/2700',flush=True)
    assert len(rows)==2700
    dump(out/'execution_summary.json',{'purpose':'EXPLORATORY_POST_G3','completed_labels':2700,'physical_runs':2700,'original_formal_labels_unchanged':6960,
         'scenarios_reused':900,'new_independent_test_sets':0,'new_independent_scenarios':0,'runtime_errors':0,
         'audited_event_records':sum(r['events_checked'] for r in rows.values()),'started_at':began,'finished_at':datetime.now(timezone.utc).isoformat(),
         'wall_seconds_this_invocation':perf_counter()-start,'all_complete':True})


if __name__=='__main__':main()
