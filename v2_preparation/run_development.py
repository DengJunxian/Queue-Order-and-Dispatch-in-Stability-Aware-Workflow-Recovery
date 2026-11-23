"""Evaluate fixed v2 choices on independent synthetic development/validation only."""
import hashlib
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from time import perf_counter

import numpy as np

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from sail.audit import audit_result
from sail.data import actual_work,bandwidth_for_ccr,failure_node,speed_vector
from sail.development import dump
from sail.metrics import paired_metrics
from sail.model import Failure,Platform
from sail.scheduling import initial_heft
from sail.simulator import Simulator,content_hash
from v2_preparation.experiment import synthetic_v2,make_method


def main():
    out=ROOT/'v2_preparation/development';out.mkdir(parents=True,exist_ok=True)
    sources={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'v2_preparation/experiment.py',ROOT/'v2_preparation/policies.py',Path(__file__),ROOT/'v2_preparation/spec.json')}
    marker=out/'RUN_MANIFEST.json'
    if marker.exists():assert json.loads(marker.read_text())['source_sha256']==sources
    else:dump(marker,{'purpose':'SYNTHETIC_DEVELOPMENT_VALIDATION','source_sha256':sources,'new_real_test_runs':0})
    journal=out/'metrics.jsonl';rows={}
    if journal.exists():
        for line in journal.read_text().splitlines():r=json.loads(line);assert r['job_id'] not in rows;rows[r['job_id']]=r
    reference_count=0;started=perf_counter()
    with journal.open('a') as log:
        for split,seeds in (('development',range(71000,71020)),('validation',range(72000,72010))):
            for seed in seeds:
                for mix in 'ABC':
                    w=synthetic_v2(seed,mix)
                    for nodes in (4,8):
                        for ccr in (.5,2):
                            p=Platform(speed_vector(seed,mix,nodes),bandwidth_for_ccr(w,ccr));initial=initial_heft(w,p);ref=Simulator(w,p,initial.plan).run()
                            reference_count+=1;audit_result(ref,w,p)
                            for fraction in (.3,.6):
                                f=Failure(ref.makespan*fraction,failure_node(seed,mix,nodes));ctx=None
                                for method in ('BudgetHEFT10','BudgetSelect10','PoolMinAWCT10'):
                                    jid=f'{seed}-{mix}-{nodes}-{ccr}-{fraction}-{method}'
                                    if jid in rows:continue
                                    policy=make_method(method,initial);run=Simulator(w,p,initial.plan,failure=f,repair=policy).run()
                                    a=audit_result(run,w,p,expected_failure=f,reference=ref)
                                    if ctx is None:ctx=run.context
                                    else:assert ctx==run.context
                                    assert run.churn<=.1+1e-12
                                    row={'job_id':jid,'split':split,'root_seed':seed,'mix':mix,'nodes':nodes,'ccr':ccr,'failure_fraction':fraction,'method':method,
                                         **paired_metrics(run,ref,w),'events_checked':a['events_checked'],'trace_sha256':run.trace_hash,
                                         'quality_feasible':getattr(policy,'last_quality_feasible',None),'new_real_test':False}
                                    log.write(json.dumps(row,allow_nan=False)+'\n');log.flush();rows[jid]=row
                print(f'{split} root {seed}: {len(rows)}/2160 labels',flush=True)
    allrows=list(rows.values());assert len(rows)==2160
    root_diffs={}
    for comparator in ('PoolMinAWCT10','BudgetHEFT10'):
        indexed={}
        for r in allrows:
            if r['split']=='development' and r['method'] in ('BudgetSelect10',comparator):indexed.setdefault((r['root_seed'],r['mix'],r['nodes'],r['ccr'],r['failure_fraction']),{})[r['method']]=r
        blocks=defaultdict(lambda:defaultdict(list))
        for key,pair in indexed.items():
            a,b=pair['BudgetSelect10'],pair[comparator]
            if a['cdi'] is not None:blocks[key[0]][key[1]].append(a['cdi']-b['cdi'])
        values=[]
        for root in range(71000,71020):
            assert all(blocks[root][m] for m in 'ABC'),'precision undefined: missing Mix within a root'
            values.append(statistics.mean(statistics.mean(blocks[root][m]) for m in 'ABC'))
        sd=statistics.stdev(values);needed=max(30,10*math.ceil(((1.96*sd/.05)**2)/10))
        root_diffs[comparator]={'development_root_mean_differences':values,'sample_SD':sd,'required_rounded_roots':needed,'precision_target_halfwidth':.05}
    required=max(v['required_rounded_roots'] for v in root_diffs.values());choice=30 if required<=30 else 60 if required<=60 else None
    summary={'status':'PASS','fault_labels':2160,'reference_executions_this_invocation':reference_count,'development_scenarios':480,'validation_scenarios':240,
             'independent_synthetic_root_namespaces':[71000,72000],'tests_on_new_real_inputs':0,'events_audited':sum(r['events_checked'] for r in allrows),
             'precision':root_diffs,'precision_selected_root_count':choice,'precision_supported_by_design_rule':choice is not None,
             'precision_note':'Normal-approximation planning heuristic on synthetic development blocks, not a guarantee on unseen real benchmarks; no test outcome used.',
             'wall_seconds':perf_counter()-started}
    dump(out/'summary.json',summary);print(json.dumps({k:v for k,v in summary.items() if k!='precision'}))


if __name__=='__main__':main()
