"""Independent v2 freeze verifier and checkpointed runner; no execution on import."""
import hashlib
import json
from functools import lru_cache
from pathlib import Path
from time import perf_counter

from sail.audit import audit_result
from sail.development import dump
from sail.experiment import workload_from_json
from sail.frozen import result_from_json,verify_freeze
from sail.metrics import paired_metrics
from sail.model import Failure,Platform
from sail.scheduling import initial_heft
from sail.simulator import Simulator,content_hash
from v2_preparation.experiment import make_method
from v2_preparation.metrics import queue_disturbance


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_v2(workspace,freeze):
    workspace=Path(workspace);freeze=Path(freeze);verify_freeze(workspace,workspace/'freeze/g2_v1_20261025')
    cfg=json.loads((freeze/'freeze.json').read_text())
    if cfg['status']!='FROZEN_G2_V2':raise ValueError('v2 not frozen')
    for e in json.loads((freeze/'inputs_manifest.json').read_text())['files']:
        if sha(freeze/e['path'])!=e['sha256']:raise ValueError('v2 input checksum mismatch: '+e['path'])
    for e in cfg['code_files']:
        if sha(workspace/e['path'])!=e['sha256']:raise ValueError('v2 code checksum mismatch: '+e['path'])
    return cfg,json.loads((freeze/'scenario_manifest.json').read_text())


class ApplicationTimer(Simulator):
    def _apply(self):
        t=perf_counter();super()._apply();self.full_application_seconds=perf_counter()-t


def execute_v2(workspace,freeze,output,job_limit=None):
    workspace=Path(workspace);freeze=Path(freeze);output=Path(output);cfg,mf=verify_v2(workspace,freeze)
    output.mkdir(parents=True,exist_ok=True);freeze_id=sha(freeze/'inputs_manifest.json');marker=output/'RUN_MANIFEST.json'
    if marker.exists():
        if json.loads(marker.read_text())['freeze_id']!=freeze_id:raise ValueError('output belongs to another freeze')
    else:dump(marker,{'freeze_id':freeze_id,'purpose':cfg['purpose'],'nominal_jobs':len(mf['jobs'])})
    records={};journal=output/'metrics.jsonl'
    if journal.exists():
        for line in journal.read_text().splitlines():
            row=json.loads(line)
            if row['job_id'] in records or row['status'] not in ('COMPLETE','ALIAS'):raise ValueError('invalid checkpoint')
            if sha(output/row['event_file'])!=row['event_sha256']:raise ValueError('checkpoint event checksum mismatch')
            records[row['job_id']]=row
    bases={b['id']:b for b in mf['bases']};scenarios={s['id']:s for s in mf['scenarios']}
    @lru_cache(maxsize=8)
    def inputs(bid):
        b=bases[bid];w=workload_from_json(json.loads((freeze/b['workload_file']).read_text()));p=Platform(tuple(b['speeds']),b['bandwidth'])
        truth=json.loads((freeze/b['truth_file']).read_text());return w,p,truth,initial_heft(w,p)
    def load(jid):return result_from_json(json.loads((output/records[jid]['event_file']).read_text()))
    executed=0
    with journal.open('a') as log:
        for job in mf['jobs']:
            jid=job['id']
            if jid in records:continue
            if job_limit is not None and executed>=job_limit:break
            try:
                bid=job['base_id']
                if job['kind']=='reference':
                    w,p,truth,initial=inputs(bid);run=Simulator(w,p,initial.plan,realized_work=truth).run();a=audit_result(run,w,p,realized_work=truth)
                    path='events/'+jid+'.json';dump(output/path,run)
                    row={'job_id':jid,'kind':'reference','base_id':bid,'status':'COMPLETE','makespan':run.makespan,'event_file':path,'event_sha256':sha(output/path),'events_checked':a['events_checked']}
                else:
                    s=scenarios[job['scenario_id']];method=job['method'];source=job.get('execution_alias_of')
                    identity={'job_id':jid,'kind':'failure','base_id':bid,'scenario_id':s['id'],'method':method,
                              **{k:s[k] for k in ('root_seed','mix','nodes','ccr','failure_fraction','variant')},'budget_theta':job.get('budget_theta',.1)}
                    if source:
                        if source not in records:raise ValueError('alias source not yet complete')
                        row={**records[source],**identity,'status':'ALIAS','execution_alias_of':source,'full_application_seconds':None}
                    else:
                        w,p,truth,initial=inputs(bid);ref=load('ref-'+bid)
                        fault=Failure(ref.makespan*s['failure_fraction'],s['failed_node'],s['control_delay_pbar_units']*w.pbar)
                        policy=make_method(job.get('factory_method',method),initial,job.get('budget_theta',.1))
                        engine=ApplicationTimer(w,p,initial.plan,realized_work=truth,failure=fault,repair=policy);run=engine.run()
                        a=audit_result(run,w,p,realized_work=truth,expected_failure=fault,reference=ref)
                        b0id=job.get('reference_b0_job');b0=load(b0id) if b0id in records else None
                        if b0 is not None and b0.context!=run.context:raise ValueError('v2 baseline contexts differ')
                        values=paired_metrics(run,ref,w,same_fault_b0=b0)
                        path='events/'+jid+'.json';dump(output/path,run)
                        row={**identity,'status':'COMPLETE','execution_alias_of':None,**values,**queue_disturbance(run.context,run.applied_plan),
                             'quality_feasible':getattr(policy,'last_quality_feasible',None),'selected_candidate':getattr(policy,'last_selected',None)['name'] if getattr(policy,'last_selected',None) else None,
                             'full_application_seconds':engine.full_application_seconds,'events_checked':a['events_checked'],
                             'context_sha256':content_hash(run.context),'event_file':path,'event_sha256':sha(output/path)}
                log.write(json.dumps(row,allow_nan=False)+'\n');log.flush();records[jid]=row;executed+=1
            except Exception as exc:
                dump(output/f'failures/{jid}.json',{'job':job,'error':repr(exc),'status':'FAILED'});raise
            if executed%25==0:print(f'v2 frozen labels {len(records)}/{len(mf["jobs"])}',flush=True)
    summary={'purpose':cfg['purpose'],'freeze_id':freeze_id,'nominal_jobs':len(mf['jobs']),'completed_labels':len(records),
             'physical_executions':sum(r['status']=='COMPLETE' for r in records.values()),'alias_records':sum(r['status']=='ALIAS' for r in records.values()),
             'all_complete':len(records)==len(mf['jobs'])}
    dump(output/'execution_summary.json',summary);return summary
