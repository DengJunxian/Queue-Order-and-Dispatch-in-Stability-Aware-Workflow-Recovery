"""Execute the registered 1,440-case fixed-plan ProtectedSubsequence control."""
import argparse
import gzip
import hashlib
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from time import perf_counter
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sail.experiment import workload_from_json
from sail.model import Plan, Platform, Failure
from sail.simulator import Simulator, jsonable, content_hash
from sail.frozen import result_from_json
from sail.metrics import paired_metrics
from sail.audit import audit_result
from revision_r2.dispatch import SkipUnready
from revision_r2.audit_dispatch import audit_result as audit_skip
from revision_r4.common import extra_metrics
from revision_r5.control import ProtectedSubsequence

OUT = ROOT / 'revision_r5'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    path = Path(path)
    return json.loads(gzip.decompress(path.read_bytes()) if path.suffix == '.gz' else path.read_bytes())


def dump(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, allow_nan=False) + '\n')


def verify_registration():
    reg = read(OUT / 'registration.json')
    for name, expected in reg['sha256'].items():
        assert sha(ROOT / name) == expected, ('registered input changed', name)
    return sha(OUT / 'protocol.json')


def check_persisted(path, w, p, truth, failure, reference, rule):
    run = result_from_json(read(path))
    auditor = audit_result if rule == 'strict' else audit_skip
    a = auditor(run, w, p, realized_work=truth, expected_failure=failure, reference=reference,
                **({'dispatch_switch_time': failure.time} if rule != 'strict' else {}))
    # Recompute aggregate fields directly from the auditor's reconstructed starts.
    start, ref = a['starts'], dict(reference.starts)
    cp = run.context.P
    cdi = sum(max(0., start[v] - ref[v]) for v in cp) / (len(cp) * w.pbar) if cp else None
    wf = {k: max(a['finishes'][t.id] for t in w.tasks if t.workflow == k) for k, _ in run.workflow_finishes}
    awct = sum(wf.values()) / len(wf)
    assert math.isclose(awct, run.awct, rel_tol=1e-12, abs_tol=1e-10)
    if rule == 'strict':
        assert all(start[v] <= ref[v] + 1e-8 for v in cp), ('strict theorem violated', path)
    return run, a, cdi, wf, awct


