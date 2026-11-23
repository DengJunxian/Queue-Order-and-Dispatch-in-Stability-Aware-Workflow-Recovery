"""Reload every new persisted event log, audit execution and recompute metrics."""
import hashlib
import json
import math
import sys
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from formal_v2.audit_outputs import independent_order
from sail.audit import audit_result
from sail.data import random_stream
from sail.development import dump
from sail.experiment import workload_from_json
from sail.frozen import result_from_json
from sail.model import Failure
from revision_r1.run_exploratory import generalized_platform
from v2_preparation.frozen import verify_v2


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main(part_only=None):
    verify_v2(ROOT, ROOT / 'freeze/g2_v2_20261025')
    old = {r['job_id']: r for r in (json.loads(s) for s in (ROOT / 'results/g2_v2_20261025/metrics.jsonl').read_text().splitlines())}
    receipts = {}
    @lru_cache(maxsize=12)
    def original(jid):
        r = old[jid]
        p = ROOT / 'results/g2_v2_20261025' / r['event_file']
        assert sha(p) == r['event_sha256']
        return result_from_json(json.loads(p.read_text()))
    @lru_cache(maxsize=10)
    def inputs(seed, mix, nodes, ccr, cv):
        w = workload_from_json(json.loads((ROOT / f'freeze/g2_v2_20261025/public/workloads/{seed}-{mix}.json').read_text()))
        p = generalized_platform(seed, mix, nodes, w, ccr)
        truth = json.loads((ROOT / f'freeze/g2_v2_20261025/evaluator/{seed}-{mix}-cv{cv:g}.json').read_text())
        return w, p, truth
    for part in ((part_only,) if part_only else ('priority', 'scale')):
        folder = ROOT / 'revision_r1/exploratory' / part
        assert json.loads((folder / 'summary.json').read_text())['status'] == 'PASS'
        rows = [json.loads(s) for s in (folder / 'metrics.jsonl').read_text().splitlines()]
        indexed = {r['job_id']: r for r in rows}
        @lru_cache(maxsize=12)
        def saved(jid):
            r = indexed[jid]
            p = folder / r['event_file']
            assert sha(p) == r['event_sha256']
            return result_from_json(json.loads(p.read_text()))
        events = budgets = fixed = metrics = 0
        contexts = defaultdict(set)
        for i, r in enumerate(rows):
            cv = r['cv'] if 'cv' in r else (0 if r['variant'] in ('main', 'control_delay') else float(r['variant'][2:]))
            w, p, truth = inputs(r['root_seed'], r['mix'], r['nodes'], r['ccr'], cv)
            run = saved(r['job_id'])
            if r['kind'] == 'reference':
                audited = audit_result(run, w, p, realized_work=truth)
            else:
                if part == 'priority':
                    ref = original(r['reference_job']); b0 = original(r['original_b0_job'])
                    failed, delay = r['failed_node'], r['control_delay_pbar_units'] * w.pbar
                else:
                    ref = saved('ref-' + r['base_id']); b0 = saved(r['scenario_id'] + '-B0')
                    failed, delay = int(random_stream(r['root_seed'], r['mix'], 'failure', 'node').integers(0, r['nodes'])), 0
                fault = Failure(ref.makespan * r['failure_fraction'], failed, delay)
                audited = audit_result(run, w, p, realized_work=truth, expected_failure=fault, reference=ref)
                assert run.context == b0.context
                contexts[r['scenario_id']].add(r['context_sha256'])
                for field, value in independent_order(run.context, run.applied_plan).items():
                    actual = r[field]
                    assert actual is None if value is None else math.isclose(actual, value, abs_tol=1e-9), (part, r['job_id'], field)
                old_assignment = dict(run.context.old_assignment)
                moves = sum(run.applied_plan.assignment[v] != old_assignment[v] for v in run.context.Q - run.context.F)
                assert math.isclose(r['churn'], moves / max(1, len(run.context.Q)), abs_tol=1e-12)
                if r['method'] != 'B2':
                    assert moves <= math.floor(.1 * max(1, len(run.context.Q))); budgets += 1
                if r['method'] == 'ProtectedFirst':
                    assert moves == 0 and run.applied_plan.assignment == b0.applied_plan.assignment
                    fixed += 1
                for metric in ('cdi', 'churn'):
                    a, b = audited[metric], r[metric]
                    assert a is None if b is None else math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9), (r['job_id'], metric)
                    metrics += 1
            assert math.isclose(audited['awct'], r['awct'], rel_tol=1e-9, abs_tol=1e-9)
            events += audited['events_checked']; metrics += 1
            if (i + 1) % 180 == 0:
                print(f'R1 persisted audit {part} {i+1}/{len(rows)}', flush=True)
        assert all(len(s) == 1 for s in contexts.values())
        receipts[part] = {'physical_executions': len(rows), 'events_checked': events, 'budget_checks': budgets,
                          'protectedfirst_fixed_assignment_checks': fixed, 'metric_checks': metrics, 'scenario_contexts': len(contexts),
                          'journal_sha256': sha(folder / 'metrics.jsonl'), 'violations': 0}
        dump(ROOT / f'revision_r1/reports/audit_{part}.json', receipts[part])
    if part_only:
        for part in ('priority', 'scale'):
            receipt = ROOT / f'revision_r1/reports/audit_{part}.json'
            if receipt.exists():
                value = json.loads(receipt.read_text())
                assert value['journal_sha256'] == sha(ROOT / f'revision_r1/exploratory/{part}/metrics.jsonl')
                receipts[part] = value
        if len(receipts) != 2:
            print(json.dumps({'status': 'PARTIAL', 'audited_parts': list(receipts)}))
            return
    summary = {'status': 'PASS', 'parts': receipts, 'physical_executions': sum(r['physical_executions'] for r in receipts.values()),
               'events_checked': sum(r['events_checked'] for r in receipts.values()), 'budget_checks': sum(r['budget_checks'] for r in receipts.values()),
               'new_confirmatory_samples': 0, 'violations': 0,
               'method': 'Persisted-log constraint audit and separate Fenwick queue metric; does not re-execute selection or provide an optimality proof.'}
    assert summary['physical_executions'] == 4740 and summary['budget_checks'] == 4140
    dump(ROOT / 'revision_r1/reports/exploratory_audit.json', summary)
    print(json.dumps(summary))


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser(); p.add_argument('--part', choices=('priority', 'scale'))
    main(p.parse_args().part)
