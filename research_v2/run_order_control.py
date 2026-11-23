import hashlib
import json
import sys
from functools import lru_cache
from pathlib import Path
from time import perf_counter

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from research_v2.order_control import B0AssignmentReorder
from sail.audit import audit_result
from sail.development import dump
from sail.experiment import workload_from_json
from sail.frozen import result_from_json,verify_freeze
from sail.metrics import paired_metrics
from sail.model import Failure,Platform
from sail.scheduling import initial_heft
from sail.simulator import Simulator


def main():
    freeze=ROOT/'freeze/g2_v1_20261025';old=ROOT/'results/g2_v1_20261025';out=ROOT/'research_v2/order_pilot'
    _,mf=verify_freeze(ROOT,freeze)
    assert json.loads((ROOT/'research_v2/reports/order_test_summary.json').read_text())['failed']==0
    out.mkdir(parents=True,exist_ok=True)
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'research_v2/order_control.py',ROOT/'research_v2/order_control_spec.json',Path(__file__))}
    if (out/'RUN_MANIFEST.json').exists():assert json.loads((out/'RUN_MANIFEST.json').read_text())['source_sha256']==hashes
    else:dump(out/'RUN_MANIFEST.json',{'purpose':'EXPLORATORY_POST_PILOT_MECHANISM_AMENDMENT','source_sha256':hashes,'planned_runs':900})
    raw={r['job_id']:r for r in [json.loads(x) for x in (old/'metrics.jsonl').read_text().splitlines()]};bases={b['id']:b for b in mf['bases']}
    @lru_cache(maxsize=8)
    def load(jid):return result_from_json(json.loads((old/raw[jid]['event_file']).read_text()))
    @lru_cache(maxsize=8)
    def inputs(bid):
        b=bases[bid];w=workload_from_json(json.loads((freeze/b['workload_file']).read_text()));p=Platform(tuple(b['speeds']),b['bandwidth'])
        return w,p,json.loads((freeze/b['truth_file']).read_text()),initial_heft(w,p),load('ref-'+bid)
    journal=out/'metrics.jsonl';records=[]
    if journal.exists():raise ValueError('Preserve earlier output; this amendment runner does not overwrite or silently resume it.')
    started=perf_counter()
    with journal.open('w') as f:
        for i,s in enumerate(mf['scenarios']):
            w,p,truth,initial,ref=inputs(s['base_id']);fault=Failure(ref.makespan*s['failure_fraction'],s['failed_node'],s['control_delay_pbar_units']*w.pbar)
            b0=load(f"run-{s['id']}-B0")
            run=Simulator(w,p,initial.plan,realized_work=truth,failure=fault,repair=B0AssignmentReorder()).run()
            a=audit_result(run,w,p,realized_work=truth,expected_failure=fault,reference=ref)
            assert run.context==b0.context and run.applied_plan.assignment==b0.applied_plan.assignment
            assert run.churn==0
            path=f"events/{s['id']}-B0AssignmentReorder.json";dump(out/path,run)
            r={**{k:s[k] for k in ('base_id','root_seed','mix','nodes','ccr','failure_fraction','variant')},'scenario_id':s['id'],
               'method':'B0AssignmentReorder','status':'COMPLETE',**paired_metrics(run,ref,w,same_fault_b0=b0),
               'event_file':path,'event_sha256':hashlib.sha256((out/path).read_bytes()).hexdigest(),'events_checked':a['events_checked'],
               'full_B0_assignment_locked':True,'purpose':'EXPLORATORY_POST_PILOT_MECHANISM_AMENDMENT'}
            f.write(json.dumps(r,allow_nan=False)+'\n');f.flush();records.append(r)
            if (i+1)%90==0:print(f'locked-assignment control {i+1}/900',flush=True)
    dump(out/'execution_summary.json',{'all_complete':True,'physical_runs':len(records),'events_audited':sum(r['events_checked'] for r in records),
         'full_assignment_mismatches':0,'new_independent_test_sets':0,'wall_seconds':perf_counter()-started})


if __name__=='__main__':main()
