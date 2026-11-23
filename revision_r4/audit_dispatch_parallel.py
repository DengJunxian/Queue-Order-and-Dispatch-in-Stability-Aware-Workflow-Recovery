"""Finish the persisted dispatch audit after a verified serial prefix, in two workers."""
import hashlib
import json
import math
import sys
from concurrent.futures import ProcessPoolExecutor
from functools import lru_cache
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from revision_r4.common import OUT,Evidence,read_rows,read_doc,sha,dump,extra_metrics,check_protocol
from revision_r2.audit_dispatch import audit_result as audit_skip
from sail.audit import audit_result
from sail.frozen import result_from_json
from sail.metrics import paired_metrics

EV=INDEX=None


def initialize():
    global EV,INDEX
    EV=Evidence();rows=read_rows(OUT/'exploratory/dispatch/metrics.jsonl');INDEX={r['job_id']:r for r in rows}


@lru_cache(maxsize=16)
def reference(jid):
    r=INDEX[jid];p=ROOT/r['event_file'];assert sha(p)==r['event_sha256']
    return result_from_json(read_doc(p))


def one(r):
    path=ROOT/r['event_file'];assert sha(path)==r['event_sha256']
    w,p,truth=EV.inputs(r['base_id']);run=result_from_json(read_doc(path));ref=None
    failure=EV.failure(EV.main[r['base_id'],r['failure_fraction']])
    if r['method']!='reference':ref=reference(f'r4-dispatch-{r["scenario_id"]}-{r["rule"]}-reference')
    expected_failure=failure if r['method']!='reference' else None
    auditor=audit_skip if r['rule']=='skip-unready' else audit_result
    args={'dispatch_switch_time':failure.time} if r['rule']=='skip-unready' else {}
    receipt=auditor(run,w,p,realized_work=truth,expected_failure=expected_failure,reference=ref,**args)
    assert receipt['events_checked']==r['events_checked']
    checks=budget=0;largest=0.
    assert run.awct==r['awct'] and run.makespan==r['makespan']
    if r['method']!='reference':
        values={**paired_metrics(run,ref,w),**extra_metrics(run,ref,w)}
        for key in ('awct','makespan','churn','cdi','protected_late_fraction','protected_signed','protected_absolute','protected_p95_positive'):
            if values[key] is None:assert r[key] is None
            else:largest=max(largest,abs(values[key]-r[key]));assert abs(values[key]-r[key])<1e-10
            checks+=1
        assert values['workflow_completion']==r['workflow_completion']
        moves=sum(run.applied_plan.assignment[v]!=dict(run.context.old_assignment)[v] for v in run.context.Q-run.context.F)
        assert moves==r['optional_moves']<=r['budget_cap']==math.floor(.1*max(1,len(run.context.Q)));budget=1
    return receipt['events_checked'],checks,budget,largest


def main():
    check_protocol();reg=read_doc(OUT/'reports/execution_registration.json')
    for p,digest in reg['files'].items():assert sha(ROOT/p)==digest
    assert sha(OUT/'run_shard.py')==read_doc(OUT/'reports/shard_registration.json')['wrapper_sha256']
    journal=OUT/'exploratory/dispatch/metrics.jsonl';raw=journal.read_bytes();lines=raw.splitlines(keepends=True);rows=[json.loads(s) for s in lines]
    assert len(rows)==23040
    cp=read_doc(OUT/'reports/event_audit_dispatch_checkpoint.json');n=cp['records_checked']
    assert hashlib.sha256(b''.join(lines[:n])).hexdigest()==cp['prefix_sha256']
    events,checks,budgets,new=(cp[k] for k in ('event_records_checked','metric_checks','integer_budget_checks','new_executions'))
    prefix_report=read_doc(OUT/'reports/partial_event_audit.json')
    assert prefix_report['parts']['dispatch']['event_records_checked']==cp['event_records_checked']
    pending=[r for r in rows[n:] if r['new_execution']];largest=prefix_report['max_metric_abs_difference']
    # The prefix was already opened and independently audited. Check remaining
    # reused source bytes while workers replay the new serialized event traces.
    with ProcessPoolExecutor(max_workers=2,initializer=initialize) as pool:
        answers=pool.map(one,pending,chunksize=8)
        for r in rows[n:]:
            if not r['new_execution']:assert sha(ROOT/r['event_file'])==r['event_sha256']
        for ne,nc,nb,diff in answers:
            events+=ne;checks+=nc;budgets+=nb;new+=1;largest=max(largest,diff)
            if new%240==0:print('R4 independent persisted dispatch replay',new,'/11280',flush=True)
    assert new==sum(r['new_execution'] for r in rows)==11280
    assert events==sum(r['events_checked'] for r in rows) and budgets==10080 and checks==80640
    receipt={'new_executions':new,'reused_source_records_verified':sum(not r['new_execution'] for r in rows),
        'unique_source_files':len({r['event_file'] for r in rows}),'event_records_checked':events,'metric_checks':checks,
        'integer_budget_checks':budgets,'journal_sha256':sha(journal),'max_metric_abs_difference':largest,
        'serial_prefix_records_reused':n,'parallel_workers':2,'parallel_auditor_sha256':sha(Path(__file__))}
    assert largest==0
    dump(OUT/'reports/event_audit_dispatch.json',receipt);print('Dispatch persisted audit PASS')


if __name__=='__main__':main()
