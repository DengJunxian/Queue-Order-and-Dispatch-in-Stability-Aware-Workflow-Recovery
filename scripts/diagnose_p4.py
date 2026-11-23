"""Exact trace replays for all main SAIL candidates and prespecified full-apply timing.

These executions are diagnostics, not new independent formal observations.
No sealed algorithm, parameter, input, or statistical estimator is modified.
"""
import json
import statistics
import sys
from collections import Counter
from functools import lru_cache
from pathlib import Path
from time import perf_counter

import numpy as np

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from sail.development import dump
from sail.experiment import make_policy,workload_from_json
from sail.frozen import result_from_json,verify_freeze
from sail.model import Failure,Platform
from sail.policy import OnlineReference
from sail.scheduling import initial_heft
from sail.simulator import Simulator,content_hash
from scripts.analyze_p4_extensions import write_csv


class TimedSimulator(Simulator):
    def _apply(self):
        start=perf_counter()
        super()._apply()
        self.application_seconds=perf_counter()-start


def main():
    freeze=ROOT/'freeze/g2_v1_20261025';out=ROOT/'results/g2_v1_20261025';folder=ROOT/'reports/p4'
    cfg,manifest=verify_freeze(ROOT,freeze)
    assert json.loads((out/'execution_summary.json').read_text())['all_complete']
    rows=[json.loads(x) for x in (out/'metrics.jsonl').read_text().splitlines()];by_id={r['job_id']:r for r in rows}
    bases={b['id']:b for b in manifest['bases']}
    scenarios=[s for s in manifest['scenarios'] if s['variant']=='main']
    scenario_map={s['id']:s for s in scenarios}
    physical_methods=('B0','B1','B2','SAIL','NoStability','Fixed_H1','Fixed_H2')
    timing_cases=[]
    for i in range(20):
        matches=[s for s in scenarios if s['root_seed']==60000+i and s['mix']=='ABC'[i%3]
                 and s['nodes']==(8 if i%2==0 else 4) and s['ccr']==2 and s['failure_fraction']==(0.3 if i%2==0 else 0.6)]
        assert len(matches)==1;timing_cases.append(matches[0]['id'])
    dump(folder/'timing_cases.json',{'selected_before_outcomes':True,'scenario_ids':timing_cases,'methods':physical_methods,'repeats':3})
    @lru_cache(maxsize=8)
    def inputs(base_id):
        b=bases[base_id];w=workload_from_json(json.loads((freeze/b['workload_file']).read_text()))
        p=Platform(tuple(b['speeds']),b['bandwidth']);truth=json.loads((freeze/b['truth_file']).read_text())
        initial=initial_heft(w,p);ref=load('ref-'+base_id)
        return w,p,truth,initial,ref
    @lru_cache(maxsize=16)
    def load(job_id):return result_from_json(json.loads((out/by_id[job_id]['event_file']).read_text()))
    replays=0;checked_events=0;timings=[];diagnostics=[]
    def replay(s,method):
        nonlocal replays,checked_events
        w,p,truth,initial,ref=inputs(s['base_id'])
        policy=make_policy(method,OnlineReference.from_initial(initial),cfg['selected_lambda'],cfg['selected_mu'])
        fault=Failure(ref.makespan*s['failure_fraction'],s['failed_node'],s['control_delay_pbar_units']*w.pbar)
        engine=TimedSimulator(w,p,initial.plan,realized_work=truth,failure=fault,repair=policy)
        run=engine.run();stored=load(f"run-{s['id']}-{method}")
        assert run.trace_hash==stored.trace_hash,(s['id'],method)
        assert run==stored,(s['id'],method,'run result')
        replays+=1;checked_events+=len(run.events)
        return policy,run,engine.application_seconds
    for i,s in enumerate(scenarios):
        policy,run,elapsed=replay(s,'SAIL');cs=policy.last_candidates;chosen=policy.last_selection.candidate
        without=load(f"run-{s['id']}-NoStability")
        diagnostics.append({'scenario_id':s['id'],**{k:s[k] for k in ('root_seed','mix','nodes','ccr','failure_fraction')},
                            'unique_scopes':cs.unique_scopes,'unique_plans':cs.unique_plans,'selected_hop':chosen.hop,
                            'selected_aliases':','.join(str(x) for x in chosen.aliases),'selected_scope_size':len(chosen.scope),
                            'F_count':len(run.context.F),'Q_count':len(run.context.Q),'P_count':len(run.context.P),
                            'nondegenerate_effective_applicable':bool(run.context.F and run.context.P and cs.unique_plans>1),
                            'different_plan_from_NoStability':run.applied_plan!=without.applied_plan,
                            'selected_predicted_CDI':chosen.predicted_cdi,'selected_predicted_AWCT_ratio':chosen.awct_ratio,
                            'selected_predicted_Churn':chosen.churn,'trace_sha256':run.trace_hash})
        if s['id'] in timing_cases:
            timings.append({'scenario_id':s['id'],'method':'SAIL','repeat':0,'full_application_seconds':elapsed})
        if (i+1)%60==0:print(f'candidate exact replay {i+1}/720',flush=True)
    for i,sid in enumerate(timing_cases):
        s=scenario_map[sid]
        # Cyclic method order is fixed by scenario index, independent of outcomes.
        ordered=physical_methods[i%7:]+physical_methods[:i%7]
        for repeat in range(3):
            for method in ordered:
                if method=='SAIL' and repeat==0:continue
                _,_,elapsed=replay(s,method)
                timings.append({'scenario_id':sid,'method':method,'repeat':repeat,'full_application_seconds':elapsed})
        if (i+1)%5==0:print(f'timing scenarios {i+1}/20',flush=True)
    assert replays==1120 and len(diagnostics)==720 and len(timings)==420
    by_mix={}
    for mix in 'ABC':
        g=[r for r in diagnostics if r['mix']==mix]
        by_mix[mix]={'scenarios':len(g),'unique_scopes':dict(Counter(r['unique_scopes'] for r in g)),
                     'unique_plans':dict(Counter(r['unique_plans'] for r in g)),
                     'selected_hops':dict(Counter(r['selected_hop'] for r in g)),
                     'effective_applicable_nondegenerate':sum(r['nondegenerate_effective_applicable'] for r in g),
                     'different_plan_from_NoStability':sum(r['different_plan_from_NoStability'] for r in g)}
    timing_summary=[]
    for method in physical_methods:
        g=[r for r in timings if r['method']==method];values=[r['full_application_seconds'] for r in g]
        timing_summary.append({'method':method,'scenario_units':20,'samples':len(values),'repeats':3,
                               'p50_seconds':statistics.median(values),'p95_seconds':float(np.quantile(values,0.95)),
                               'max_seconds':max(values)})
    write_csv(folder/'data/candidate_diagnostics.csv',diagnostics);write_csv(folder/'data/full_application_timings.csv',timings)
    write_csv(folder/'data/timing_summary.csv',timing_summary)
    dump(folder/'diagnostic_summary.json',{'status':'PASS','exact_trace_replays':replays,'event_records_compared':checked_events,
         'main_SAIL_candidates':720,'by_mix':by_mix,'timing_summary':timing_summary,
         'timing_boundary':'entire Simulator._apply: snapshot + policy + validate + input invalidation + plan application',
         'timing_note':'Descriptive wall time on this local host. 20 scenario units, 3 repeats; NoChurn is an alias with no independent sample.',
         'formal_counts_unchanged':True,'new_independent_scenarios':0})


if __name__=='__main__':main()
