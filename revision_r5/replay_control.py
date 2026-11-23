"""Replay PS from the compact ledger without any prior event archives."""
import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from revision_r5.run_control import read, sha, dump
from revision_r5.control import ProtectedSubsequence
from sail.experiment import workload_from_json
from sail.model import Plan, Platform, Failure
from sail.simulator import Simulator, content_hash
from sail.metrics import paired_metrics
from sail.audit import audit_result
from revision_r2.dispatch import SkipUnready
from revision_r2.audit_dispatch import audit_result as audit_skip


def main(cases, output):
    base = ROOT / 'revision_r5'
    registration = read(base / 'registration.json')
    ledger_path = ROOT / 'paper_v7/artifact/factorial_plans.json.gz'
    assert sha(ledger_path) == registration['sha256']['paper_v7/artifact/factorial_plans.json.gz']
    data = read(ledger_path)
    selected = data['cases'] if cases == 'all' else data['cases'][:1] if cases == 'first' else [c for c in data['cases'] if c['scenario_id'] == cases]
    assert selected, 'Unknown case selection'
    expected = {(r['scenario_id'], r['rule']): r for r in (json.loads(s) for s in (base / 'metrics.jsonl').read_text().splitlines())}
    output_rows = []
    events = executions = metric_checks = 0
    freeze = ROOT / 'freeze/g2_v2_20261025'
    for case in selected:
        b = data['bases'][case['base_id']]
        w = workload_from_json(read(freeze / b['workload_file']))
        p = Platform(tuple(b['speeds']), b['bandwidth'])
        truth = read(freeze / b['truth_file'])
        initial = Plan(tuple(tuple(q) for q in b['initial_queues']))
        fault = Failure(case['failure_time'], case['failed_node'])
        b0 = Plan(tuple(tuple(q) for q in case['plans']['B0']['queues']))
        for rule in ('strict', 'skip-unready'):
            cls = Simulator if rule == 'strict' else SkipUnready
            auditor = audit_result if rule == 'strict' else audit_skip
            kw = {} if rule == 'strict' else {'switch_time': fault.time}
            ak = {} if rule == 'strict' else {'dispatch_switch_time': fault.time}
            reference = cls(w, p, initial, realized_work=truth, **kw).run()
            events += auditor(reference, w, p, realized_work=truth, **ak)['events_checked']
            run = cls(w, p, initial, realized_work=truth, failure=fault, repair=ProtectedSubsequence(b0), **kw).run()
            events += auditor(run, w, p, realized_work=truth, expected_failure=fault, reference=reference, **ak)['events_checked']
            executions += 2
            want = expected[case['scenario_id'], rule]
            metrics = paired_metrics(run, reference, w)
            for key in ('cdi', 'awct', 'churn', 'makespan'):
                assert math.isclose(metrics[key], want[key], rel_tol=1e-11, abs_tol=1e-9), (case['scenario_id'], rule, key)
                metric_checks += 1
            for wf, completion in run.workflow_finishes:
                assert math.isclose(completion, want['workflow_completion'][wf], rel_tol=1e-11, abs_tol=1e-9)
                metric_checks += 1
            assert content_hash(run.applied_plan.queues) == want['plan_sha256']
            assert content_hash(run.context) == want['context_sha256']
            output_rows.append({'scenario_id': case['scenario_id'], 'rule': rule, 'cdi': metrics['cdi'], 'awct': metrics['awct'], 'churn': metrics['churn'], 'saved_result_matches': True})
    receipt = {'status': 'PASS', 'cases': len(selected), 'physical_validation_executions': executions,
               'independent_event_records': events, 'saved_metric_checks': metric_checks,
               'new_scientific_samples': 0, 'requires_previous_event_archives': False, 'records': output_rows}
    dump(Path(output), receipt)
    print(json.dumps({k: v for k, v in receipt.items() if k != 'records'}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--cases', default='first')
    parser.add_argument('--output', default='/private/tmp/cscwd-r5-replay.json')
    args = parser.parse_args()
    main(args.cases, args.output)
