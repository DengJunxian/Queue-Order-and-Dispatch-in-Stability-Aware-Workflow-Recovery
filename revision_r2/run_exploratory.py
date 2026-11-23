"""Separate added dispatch and error controls; original runs are read-only."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from revision_r2.common import Evidence, sha, dump, BS, PM, Q0, AL, FixedDecision
from revision_r2.dispatch import SkipUnready
from revision_r2.wait_accounting import wait_components
from revision_r2.audit_dispatch import audit_result as audit_dispatch
from sail.audit import audit_result
from sail.frozen import result_from_json
from sail.metrics import paired_metrics
from sail.simulator import Simulator, content_hash
from v2_preparation.experiment import make_method
from v2_preparation.frozen import verify_v2


def main(part, limit=None):
    verify_v2(ROOT, ROOT / 'freeze/g2_v2_20261025')
    ev = Evidence()
    folder = ROOT / 'revision_r2/exploratory' / part
    folder.mkdir(parents=True, exist_ok=True)
    journal = folder / 'metrics.jsonl'
    rows = {}
    if journal.exists():
        for line in journal.read_text().splitlines():
            r = json.loads(line); assert r['job_id'] not in rows
            assert sha(folder / r['event_file']) == r['event_sha256']
            rows[r['job_id']] = r
    if part == 'dispatch':
        selected = [c for c in ev.cases if c['variant'] == 'main' and c['root_seed'] < 81010]
        methods = ('B0', AL, Q0, BS, PM, 'ProtectedFirst')
        work = [(c, method) for c in selected for method in ('reference', *methods)]
    elif part == 'Q0_error':
        work = [(c, Q0) for c in ev.cases if c['variant'] in ('cv0.1', 'cv0.3')]
    else:
        chosen = {r['scenario_id']: r for r in (json.loads(s) for s in (ROOT / 'revision_r2/analysis/guard_choices.jsonl').read_text().splitlines())}
        work = [(c, 'WorkflowGuard') for c in ev.cases if c['variant'] in ('cv0.1', 'cv0.3')]
    dump(folder / 'PLAN.json', {'purpose': 'EXPLORATORY_NOT_CONFIRMATORY', 'cases': len(selected) if part == 'dispatch' else len(work),
                               'jobs': len(work), 'protocol_sha256': sha(ROOT / 'revision_r2/protocol.json')})
    fresh = 0
    with journal.open('a') as stream:
        for case, method in work:
            sid, bid = case['scenario_id'], case['base_id']
            jid = f'r2-{part}-{sid}-{method}'
            if jid in rows: continue
            if limit is not None and fresh >= limit: break
            w, p, truth = ev.inputs(bid)
            failure = ev.failure(case)
            initial = ev.initial_plan(bid)
            meta = {k: case[k] for k in ('scenario_id', 'base_id', 'root_seed', 'mix', 'nodes', 'ccr', 'failure_fraction', 'variant')}
            if part == 'dispatch':
                if method == 'reference':
                    run = SkipUnready(w, p, initial, realized_work=truth, switch_time=failure.time).run()
                    a = audit_dispatch(run, w, p, realized_work=truth, dispatch_switch_time=failure.time)
                    values = {'awct': run.awct, 'makespan': run.makespan}
                else:
                    reference_row = rows[f'r2-dispatch-{sid}-reference']
                    reference = result_from_json(json.loads((folder / reference_row['event_file']).read_text()))
                    if method == 'ProtectedFirst':
                        r = ev.priority[sid]; path = ROOT / 'revision_r1/exploratory/priority' / r['event_file']
                        assert sha(path) == r['event_sha256']; old = json.loads(path.read_text())
                    else: old = ev.doc(f'run-{sid}-{method}')
                    run = SkipUnready(w, p, initial, realized_work=truth, failure=failure,
                                      repair=FixedDecision(old), switch_time=failure.time).run()
                    assert run.context == result_from_json(old).context
                    assert run.applied_plan == result_from_json(old).applied_plan
                    a = audit_dispatch(run, w, p, realized_work=truth, expected_failure=failure,
                                       reference=reference, dispatch_switch_time=failure.time)
                    waits = wait_components({'events': run.events, 'starts': run.starts, 'finishes': run.finishes}, w, failure.time, run.context.Q)
                    assert max((v['HOL'] for v in waits.values()), default=0) < 1e-7
                    values = paired_metrics(run, reference, w)
                    values['max_ready_idle_after_switch'] = max((v['HOL'] for v in waits.values()), default=0)
            else:
                reference = ev.result('ref-' + bid)
                if part == 'Q0_error': policy = make_method(Q0, None)
                else:
                    from sail.model import Plan, RepairDecision
                    choice = chosen[sid]
                    policy = lambda snapshot, ctx: RepairDecision(ctx.Q, Plan(tuple(tuple(q) for q in choice['queues'])))
                run = Simulator(w, p, initial, realized_work=truth, failure=failure, repair=policy).run()
                a = audit_result(run, w, p, realized_work=truth, expected_failure=failure, reference=reference)
                values = paired_metrics(run, reference, w)
                assert run.context == ev.result(f'run-{sid}-B0').context
                if part == 'guard_error':
                    values.update({'guard_feasible': choice['guard_feasible'], 'mean_quality_feasible': choice['mean_quality_feasible'],
                                   'predicted_workflow_completion': choice['workflow_completion'], 'selected_candidate': choice['name']})
            if method != 'reference':
                assert run.churn <= .1 + 1e-12
                values.update({'workflow_completion': dict(run.workflow_finishes),
                               'reference_workflow_completion': dict(reference.workflow_finishes),
                               'context_sha256': content_hash(run.context), 'F_count': len(run.context.F), 'Q_count': len(run.context.Q)})
            path = 'events/' + jid + '.json'
            dump(folder / path, run)
            row = {**meta, **values, 'job_id': jid, 'method': method, 'kind': 'reference' if method == 'reference' else 'failure',
                   'status': 'COMPLETE', 'purpose': 'EXPLORATORY_NOT_CONFIRMATORY', 'event_file': path,
                   'event_sha256': sha(folder / path), 'events_checked': a['events_checked']}
            stream.write(json.dumps(row, allow_nan=False) + '\n'); stream.flush(); rows[jid] = row; fresh += 1
            if len(rows) % 60 == 0:
                dump(folder / 'progress.json', {'completed': len(rows), 'total': len(work)})
                print(f'R2 {part} {len(rows)}/{len(work)}', flush=True)
    dump(folder / 'summary.json', {'status': 'PASS' if len(rows) == len(work) else 'PARTIAL', 'executions': len(rows), 'planned': len(work),
                                  'new_confirmatory_samples': 0, 'events_checked': sum(r['events_checked'] for r in rows.values()),
                                  'violations': 0, 'journal_sha256': sha(journal)})


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--part', choices=('dispatch', 'Q0_error', 'guard_error'), required=True); p.add_argument('--limit', type=int)
    a = p.parse_args(); main(a.part, a.limit)
