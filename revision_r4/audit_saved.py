"""Reopen persisted compressed logs and independently replay every new execution."""
import json
import math
import sys
import argparse
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from revision_r4.common import OUT, Evidence, read_rows, read_doc, sha, dump, extra_metrics, error_work, check_protocol
from revision_r2.audit_dispatch import audit_result as audit_skip
from sail.audit import audit_result
from sail.frozen import result_from_json
from sail.metrics import paired_metrics
from sail.model import Failure
from v2_preparation.frozen import verify_v2


def main(only=None,allow_partial=False):
    protocol = check_protocol(); ev = Evidence(); totals = {}; all_events = metric_checks = budgets = 0; largest = 0.
    registration = json.loads((OUT / 'reports/execution_registration.json').read_text())
    for path, digest in registration['files'].items(): assert sha(ROOT / path) == digest
    shard_registration=OUT/'reports/shard_registration.json'
    if shard_registration.exists():assert sha(OUT/'run_shard.py')==read_doc(shard_registration)['wrapper_sha256']
    for part, expected in (('dispatch', 23040), ('error', 1920), ('latency', 480)):
        if only is not None and part not in only: continue
        folder = OUT / 'exploratory' / part
        raw=(folder/'metrics.jsonl').read_bytes();raw=raw[:raw.rfind(b'\n')+1]
        lines=raw.splitlines(keepends=True);rows=[json.loads(s) for s in lines]
        assert len(rows) <= expected and (allow_partial or len(rows)==expected)
        indexed = {r['job_id']: r for r in rows}; assert len(indexed) == len(rows)
        receipt = OUT / 'reports' / ('event_audit_' + part + '.json')
        if receipt.exists():
            old = read_doc(receipt)
            assert old['journal_sha256'] == sha(folder / 'metrics.jsonl')
            for r in rows: assert sha(ROOT / r['event_file']) == r['event_sha256']
            totals[part] = old
            all_events += old['event_records_checked']; metric_checks += old['metric_checks']; budgets += old['integer_budget_checks']
            continue
        checkpoint=OUT/'reports'/('event_audit_'+part+'_checkpoint.json')
        refs = {}; events = checks = capchecks = new = aliases = 0; used_sources = set();completed_prefix=0
        if checkpoint.exists():
            cp=read_doc(checkpoint);completed_prefix=cp['records_checked']
            assert hashlib.sha256(b''.join(lines[:completed_prefix])).hexdigest()==cp['prefix_sha256']
            events,checks,capchecks,new,aliases=(cp[k] for k in ('event_records_checked','metric_checks','integer_budget_checks','new_executions','reused_source_records_verified'))
        for i, r in enumerate(rows):
            path = ROOT / r['event_file']; assert sha(path) == r['event_sha256']; used_sources.add(r['event_file'])
            if i<completed_prefix:continue
            if not r['new_execution']: aliases += 1; continue
            w, p, truth = ev.inputs(r['base_id'])
            if part == 'error':
                truth = read_doc(ROOT / r['truth_file'])
                assert truth == error_work(w, r['root_seed'], r['mix'], r['draw'], float(r['variant'][2:]))
            run = result_from_json(read_doc(path)); ref = None; failure = None
            if r['method'] != 'reference':
                if part == 'latency':
                    original = ev.main[r['base_id'], r['failure_fraction']]
                    f = ev.failure(original); failure = Failure(f.time, f.node, r['delay_pbar'] * w.pbar)
                    ref = ev.result('ref-' + r['base_id'])
                else:
                    refid = f'r4-{part}-{r["scenario_id"]}-{r["rule"]}-reference'
                    rr = indexed[refid]
                    if refid not in refs: refs = {refid: result_from_json(read_doc(ROOT / rr['event_file']))}
                    ref = refs[refid]
                    if part == 'error': failure = Failure(ref.makespan * .6, r['failed_node'])
                    else: failure = ev.failure(ev.main[r['base_id'], r['failure_fraction']])
            if r['rule'] == 'skip-unready':
                switch = ev.failure(ev.main[r['base_id'], r['failure_fraction']]).time
                a = audit_skip(run, w, p, realized_work=truth, expected_failure=failure, reference=ref, dispatch_switch_time=switch)
            else: a = audit_result(run, w, p, realized_work=truth, expected_failure=failure, reference=ref)
            assert a['events_checked'] == r['events_checked']; events += a['events_checked']; new += 1
            if r['method'] != 'reference':
                values = {**paired_metrics(run, ref, w), **extra_metrics(run, ref, w)}
                for key in ('awct', 'makespan', 'churn', 'cdi', 'protected_late_fraction', 'protected_signed', 'protected_absolute', 'protected_p95_positive'):
                    if values[key] is None: assert r[key] is None
                    else:
                        error = abs(values[key] - r[key]); largest = max(largest, error); assert error < 1e-10
                    checks += 1
                assert values['workflow_completion'] == r['workflow_completion']
                moves = sum(run.applied_plan.assignment[v] != dict(run.context.old_assignment)[v] for v in run.context.Q - run.context.F)
                assert moves == r['optional_moves'] <= r['budget_cap'] == math.floor(.1 * max(1, len(run.context.Q)))
                capchecks += 1
            if new % 240 == 0: print(f'R4 independent replay {part}: {new} new executions', flush=True)
        totals[part] = {'new_executions': new, 'reused_source_records_verified': aliases, 'unique_source_files': len(used_sources),
            'event_records_checked': events, 'metric_checks': checks, 'integer_budget_checks': capchecks,
            'journal_sha256': sha(folder / 'metrics.jsonl')}
        assert new==sum(r['new_execution'] for r in rows)
        assert events==sum(r['events_checked'] for r in rows)
        assert checks==8*sum(r['new_execution'] and r['kind']=='failure' for r in rows)
        if len(rows)==expected:dump(receipt, totals[part])
        else:dump(checkpoint,{**totals[part],'status':'PARTIAL','records_checked':len(rows),'prefix_sha256':hashlib.sha256(raw).hexdigest()})
        all_events += events; metric_checks += checks; budgets += capchecks
    verify_v2(ROOT, ROOT / 'freeze/g2_v2_20261025')
    dump(OUT / 'reports' / ('persisted_event_audit.json' if only is None else 'partial_event_audit.json'), {'status': 'PARTIAL' if allow_partial else 'PASS', 'parts': totals, 'event_records_checked': all_events,
        'metric_checks': metric_checks, 'integer_budget_checks': budgets, 'violations': 0, 'max_metric_abs_difference': largest,
        'original_v2_freeze_verified': True, 'protocol_sha256': protocol, 'new_confirmatory_samples': 0})
    print('R4 all persisted execution audits PASS')


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--part', nargs='+', choices=('dispatch', 'error', 'latency'));p.add_argument('--allow-partial',action='store_true')
    a=p.parse_args();main(a.part,a.allow_partial)
