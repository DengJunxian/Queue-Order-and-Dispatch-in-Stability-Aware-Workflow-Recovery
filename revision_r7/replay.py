"""Reconstruct saved R7 choices and executions; creates no new scientific samples."""
import argparse,json,math
from pathlib import Path
from sail.experiment import workload_from_json
from sail.model import Platform,Failure
from sail.simulator import jsonable
from sail.scheduling import initial_heft
from revision_r6.common import original_choices
from revision_r6.run_holdout import snapshot_at,audit_saved
from revision_r6.audit_dispatch_order import audit as audit_dispatch
from revision_r7.run import evaluate,candidate_samples,verify_registration
from revision_r7.portable_io import read_document
from revision_r7.common import ROOT,OUT,read,sha


def main(output,all_cases=False):
    verify_registration();margins=read(OUT/'calibration/margins.json')
    assert sha(OUT/'calibration/margins.json')==read(OUT/'evaluation_registration.json')['margins_sha256']
    paths=sorted((OUT/'calibration/cases').glob('*.json'))+sorted((OUT/'evaluation/cases').glob('*.json')) if all_cases else [OUT/'calibration/cases/BLAST_new-repeat003-r94000.json',OUT/'evaluation/cases/BWA_SRA_new-repeat005-r94001.json']
    counts=[];diffs=[];numeric=0
    def compare(a,b):
        nonlocal numeric
        if isinstance(a,dict):
            assert set(a)==set(b),(set(a),set(b))
            for k in a:compare(a[k],b[k])
        elif isinstance(a,list):
            assert len(a)==len(b)
            for v,w in zip(a,b):compare(v,w)
        elif isinstance(a,(int,float)) and not isinstance(a,bool):
            assert math.isclose(a,b,rel_tol=1e-10,abs_tol=1e-9),(a,b);diffs.append(abs(a-b));numeric+=1
        else:assert a==b,(a,b)
    for path in paths:
        case=read(path);expected=read_document(case);w=workload_from_json(expected['workload']);p=Platform(tuple(expected['platform']['speeds']),expected['platform']['bandwidth']);truth=expected['truth'];fault=Failure(**expected['failure']);initial=initial_heft(w,p)
        assert jsonable(initial.plan)==expected['initial']
        snap,context=snapshot_at(w,p,truth,initial,fault);compare(jsonable(snap),expected['public_snapshot'])
        original,pool,b2=original_choices(snap,context,initial)
        env=margins['cells'][case['composition']] if case['repeat'] in [4,5] else None
        actual=evaluate(w,p,truth,initial,fault,snap,context,original,pool,b2,env)
        for field in ['metadata','predictions','pool_forecasts']:compare(actual[field],expected[field])
        for group in ['references','runs']:
            assert set(actual[group])==set(expected[group])
            for key,run in actual[group].items():
                assert set(run)==set(expected[group][key])
                for engine,v in run.items():
                    target=expected[group][key][engine]
                    compare({k:x for k,x in v.items() if k!='events'},{k:x for k,x in target.items() if k!='events'})
        for a,b in zip(actual['candidate_continuations'],expected['candidate_continuations']):
            compare({k:v for k,v in a.items() if k!='continuation'},{k:v for k,v in b.items() if k!='continuation'})
            compare({k:v for k,v in a['continuation'].items() if k!='events'},{k:v for k,v in b['continuation'].items() if k!='events'})
        rows,checks=audit_saved(actual,w,p,truth,fault)
        for group in ['references','runs']:
            for key,run in actual[group].items():audit_dispatch(run['clock'],key.split('/')[1],fault.time)
        count=sum(len(v) for group in ['references','runs'] for v in actual[group].values())
        counts.append({'case_id':case['case_id'],'physical_validation_executions':count,'offline_candidate_continuations':len(actual['candidate_continuations']),'checks':checks})
        print('Replayed '+case['case_id'],flush=True)
    report={'status':'PASS','cases':len(counts),'new_scientific_samples':0,'physical_validation_executions':sum(x['physical_validation_executions'] for x in counts),'offline_candidate_continuations':sum(x['offline_candidate_continuations'] for x in counts),'numeric_comparisons':numeric,'maximum_timing_difference':max(diffs),'records':counts}
    Path(output).write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({k:v for k,v in report.items() if k!='records'}))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',default='r7-replay.json');p.add_argument('--all',action='store_true');a=p.parse_args();main(a.output,a.all)
