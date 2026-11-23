"""Seal v2 only after data, correctness, precision and resource gates pass."""
import hashlib
import json
import shutil
import sys
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from sail.data import actual_work,bandwidth_for_ccr,failure_node,speed_vector
from sail.development import dump
from v2_preparation.adapters import CorpusV2
from v2_preparation.experiment import METHODS
from v2_preparation.frozen import verify_v2,sha


def main():
    prep=ROOT/'v2_preparation';target=ROOT/'freeze/g2_v2_20261025'
    if (target/'freeze.json').exists():return verify_v2(ROOT,target)[0]
    data=json.loads((prep/'reports/new_data_summary.json').read_text());dev=json.loads((prep/'development/summary.json').read_text())
    tests=json.loads((prep/'reports/test_summary.json').read_text());profile=json.loads((prep/'reports/runtime_profile.json').read_text())
    assert data['status']=='PASS' and data['eligible']==6 and data['unseen_topology_groups']==6 and data['new_test_scheduling_runs']==0
    assert tests['failed']==0 and tests['skipped']==0 and tests['passed']==214
    assert dev['precision_supported_by_design_rule'] and dev['tests_on_new_real_inputs']==0
    n=dev['precision_selected_root_count'];assert n in (30,60)
    c=CorpusV2(ROOT);bases=[];scenarios=[];jobs=[];fault_jobs=[];workloads={}
    for seed in range(81000,81000+n):
        for mix in 'ABC':
            w=c.load_mix(mix,seed);path=f'public/workloads/{seed}-{mix}.json';dump(target/path,w);workloads[seed,mix]=(w,path)
    def base(seed,mix,nodes,ccr,cv):
        w,wfile=workloads[seed,mix];bid=f'{seed}-{mix}-n{nodes}-ccr{ccr:g}-cv{cv:g}';tfile=f'evaluator/{seed}-{mix}-cv{cv:g}.json'
        if not (target/tfile).exists():dump(target/tfile,actual_work(w,seed,mix,cv))
        b={'id':bid,'root_seed':seed,'mix':mix,'nodes':nodes,'ccr':ccr,'runtime_cv':cv,'workload_file':wfile,'truth_file':tfile,
           'speeds':speed_vector(seed,mix,nodes),'bandwidth':bandwidth_for_ccr(w,ccr)}
        bases.append(b);jobs.append({'id':'ref-'+bid,'kind':'reference','base_id':bid});return bid
    core_bases={}
    for seed in range(81000,81000+n):
        for mix in 'ABC':
            for nodes in (4,8):
                for ccr in (.5,2):core_bases[seed,mix,nodes,ccr]=base(seed,mix,nodes,ccr,0)
    def scenario(bid,fraction,delay,variant,methods,theta=.1):
        b=next(b for b in bases if b['id']==bid);seed=b['root_seed'];mix=b['mix'];nodes=b['nodes'];sid=bid+f'-f{fraction:g}-{variant}'
        scenarios.append({'id':sid,'base_id':bid,**{k:b[k] for k in ('root_seed','mix','nodes','ccr')},'failure_fraction':fraction,'variant':variant,
            'failed_node':failure_node(seed,mix,nodes),'control_delay_pbar_units':delay,'fault_time_numeric':None,
            'fault_time_rule':'failure_fraction * matched actual no-fault makespan, computed only after freezing'})
        for method in methods:
            label=method if not variant.startswith('theta') else method.removesuffix('10')+'_theta'+format(theta,'g')
            job={'id':f'run-{sid}-{label}','kind':'failure','base_id':bid,'scenario_id':sid,'method':label,'factory_method':method,
                 'budget_theta':theta,'reference_b0_job':f'run-{sid}-B0'}
            if variant.startswith('theta'):
                main_sid=bid+'-f0.6-main';job['reference_b0_job']='run-'+main_sid+'-B0'
                if method=='BudgetHEFT10' and theta in (0,1):job['execution_alias_of']='run-'+main_sid+('-QueueRepair0' if theta==0 else '-B2')
            fault_jobs.append(job)
        return sid
    for key,bid in core_bases.items():
        for fraction in (.3,.6):scenario(bid,fraction,0,'main',METHODS)
    robust_methods=('B0','B2','BudgetHEFT10','BudgetSelect10','PoolMinAWCT10','B0AssignmentReorder')
    for seed in range(81000,81010):
        for mix in 'ABC':
            for ccr in (.5,2):
                for cv in (.1,.3):scenario(base(seed,mix,4,ccr,cv),.6,0,'cv'+format(cv,'g'),robust_methods)
                scenario(core_bases[seed,mix,4,ccr],.6,.1,'control_delay',robust_methods)
    for seed in range(81000,81010):
        for mix in 'ABC':
            for ccr in (.5,2):
                for theta in (0,.05,.2,.5,1):scenario(core_bases[seed,mix,4,ccr],.6,0,'theta'+format(theta,'g'),('BudgetHEFT10','BudgetSelect10','PoolMinAWCT10'),theta)
    jobs+=fault_jobs
    assert len(jobs)==(15780 if n==60 else 8940) and len({j['id'] for j in jobs})==len(jobs)
    assert len({b['id'] for b in bases})==len(bases) and len({s['id'] for s in scenarios})==len(scenarios)
    costs=profile['p95_end_to_end_seconds'];workload_factor=max(1,data['max_new_mix_tasks']/192)**2
    upper_sum=sum(profile['p95_reference_seconds'] if j['kind']=='reference' else costs[j['factory_method']] for j in jobs)
    seconds=2*workload_factor*upper_sum+600
    budget={'selected_roots':n,'max_new_mix_tasks':data['max_new_mix_tasks'],'task_squared_factor':workload_factor,'nominal_cost_seconds_before_scaling':upper_sum,
            'conservative_estimated_seconds':seconds,'conservative_estimated_hours':seconds/3600,'gate_hours':12,'gate_passed':seconds<=12*3600,
            'scope':'planning estimate from synthetic end-to-end p95; not observed new benchmark runtime; aliases counted conservatively at physical cost'}
    dump(prep/'reports/budget_decision.json',budget)
    if not budget['gate_passed']:raise ValueError('v2 runtime budget gate failed; no freeze created')
    dump(target/'scenario_manifest.json',{'bases':bases,'scenarios':scenarios,'jobs':jobs})
    shutil.copy2(prep/'protocol_v2.md',target/'protocol_v2.md')
    data_manifest=json.loads((prep/'data/manifest_v2.json').read_text())
    for r in data_manifest['records']:
        for field in ('raw_path','parsed_path'):
            source=ROOT/r[field];new=('data/raw/' if field=='raw_path' else 'data/parsed/')+source.name
            (target/new).parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target/new);r['source_'+field]=r[field];r[field]=new
    dump(target/'data_manifest.json',data_manifest)
    for name,source in {'development_summary.json':prep/'development/summary.json','test_summary.json':prep/'reports/test_summary.json',
                        'runtime_profile.json':prep/'reports/runtime_profile.json','budget_decision.json':prep/'reports/budget_decision.json','execution_spec.json':prep/'spec.json'}.items():shutil.copy2(source,target/name)
    code=set((ROOT/'sail').glob('*.py'))|set(prep.glob('*.py'))|{ROOT/'research_v2/policies.py',ROOT/'research_v2/order_control.py',prep/'protocol_v2.md',
         prep/'spec.json',prep/'profile_design.json',prep/'data/manifest_v2.json',prep/'data/selection_before_outcomes.json',ROOT/'scripts/validate_p0_data.py',
         ROOT/'data/schema/wfcommons-schema.json',ROOT/'requirements-p3.txt',prep/'development/summary.json',prep/'reports/test_summary.json',
         prep/'reports/runtime_profile.json',prep/'reports/budget_decision.json'}
    # Gate/report writers can evolve outside the sealed algorithm and run/analysis entry points.
    code={p for p in code if p.name not in ('write_stage_report.py','check_stage.py','make_delivery_manifest.py')}
    aliases=sum('execution_alias_of' in j for j in jobs)
    cfg={'status':'FROZEN_G2_V2','purpose':'CONFIRMATORY_V2','version':'g2_v2_20261025','created_at':datetime.now(timezone.utc).isoformat(),
         'root_seeds':list(range(81000,81000+n)),'methods':list(METHODS),'primary_comparators':['PoolMinAWCT10','BudgetHEFT10'],
         'primary_budget_theta':.1,'bootstrap_repetitions':5000,'bootstrap_seed':83000,'nominal_jobs':len(jobs),'reference_jobs':len(bases),
         'failure_scenarios':len(scenarios),'mathematical_alias_records':aliases,'expected_physical_executions':len(jobs)-aliases,
         'new_topology_groups':6,'new_test_scheduling_runs_before_freeze':0,'formal_runs_completed':0,'original_v1_G3':'NOT_SUPPORTED',
         'protocol_sha256':sha(prep/'protocol_v2.md'),'source_data_manifest_sha256':sha(prep/'data/manifest_v2.json'),
         'budget_decision':budget,'code_files':[{'path':str(p.relative_to(ROOT)),'sha256':sha(p)} for p in sorted(code)]}
    dump(target/'freeze.json',cfg)
    paths=sorted(p for p in target.rglob('*') if p.is_file() and p.name!='inputs_manifest.json')
    dump(target/'inputs_manifest.json',{'files':[{'path':str(p.relative_to(target)),'sha256':sha(p)} for p in paths]})
    verify_v2(ROOT,target);return cfg


if __name__=='__main__':
    r=main();print(json.dumps({k:r[k] for k in ('status','nominal_jobs','reference_jobs','failure_scenarios','mathematical_alias_records','expected_physical_executions','formal_runs_completed')}))
