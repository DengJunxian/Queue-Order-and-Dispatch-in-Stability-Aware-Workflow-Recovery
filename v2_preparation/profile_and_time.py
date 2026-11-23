"""Single-process full application timing plus synthetic end-to-end cost profiles."""
import hashlib
import json
import statistics
import sys
from functools import lru_cache
from pathlib import Path
from time import perf_counter

import numpy as np

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from research_v2.diagnose_existing import write_csv
from sail.audit import audit_result
from sail.data import actual_work,bandwidth_for_ccr,failure_node,speed_vector
from sail.development import dump
from sail.experiment import workload_from_json
from sail.frozen import result_from_json,verify_freeze
from sail.metrics import paired_metrics
from sail.model import Failure,Platform
from sail.scheduling import initial_heft
from sail.simulator import Simulator
from v2_preparation.experiment import METHODS,make_method,synthetic_v2


class TimedSimulator(Simulator):
    def _apply(self):
        t=perf_counter();super()._apply();self.application_seconds=perf_counter()-t


def main():
    folder=ROOT/'v2_preparation';freeze=ROOT/'freeze/g2_v1_20261025';old=ROOT/'results/g2_v1_20261025'
    _,mf=verify_freeze(ROOT,freeze);bases={b['id']:b for b in mf['bases']};scenarios={s['id']:s for s in mf['scenarios']}
    indexes={}
    for loc in ('results/g2_v1_20261025','research_v2/pilot','research_v2/order_pilot','v2_preparation/ablation'):
        for r in [json.loads(x) for x in (ROOT/loc/'metrics.jsonl').read_text().splitlines()]:
            indexes[(r.get('scenario_id'),r.get('method'))]=(ROOT/loc,r)
            if r.get('kind')=='reference':indexes[(r['base_id'],'reference')]=(ROOT/loc,r)
    @lru_cache(maxsize=8)
    def inputs(bid):
        b=bases[bid];w=workload_from_json(json.loads((freeze/b['workload_file']).read_text()));p=Platform(tuple(b['speeds']),b['bandwidth'])
        root,r=indexes[(bid,'reference')];ref=result_from_json(json.loads((root/r['event_file']).read_text()))
        return w,p,json.loads((freeze/b['truth_file']).read_text()),initial_heft(w,p),ref
    timing_design=json.loads((folder/'profile_design.json').read_text());times=[]
    ids=json.loads((ROOT/'reports/p4/timing_cases.json').read_text())['scenario_ids'];methods=timing_design['timing_methods']
    for i,sid in enumerate(ids):
        s=scenarios[sid];w,p,truth,initial,ref=inputs(s['base_id']);fault=Failure(ref.makespan*s['failure_fraction'],s['failed_node'])
        ordered=methods[i%len(methods):]+methods[:i%len(methods)]
        for repeat in range(3):
            for method in ordered:
                simulator=TimedSimulator(w,p,initial.plan,realized_work=truth,failure=fault,repair=make_method(method,initial));run=simulator.run()
                root,r=indexes[(sid,method)];stored=result_from_json(json.loads((root/r['event_file']).read_text()));assert run==stored
                times.append({'scenario_id':sid,'method':method,'repeat':repeat,'full_application_seconds':simulator.application_seconds,'exact_trace_match':True})
        if (i+1)%5==0:print(f'full application timing {i+1}/20 cases',flush=True)
    write_csv(folder/'reports/full_application_times.csv',times)
    summary=[{'method':m,'scenario_units':20,'samples':60,'repeats':3,'p50_seconds':statistics.median(r['full_application_seconds'] for r in times if r['method']==m),
              'p95_seconds':float(np.quantile([r['full_application_seconds'] for r in times if r['method']==m],.95))} for m in methods]
    dump(folder/'reports/full_application_summary.json',{'boundary':timing_design['timing_boundary'],'summary':summary,'exact_trace_matches':len(times),
        'host':'local macOS arm64; one process; other host activity uncontrolled','timing_repeats_are_independent_experiments':False})
    profiles=[];references=[]
    for i in range(20):
        seed=71000+i;mix='ABC'[i%3];nodes=8 if i%2==0 else 4;w=synthetic_v2(seed,mix);p=Platform(speed_vector(seed,mix,nodes),bandwidth_for_ccr(w,2))
        cv=(0,.1,.3)[i%3];truth=actual_work(w,seed,mix,cv);t=perf_counter();initial=initial_heft(w,p);ref=Simulator(w,p,initial.plan,realized_work=truth).run();audit_result(ref,w,p,realized_work=truth)
        dump(folder/f'profiles/{i}/reference.json',ref);references.append(perf_counter()-t)
        fault=Failure(ref.makespan*(.3 if i%2==0 else .6),failure_node(seed,mix,nodes),.1*w.pbar if i%4==3 else 0)
        for method in METHODS:
            t=perf_counter();run=Simulator(w,p,initial.plan,realized_work=truth,failure=fault,repair=make_method(method,initial)).run()
            audit_result(run,w,p,realized_work=truth,expected_failure=fault,reference=ref);paired_metrics(run,ref,w);dump(folder/f'profiles/{i}/{method}.json',run)
            profiles.append({'case':i,'seed':seed,'mix':mix,'nodes':nodes,'cv':cv,'method':method,'end_to_end_seconds':perf_counter()-t,'events':len(run.events)})
        if (i+1)%5==0:print(f'end-to-end profile {i+1}/20 cases',flush=True)
    stats={m:float(np.quantile([r['end_to_end_seconds'] for r in profiles if r['method']==m],.95)) for m in METHODS}
    dump(folder/'reports/runtime_profile.json',{'p95_end_to_end_seconds':stats,'p95_reference_seconds':float(np.quantile(references,.95)),
         'profile_runs':180,'references':20,'new_real_test_runs':0,'source':'20 prescribed synthetic development cases; all methods serialized and independently audited',
         'full_application_diagnostic_replays':420})
    write_csv(folder/'reports/runtime_profile_samples.csv',profiles)


if __name__=='__main__':main()
