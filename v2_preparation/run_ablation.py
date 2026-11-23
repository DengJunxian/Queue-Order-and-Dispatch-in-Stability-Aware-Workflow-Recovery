"""Run the pure-AWCT control on all already-seen v1 scenarios."""
import hashlib
import json
import math
import sys
from functools import lru_cache
from pathlib import Path
from time import perf_counter

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from sail.audit import audit_result
from sail.development import dump
from sail.experiment import workload_from_json
from sail.frozen import result_from_json,verify_freeze
from sail.metrics import paired_metrics
from sail.model import Failure,Platform
from sail.policy import OnlineReference
from sail.scheduling import initial_heft
from sail.simulator import Simulator,content_hash
from v2_preparation.metrics import queue_disturbance
from v2_preparation.policies import PoolMinAWCT


def main():
    freeze=ROOT/'freeze/g2_v1_20261025';old=ROOT/'results/g2_v1_20261025';out=ROOT/'v2_preparation/ablation'
    _,mf=verify_freeze(ROOT,freeze);out.mkdir(parents=True,exist_ok=True)
    sources={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'v2_preparation/policies.py',ROOT/'v2_preparation/spec.json',Path(__file__),ROOT/'research_v2/policies.py')}
    marker=out/'RUN_MANIFEST.json'
    if marker.exists():assert json.loads(marker.read_text())['source_sha256']==sources
    else:dump(marker,{'purpose':'EXPLORATORY_SAME_POOL_ABLATION','source_sha256':sources,'planned_labels':900,'new_independent_test_sets':0})
    journal=out/'metrics.jsonl';rows={}
    if journal.exists():
        for line in journal.read_text().splitlines():
            r=json.loads(line);assert r['scenario_id'] not in rows and hashlib.sha256((out/r['event_file']).read_bytes()).hexdigest()==r['event_sha256'];rows[r['scenario_id']]=r
    legacy={r['job_id']:r for r in [json.loads(x) for x in (old/'metrics.jsonl').read_text().splitlines()]}
    source={r['scenario_id']:r for r in [json.loads(x) for x in (ROOT/'research_v2/pilot/metrics.jsonl').read_text().splitlines()] if r['method']=='BudgetSelect10'}
    bases={b['id']:b for b in mf['bases']}
    @lru_cache(maxsize=8)
    def load_old(jid):return result_from_json(json.loads((old/legacy[jid]['event_file']).read_text()))
    @lru_cache(maxsize=8)
    def inputs(bid):
        b=bases[bid];w=workload_from_json(json.loads((freeze/b['workload_file']).read_text()));p=Platform(tuple(b['speeds']),b['bandwidth'])
        return w,p,json.loads((freeze/b['truth_file']).read_text()),initial_heft(w,p),load_old('ref-'+bid)
    begin=perf_counter()
    with journal.open('a') as f:
        for i,s in enumerate(mf['scenarios']):
            if s['id'] in rows:continue
            w,p,truth,initial,ref=inputs(s['base_id']);fault=Failure(ref.makespan*s['failure_fraction'],s['failed_node'],s['control_delay_pbar_units']*w.pbar)
            policy=PoolMinAWCT(OnlineReference.from_initial(initial))
            run=Simulator(w,p,initial.plan,realized_work=truth,failure=fault,repair=policy).run()
            audited=audit_result(run,w,p,realized_work=truth,expected_failure=fault,reference=ref)
            b0=load_old('run-'+s['id']+'-B0');assert run.context==b0.context
            original=result_from_json(json.loads((ROOT/'research_v2/pilot'/source[s['id']]['event_file']).read_text()))
            assert policy.original_decision.plan==original.applied_plan and policy.last_quality_feasible==source[s['id']]['quality_feasible']
            values=paired_metrics(run,ref,w,same_fault_b0=b0);assert run.churn<=.1+1e-12
            path=f"events/{s['id']}-PoolMinAWCT10.json";dump(out/path,run)
            row={**{k:s[k] for k in ('base_id','root_seed','mix','nodes','ccr','failure_fraction','variant')},'scenario_id':s['id'],'method':'PoolMinAWCT10','status':'COMPLETE',
                 **values,**queue_disturbance(run.context,run.applied_plan),'quality_feasible':policy.last_quality_feasible,
                 'candidate_pool_sha256':content_hash(policy.last_candidates),'source_decision_matches':True,'selected_candidate':policy.last_selected['name'],
                 'event_file':path,'event_sha256':hashlib.sha256((out/path).read_bytes()).hexdigest(),'events_checked':audited['events_checked'],
                 'purpose':'EXPLORATORY_SAME_POOL_ABLATION'}
            f.write(json.dumps(row,allow_nan=False)+'\n');f.flush();rows[s['id']]=row
            if (i+1)%90==0:print(f'same-pool control {i+1}/900',flush=True)
    assert len(rows)==900
    dump(out/'execution_summary.json',{'all_complete':True,'labels':900,'physical_runs':900,'source_decision_matches':900,
         'events_audited':sum(r['events_checked'] for r in rows.values()),'runtime_errors':0,'new_independent_test_sets':0,'wall_seconds_this_invocation':perf_counter()-begin})


if __name__=='__main__':main()
