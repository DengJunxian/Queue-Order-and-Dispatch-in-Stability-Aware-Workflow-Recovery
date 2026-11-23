"""Fresh replay of all R2 persisted event documents, separate from their runner."""
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from revision_r2.common import Evidence, sha, dump
from revision_r2.audit_dispatch import audit_result as audit_dispatch
from sail.audit import audit_result
from sail.frozen import result_from_json
from sail.metrics import paired_metrics
from v2_preparation.frozen import verify_v2


def main():
    verify_v2(ROOT, ROOT / 'freeze/g2_v2_20261025')
    ev = Evidence(); events = checks = budget_checks = 0
    parts = {}; maximum_metric_difference = 0.
    for part in ('dispatch','Q0_error','guard_error','offline_validation'):
        folder = ROOT / 'revision_r2/exploratory' / part
        rows = [json.loads(s) for s in (folder/'metrics.jsonl').read_text().splitlines()]
        assert len({r['job_id'] for r in rows}) == len(rows)
        index = {r['job_id']:r for r in rows}
        for row in rows:
            path = folder / row['event_file']; assert sha(path) == row['event_sha256']
            run = result_from_json(json.loads(path.read_text()))
            w,p,truth = ev.inputs(row['base_id']); fail = ev.failure(row)
            if row['kind'] == 'reference':
                outcome = audit_dispatch(run,w,p,realized_work=truth,dispatch_switch_time=fail.time)
            else:
                if part == 'dispatch':
                    rr = index[f"r2-dispatch-{row['scenario_id']}-reference"]
                    ref = result_from_json(json.loads((folder/rr['event_file']).read_text()))
                    outcome = audit_dispatch(run,w,p,realized_work=truth,expected_failure=fail,
                                             reference=ref,dispatch_switch_time=fail.time)
                else:
                    ref = ev.result('ref-'+row['base_id'])
                    outcome = audit_result(run,w,p,realized_work=truth,expected_failure=fail,reference=ref)
                assert run.context == ev.result(f"run-{row['scenario_id']}-B0").context
                metrics = paired_metrics(run,ref,w)
                for k in ('cdi','awct','churn','makespan'):
                    assert (row[k] is None) == (metrics[k] is None)
                    if row[k] is not None:
                        error = abs(row[k] - metrics[k]); maximum_metric_difference = max(error,maximum_metric_difference)
                        assert error < 1e-10
                        checks += 1
                theta = row.get('theta',.1)
                original_assignment = ev.initial_plan(row['base_id']).assignment
                optional_moves = sum(run.applied_plan.assignment[v] != original_assignment[v] for v in run.context.Q-run.context.F)
                assert optional_moves <= math.floor(theta*max(1,len(run.context.Q)))
                budget_checks += 1
            events += outcome['events_checked']
        parts[part] = {'executions':len(rows),'journal_sha256':sha(folder/'metrics.jsonl')}
        print(f'Persisted independent audit {part}: {len(rows)}',flush=True)
    assert sum(x['executions'] for x in parts.values()) == 1940
    dump(ROOT/'revision_r2/reports/persisted_event_audit.json',{'status':'PASS','parts':parts,
         'event_records_checked':events,'metric_checks':checks,'max_metric_abs_difference':maximum_metric_difference,
         'integer_optional_budget_checks':budget_checks,'violations':0,'original_freeze_verified':True,
         'scope':'Independent constraint replay of persisted event files; dispatch auditor extends the immutable strict auditor with verified first-ready promotions.'})


if __name__ == '__main__': main()