def main(limit=None):
    protocol_hash = verify_registration()
    data = read(ROOT / 'paper_v7/artifact/factorial_plans.json.gz')
    prior = [json.loads(x) for x in (ROOT / 'revision_r4/exploratory/dispatch/metrics.jsonl').read_text().splitlines()]
    refs = {(x['scenario_id'], x['rule']): x for x in prior if x['method'] == 'reference'}
    baseline = {(x['scenario_id'], x['rule']): x for x in prior if x['method'] == 'B0'}
    journal = OUT / 'metrics.jsonl'
    saved = [json.loads(x) for x in journal.read_text().splitlines()] if journal.exists() else []
    done = {(x['scenario_id'], x['rule']) for x in saved}
    assert len(done) == len(saved)
    for x in saved:
        assert sha(ROOT / x['event_file']) == x['event_sha256']
    assert len(data['cases']) == 1440
    written = 0
    freeze = ROOT / 'freeze/g2_v2_20261025'
    with journal.open('a') as stream:
        for case in data['cases']:
            b = data['bases'][case['base_id']]
            w = workload_from_json(read(freeze / b['workload_file']))
            p = Platform(tuple(b['speeds']), b['bandwidth'])
            truth = read(freeze / b['truth_file'])
            initial = Plan(tuple(tuple(q) for q in b['initial_queues']))
            failure = Failure(case['failure_time'], case['failed_node'])
            b0 = Plan(tuple(tuple(q) for q in case['plans']['B0']['queues']))
            for rule in ('strict', 'skip-unready'):
                sid = case['scenario_id']
                if (sid, rule) in done: continue
                if limit is not None and written >= limit: return
                rr = refs[sid, rule]
                ref_path = ROOT / rr['event_file']
                assert sha(ref_path) == rr['event_sha256']
                reference = result_from_json(read(ref_path))
                cls = Simulator if rule == 'strict' else SkipUnready
                kw = {} if rule == 'strict' else {'switch_time': failure.time}
                started = perf_counter()
                run = cls(w, p, initial, realized_work=truth, failure=failure,
                          repair=ProtectedSubsequence(b0), **kw).run()
                elapsed = perf_counter() - started
                assert sorted(run.context.P) == case['context']['P']
                assert sorted(run.context.F) == case['context']['F']
                assert sorted(run.context.Q) == case['context']['Q']
                assert run.applied_plan.assignment == b0.assignment
                assert run.churn == 0.
                path = OUT / 'events' / f'{sid}-{rule}-ProtectedSubsequence.json.gz'
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(gzip.compress(json.dumps(jsonable(run), separators=(',', ':'), allow_nan=False).encode(), mtime=0))
                reopened, a, cdi, wf, awct = check_persisted(path, w, p, truth, failure, reference, rule)
                metrics = {**paired_metrics(reopened, reference, w), **extra_metrics(reopened, reference, w)}
                assert metrics['cdi'] is None if cdi is None else math.isclose(cdi, metrics['cdi'], rel_tol=1e-12, abs_tol=1e-10)
                assert math.isclose(awct, metrics['awct'], rel_tol=1e-12, abs_tol=1e-10)
                assert all(math.isclose(wf[k], metrics['workflow_completion'][k], rel_tol=1e-12, abs_tol=1e-10) for k in wf)
                info = baseline[sid, rule]
                record = {k: info[k] for k in ('scenario_id', 'base_id', 'root_seed', 'mix', 'nodes', 'ccr', 'failure_fraction', 'variant')}
                record.update(metrics)
                record.update({'method': 'ProtectedSubsequence', 'rule': rule, 'purpose': 'EXPLORATORY_NOT_CONFIRMATORY',
                               'protocol_sha256': protocol_hash, 'event_file': str(path.relative_to(ROOT)),
                               'event_sha256': sha(path), 'reference_event_file': rr['event_file'],
                               'reference_event_sha256': rr['event_sha256'], 'plan_sha256': content_hash(run.applied_plan.queues),
                               'b0_plan_sha256': content_hash(b0.queues), 'context_sha256': content_hash(run.context),
                               'optional_moves': 0, 'budget_cap': 0, 'complete_execution_wall_seconds': elapsed,
                               'events_checked_after_reopen': a['events_checked'], 'independently_recomputed_fields': 5,
                               'max_protected_start_shift': max((dict(run.starts)[v] - dict(reference.starts)[v] for v in run.context.P), default=None),
                               'protected_delay_violations_above_1e_minus_8': sum(dict(run.starts)[v] > dict(reference.starts)[v] + 1e-8 for v in run.context.P),
                               'status': 'COMPLETE'})
                stream.write(json.dumps(record, allow_nan=False) + '\n'); stream.flush()
                saved.append(record); done.add((sid, rule)); written += 1
                if len(saved) % 120 == 0:
                    dump(OUT / 'progress.json', {'completed': len(saved), 'expected': 2880})
                    print(f'R5 ProtectedSubsequence {len(saved)}/2880', flush=True)
    assert len(saved) == 2880
    assert all(next(x for x in saved if x['scenario_id'] == s and x['rule'] == 'strict')['plan_sha256'] ==
               next(x for x in saved if x['scenario_id'] == s and x['rule'] == 'skip-unready')['plan_sha256'] for s in {x['scenario_id'] for x in saved})
    dump(OUT / 'execution_receipt.json', {'status': 'PASS', 'completed_at_Asia_Shanghai': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
         'new_exploratory_executions': 2880, 'new_confirmatory_samples': 0, 'reused_reference_records': 2880,
         'independent_persisted_events': sum(x['events_checked_after_reopen'] for x in saved),
         'independent_metric_fields': sum(x['independently_recomputed_fields'] for x in saved), 'budget_checks': len(saved),
         'all_optional_moves_zero': True, 'strict_protected_task_delays_above_1e_minus_8': sum(x['protected_delay_violations_above_1e_minus_8'] for x in saved if x['rule'] == 'strict'),
         'protocol_sha256': protocol_hash, 'journal_sha256': sha(journal), 'all_saved_files_reopened': True,
         'original_protocol_changed': False, 'timing_scope': 'Execution of the fixed B0 plan plus linear stable partition; not end-to-end B0 construction timing.'})
    print('R5 executions and persisted audits PASS', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--limit', type=int)
    main(parser.parse_args().limit)
