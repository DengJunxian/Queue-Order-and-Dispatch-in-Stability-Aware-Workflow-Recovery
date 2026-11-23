"""Rebuild plans and both execution implementations from portable saved inputs."""
import argparse,math
from sail.experiment import workload_from_json
from revision_r6.common import *
from revision_r6.run_holdout import snapshot_at,evaluate_case,audit_saved,compare_documents
from sail.simulator import Simulator

def main(output,all_cases=False):
    ledger=read(OUT/'compact/manifest.json')['entries']
    chosen=ledger if all_cases else [next(e for e in ledger if e['stage']=='holdout' and '-n4-c2' in e['case_id']),next(e for e in ledger if e['stage']=='measured/evaluation')]
    reports=[];compared=0;maximum=0.;physical=0
    for e in chosen:
        file=ROOT/e['compact_path'];assert sha(file)==e['compact_sha256'];d=read(file)
        w=workload_from_json(d['workload']);p=Platform(tuple(d['platform']['speeds']),d['platform']['bandwidth']);truth=d['truth'];fault=Failure(**d['failure']);initial=initial_heft(w,p)
        assert jsonable(initial.plan)==d['initial']
        snapshot,context=snapshot_at(w,p,truth,initial,fault);assert jsonable(snapshot)==d['public_snapshot']
        original,pool,b2=original_choices(snapshot,context,initial)
        nets=sorted({key.split('/')[0] for key in d['references']});eta=read(OUT/'measured/calibration.json')['eta'] if e['stage']=='measured/evaluation' else None
        ref=Simulator(w,p,initial.plan,realized_work=truth).run()
        new=evaluate_case(w,p,truth,initial,fault,original,pool,b2,snapshot,context,nets,eta=eta,strict_reference=ref)
        assert new['metadata']==d['metadata'] and new['predictions']==d['predictions']
        for collection in ['references','runs']:
            assert new[collection].keys()==d[collection].keys()
            for key,b in new[collection].items():
                count,diff=compare_documents(b['clock'],d[collection][key]['clock']);compared+=count;maximum=max(maximum,diff)
                assert b['clock']['applied_plan']==d[collection][key]['clock']['applied_plan']
        rows,checks=audit_saved(new,w,p,truth,fault)
        physical+=checks['reference_executions']+checks['repair_executions']+checks['clock_validation_executions']
        reports.append({'case_id':e['case_id'],'stage':e['stage'],'checks':checks})
    result={'status':'PASS','replayed_cases':len(chosen),'physical_validation_executions':physical,'saved_clock_fields_compared':compared,'maximum_timing_difference':maximum,'new_scientific_samples':0,'cases':reports}
    dump(output,result);print(json.dumps({k:v for k,v in result.items() if k!='cases'}))
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--all',action='store_true');ap.add_argument('--output',required=True);a=ap.parse_args();main(a.output,a.all)
