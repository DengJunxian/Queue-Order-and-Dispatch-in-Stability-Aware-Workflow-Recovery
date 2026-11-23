"""Review-driven executions with resumable journals and immutable source aliases."""
import argparse
import json
import math
import sys
from functools import lru_cache
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from revision_r4.common import (OUT, METHODS, Evidence, sha, dump, BS, PM, AL, Q0, read_rows,
    read_doc, save_doc, extra_metrics, fixed_guard_document, policy, error_work, check_protocol)
from revision_r2.common import FixedDecision
from revision_r2.dispatch import SkipUnready
from revision_r2.audit_dispatch import audit_result as audit_skip
from sail.audit import audit_result
from sail.frozen import result_from_json
from sail.metrics import paired_metrics
from sail.model import Failure
from sail.scheduling import initial_heft
from sail.simulator import Simulator, content_hash


def main(part, limit=None):
    protocol_sha = check_protocol(); ev = Evidence()
    folder = OUT / 'exploratory' / part; folder.mkdir(parents=True, exist_ok=True)
    journal = folder / 'metrics.jsonl'
    rows = {r['job_id']: r for r in read_rows(journal)}
    assert len(rows) == len(read_rows(journal))
    for r in rows.values(): assert sha(ROOT / r['event_file']) == r['event_sha256']
    fresh = 0
    pools = {r['scenario_id']: r for r in read_rows(ROOT / 'revision_r2/analysis/pool_cases.jsonl')}
    r2skip = {r['job_id']: r for r in read_rows(ROOT / 'revision_r2/exploratory/dispatch/metrics.jsonl')}
    cases = [c for c in ev.cases if c['variant'] == 'main'] if part == 'dispatch' else (
        [c for c in ev.cases if c['variant'] in ('cv0.1', 'cv0.3')] if part == 'error' else
        [c for c in ev.cases if c['variant'] == 'main' and c['root_seed'] < 81010 and c['nodes'] == 4 and c['failure_fraction'] == .6])
    expected = 1440 * 16 if part == 'dispatch' else 2 * 120 * 8 if part == 'error' else 60 * 2 * 4

    @lru_cache(maxsize=8)
    def initial(bid):
        w, p, _ = ev.inputs(bid); x = initial_heft(w, p)
        assert x.plan == ev.initial_plan(bid)
        return x

    def record(case, method, rule, run, reference, failure, *, source=None, audited=None, extra=None):
        nonlocal fresh
        suffix = rule; jid = f'r4-{part}-{case["scenario_id"]}-{suffix}-{method}'
        if source is None:
            path = folder / 'events' / (jid + '.json.gz'); save_doc(path, run)
        else: path = ROOT / source
        r = {k: case[k] for k in ('scenario_id', 'base_id', 'root_seed', 'mix', 'nodes', 'ccr', 'failure_fraction', 'variant')}
        if method == 'reference': values = {'awct': run.awct, 'makespan': run.makespan}
        else:
            values = {**paired_metrics(run, reference, w), **extra_metrics(run, reference, w)}
            values['context_sha256'] = content_hash(run.context)
            values['plan_sha256'] = content_hash(run.applied_plan.queues)
            moves = sum(run.applied_plan.assignment[v] != dict(run.context.old_assignment)[v] for v in run.context.Q - run.context.F)
            assert moves <= math.floor(.1 * max(1, len(run.context.Q)))
            values.update({'optional_moves': moves, 'budget_cap': math.floor(.1 * max(1, len(run.context.Q)))})
        r.update(values); r.update(extra or {})
        r.update({'job_id': jid, 'method': method, 'rule': rule, 'kind': 'reference' if method == 'reference' else 'failure',
                  'new_execution': source is None, 'event_file': str(path.relative_to(ROOT)), 'event_sha256': sha(path),
                  'events_checked': audited['events_checked'] if audited else 0,
                  'purpose': 'EXPLORATORY_NOT_CONFIRMATORY', 'protocol_sha256': protocol_sha, 'status': 'COMPLETE'})
        stream.write(json.dumps(r, allow_nan=False) + '\n'); stream.flush(); rows[jid] = r; fresh += 1
        if len(rows) % 120 == 0:
            print(f'R4 {part} {len(rows)}/{expected}', flush=True)
            dump(folder / 'progress.json', {'completed': len(rows), 'expected': expected})
        return r

    with journal.open('a') as stream:
        for case0 in cases:
            w, p, original_truth = ev.inputs(case0['base_id'])
            base_plan = ev.initial_plan(case0['base_id'])
            if part == 'dispatch':
                case = case0; sid = case['scenario_id']; failure = ev.failure(case)
                guard = pools[sid]['guard']; documents = {}
                for method in METHODS:
                    if method == 'WorkflowGuard': documents[method] = fixed_guard_document(ev, case, guard)
                    elif method == 'ProtectedFirst':
                        r = ev.priority[sid]; path = ROOT / 'revision_r1/exploratory/priority' / r['event_file']
                        assert sha(path) == r['event_sha256']; documents[method] = read_doc(path)
                    else: documents[method] = ev.doc(f'run-{sid}-{method}')
                for rule in ('strict', 'skip-unready'):
                    ref_jid = f'r4-dispatch-{sid}-{rule}-reference'
                    if ref_jid in rows: ref = result_from_json(read_doc(ROOT / rows[ref_jid]['event_file']))
                    elif rule == 'strict':
                        rr = ev.raw['ref-' + case['base_id']]; ref = ev.result('ref-' + case['base_id'])
                        record(case, 'reference', rule, ref, None, failure, source='results/g2_v2_20261025/' + rr['event_file'])
                    else:
                        oldid = f'r2-dispatch-{sid}-reference'
                        if oldid in r2skip:
                            rr = r2skip[oldid]; path = ROOT / 'revision_r2/exploratory/dispatch' / rr['event_file']
                            assert sha(path) == rr['event_sha256']; ref = result_from_json(read_doc(path))
                            record(case, 'reference', rule, ref, None, failure, source=str(path.relative_to(ROOT)))
                        else:
                            ref = SkipUnready(w, p, base_plan, realized_work=original_truth, switch_time=failure.time).run()
                            a = audit_skip(ref, w, p, realized_work=original_truth, dispatch_switch_time=failure.time)
                            record(case, 'reference', rule, ref, None, failure, audited=a)
                    for method in METHODS:
                        jid = f'r4-dispatch-{sid}-{rule}-{method}'
                        if jid in rows: continue
                        if limit is not None and fresh >= limit: return
                        extras = {'draw': 0}
                        if method == 'WorkflowGuard': extras.update({'guard_feasible': guard['guard_feasible'], 'mean_quality_feasible': guard['mean_quality_feasible'], 'selected_candidate': guard['name']})
                        if rule == 'strict' and method != 'WorkflowGuard':
                            if method == 'ProtectedFirst': path = ROOT / 'revision_r1/exploratory/priority' / ev.priority[sid]['event_file']
                            else: path = ROOT / 'results/g2_v2_20261025' / ev.raw[f'run-{sid}-{method}']['event_file']
                            run = result_from_json(documents[method]); record(case, method, rule, run, ref, failure, source=str(path.relative_to(ROOT)), extra=extras)
                        elif rule == 'skip-unready' and f'r2-dispatch-{sid}-{method}' in r2skip:
                            rr = r2skip[f'r2-dispatch-{sid}-{method}']; path = ROOT / 'revision_r2/exploratory/dispatch' / rr['event_file']
                            assert sha(path) == rr['event_sha256']; run = result_from_json(read_doc(path))
                            record(case, method, rule, run, ref, failure, source=str(path.relative_to(ROOT)), extra=extras)
                        else:
                            kw = {'switch_time': failure.time} if rule == 'skip-unready' else {}
                            cls = SkipUnready if rule == 'skip-unready' else Simulator
                            run = cls(w, p, base_plan, realized_work=original_truth, failure=failure, repair=FixedDecision(documents[method]), **kw).run()
                            assert sorted(run.context.F) == documents[method]['context']['F']
                            expected_plan = next(e for e in documents[method]['events'] if e['kind'] == 'PLAN_APPLIED')['details']['queues']
                            assert json.loads(json.dumps(run.applied_plan.queues)) == json.loads(json.dumps(expected_plan))
                            auditor = audit_skip if rule == 'skip-unready' else audit_result
                            a = auditor(run, w, p, realized_work=original_truth, expected_failure=failure, reference=ref,
                                        **({'dispatch_switch_time': failure.time} if rule == 'skip-unready' else {}))
                            record(case, method, rule, run, ref, failure, audited=a, extra=extras)
            elif part == 'error':
                for draw in (1, 2):
                    case = {**case0, 'scenario_id': case0['scenario_id'] + f'-draw{draw}'}; sid = case['scenario_id']
                    truth = error_work(w, case['root_seed'], case['mix'], draw, float(case['variant'][2:]))
                    truth_path = folder / 'truth' / f'draw{draw}-{case["root_seed"]}-{case["mix"]}-{case["variant"]}.json'
                    if not truth_path.exists(): dump(truth_path, truth)
                    assert read_doc(truth_path) == truth
                    refid = f'r4-error-{sid}-strict-reference'
                    if refid in rows: ref = result_from_json(read_doc(ROOT / rows[refid]['event_file']))
                    else:
                        ref = Simulator(w, p, base_plan, realized_work=truth).run(); a = audit_result(ref, w, p, realized_work=truth)
                        record(case, 'reference', 'strict', ref, None, None, audited=a, extra={'draw': draw, 'truth_file': str(truth_path.relative_to(ROOT))})
                    failure = Failure(ref.makespan * .6, ev.scenarios[case0['scenario_id']]['failed_node'])
                    for method in METHODS:
                        jid = f'r4-error-{sid}-strict-{method}'
                        if jid in rows: continue
                        if limit is not None and fresh >= limit: return
                        pi = policy(method, initial(case['base_id'])); t = perf_counter()
                        run = Simulator(w, p, base_plan, realized_work=truth, failure=failure, repair=pi).run(); elapsed = perf_counter() - t
                        a = audit_result(run, w, p, realized_work=truth, expected_failure=failure, reference=ref)
                        extras = {'draw': draw, 'truth_file': str(truth_path.relative_to(ROOT)), 'failure_time': failure.time, 'failed_node': failure.node,
                                  'complete_simulation_wall_seconds': elapsed}
                        if hasattr(pi, 'last_selected') and pi.last_selected:
                            extras.update({'selected_candidate': pi.last_selected['name'], 'predicted_cdi': pi.last_selected['cdi'], 'predicted_awct': pi.last_selected['awct'], 'mean_quality_feasible': pi.last_quality_feasible})
                        if method == 'WorkflowGuard': extras.update({'guard_feasible': pi.guard_feasible, 'predicted_pool_workflow_reference': pi.workflow_reference})
                        record(case, method, 'strict', run, ref, failure, audited=a, extra=extras)
            else:
                ref = ev.result('ref-' + case0['base_id']); original = ev.failure(case0)
                for delay in (.1, 1.):
                    case = {**case0, 'scenario_id': case0['scenario_id'] + f'-delay{delay:g}'}
                    failure = Failure(original.time, original.node, delay * w.pbar)
                    for method in (AL, BS, 'WorkflowGuard', 'ProtectedFirst'):
                        jid = f'r4-latency-{case["scenario_id"]}-strict-{method}'
                        if jid in rows: continue
                        if limit is not None and fresh >= limit: return
                        pi = policy(method, initial(case0['base_id']))
                        run = Simulator(w, p, base_plan, realized_work=original_truth, failure=failure, repair=pi).run()
                        a = audit_result(run, w, p, realized_work=original_truth, expected_failure=failure, reference=ref)
                        record(case, method, 'strict', run, ref, failure, audited=a, extra={'delay_pbar': delay, 'original_scenario_id': case0['scenario_id']})
    dump(folder / 'summary.json', {'status': 'PASS' if len(rows) == expected else 'PARTIAL', 'records': len(rows), 'expected': expected,
        'new_executions': sum(r['new_execution'] for r in rows.values()), 'reused_records': sum(not r['new_execution'] for r in rows.values()),
        'events_checked_new': sum(r['events_checked'] for r in rows.values()), 'violations': 0,
        'journal_sha256': sha(journal), 'new_confirmatory_samples': 0, 'protocol_sha256': protocol_sha})
    print(f'R4 {part} complete: {len(rows)} records', flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--part', choices=('dispatch', 'error', 'latency'), required=True); p.add_argument('--limit', type=int)
    a = p.parse_args(); main(a.part, a.limit)
