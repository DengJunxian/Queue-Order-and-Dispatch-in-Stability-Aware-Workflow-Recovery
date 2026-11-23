"""Separate post-freeze baseline and capacity diagnostics, checkpointed by ID."""
import argparse
import hashlib
import json
import sys
from functools import lru_cache
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sail.audit import audit_result
from sail.data import random_stream, bandwidth_for_ccr
from sail.development import dump
from sail.experiment import workload_from_json
from sail.frozen import result_from_json
from sail.metrics import paired_metrics
from sail.model import Failure, Platform
from sail.scheduling import initial_heft
from sail.simulator import Simulator, content_hash
from v2_preparation.experiment import make_method
from v2_preparation.frozen import verify_v2, ApplicationTimer
from v2_preparation.metrics import queue_disturbance
from revision_r1.policies import ProtectedFirst

FREEZE = ROOT / 'freeze/g2_v2_20261025'
ORIGINAL = ROOT / 'results/g2_v2_20261025'
METHODS = ('B0', 'B2', 'QueueRepair0', 'B0AssignmentReorder', 'BudgetHEFT10', 'BudgetSelect10', 'PoolMinAWCT10', 'ProtectedFirst')


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def generalized_platform(seed, mix, nodes, workload, ccr):
    speed = random_stream(seed, mix, 'platform', 'speeds').uniform(.5, 1.5, nodes)
    return Platform(tuple(float(s) for s in speed / speed.mean()), bandwidth_for_ccr(workload, ccr))


def failure_node(seed, mix, nodes):
    return int(random_stream(seed, mix, 'failure', 'node').integers(0, nodes))


def main(part, limit=None):
    _, mf = verify_v2(ROOT, FREEZE)
    folder = ROOT / 'revision_r1/exploratory' / part
    folder.mkdir(parents=True, exist_ok=True)
    raw = {r['job_id']: r for r in (json.loads(s) for s in (ORIGINAL / 'metrics.jsonl').read_text().splitlines())}
    journal = folder / 'metrics.jsonl'
    records = {}
    if journal.exists():
        for line in journal.read_text().splitlines():
            row = json.loads(line)
            assert row['job_id'] not in records and sha(folder / row['event_file']) == row['event_sha256']
            records[row['job_id']] = row
    @lru_cache(maxsize=10)
    def original_event(jid):
        r = raw[jid]
        assert sha(ORIGINAL / r['event_file']) == r['event_sha256']
        return result_from_json(json.loads((ORIGINAL / r['event_file']).read_text()))
    @lru_cache(maxsize=10)
    def inputs(seed, mix, nodes, ccr):
        workload = workload_from_json(json.loads((FREEZE / f'public/workloads/{seed}-{mix}.json').read_text()))
        platform = generalized_platform(seed, mix, nodes, workload, ccr)
        return workload, platform, initial_heft(workload, platform)
    work = []
    if part == 'priority':
        for j in mf['jobs']:
            if j.get('method') == 'B0':
                s = next(s for s in mf['scenarios'] if s['id'] == j['scenario_id'])
                if s['variant'] in ('main', 'cv0.1', 'cv0.3', 'control_delay'):
                    work.append({'kind': 'failure', 'job_id': 'r1-' + s['id'] + '-ProtectedFirst', 'method': 'ProtectedFirst',
                                 'reference_job': 'ref-' + s['base_id'], 'original_b0_job': j['id'],
                                 **s, 'scenario_id': s['id']})
    else:
        for seed in range(81000, 81010):
            for mix in 'ABC':
                for nodes in (16, 32):
                    for ccr in (.5, 2):
                        for cv in (0, .3):
                            bid = f'r1-{seed}-{mix}-n{nodes}-ccr{ccr:g}-cv{cv:g}'
                            meta = {'base_id': bid, 'root_seed': seed, 'mix': mix, 'nodes': nodes, 'ccr': ccr, 'cv': cv}
                            work.append({**meta, 'kind': 'reference', 'job_id': 'ref-' + bid})
                            for fraction in ((.3, .6) if cv == 0 else (.6,)):
                                sid = bid + f'-f{fraction:g}'
                                for method in METHODS:
                                    work.append({**meta, 'kind': 'failure', 'job_id': sid + '-' + method, 'scenario_id': sid,
                                                 'failure_fraction': fraction, 'variant': 'main' if cv == 0 else 'cv0.3', 'method': method})
    dump(folder / 'PLAN.json', {'purpose': 'POST_FREEZE_EXPLORATORY_NOT_CONFIRMATORY', 'jobs': work,
                               'revision_protocol_sha256': sha(ROOT / 'revision_r1/protocol.json')})
    fresh = 0
    with journal.open('a') as stream:
        for job in work:
            jid = job['job_id']
            if jid in records:
                continue
            if limit is not None and fresh >= limit:
                break
            seed, mix, nodes, ccr = job['root_seed'], job['mix'], job['nodes'], job['ccr']
            w, platform, initial = inputs(seed, mix, nodes, ccr)
            if 'cv' in job:
                cv = job['cv']
            else:
                cv = 0 if job['variant'] in ('main', 'control_delay') else float(job['variant'][2:])
            truth = json.loads((FREEZE / f'evaluator/{seed}-{mix}-cv{cv:g}.json').read_text())
            if job['kind'] == 'reference':
                engine = Simulator(w, platform, initial.plan, realized_work=truth)
                run = engine.run()
                audited = audit_result(run, w, platform, realized_work=truth)
                values = {'awct': run.awct, 'makespan': run.makespan}
            else:
                if part == 'priority':
                    reference = original_event(job['reference_job'])
                    b0 = original_event(job['original_b0_job'])
                    failed = job['failed_node']
                    delay = job['control_delay_pbar_units'] * w.pbar
                else:
                    rrow = records['ref-' + job['base_id']]
                    reference = result_from_json(json.loads((folder / rrow['event_file']).read_text()))
                    bjid = job['scenario_id'] + '-B0'
                    b0 = result_from_json(json.loads((folder / records[bjid]['event_file']).read_text())) if bjid in records else None
                    failed = failure_node(seed, mix, nodes)
                    delay = 0
                failure = Failure(reference.makespan * job['failure_fraction'], failed, delay)
                policy = ProtectedFirst() if job['method'] == 'ProtectedFirst' else make_method(job['method'], initial, .1)
                engine = ApplicationTimer(w, platform, initial.plan, realized_work=truth, failure=failure, repair=policy)
                run = engine.run()
                audited = audit_result(run, w, platform, realized_work=truth, expected_failure=failure, reference=reference)
                if b0 is not None:
                    assert b0.context == run.context
                if job['method'] == 'ProtectedFirst':
                    assert run.applied_plan.assignment == b0.applied_plan.assignment
                    assert run.churn == 0
                values = {**paired_metrics(run, reference, w, same_fault_b0=b0), **queue_disturbance(run.context, run.applied_plan),
                          'F_count': len(run.context.F), 'Q_count': len(run.context.Q),
                          'workflow_completion': dict(run.workflow_finishes), 'reference_workflow_completion': dict(reference.workflow_finishes),
                          'capacity_fraction_lost': platform.speeds[failed] / sum(platform.speeds),
                          'context_sha256': content_hash(run.context),
                          'quality_feasible': getattr(policy, 'last_quality_feasible', None),
                          'selected_candidate': getattr(policy, 'last_selected', None)['name'] if getattr(policy, 'last_selected', None) else None,
                          'full_application_seconds': engine.full_application_seconds}
            event_file = 'events/' + jid + '.json'
            dump(folder / event_file, run)
            row = {**job, **values, 'status': 'COMPLETE', 'purpose': 'POST_FREEZE_EXPLORATORY_NOT_CONFIRMATORY',
                   'events_checked': audited['events_checked'], 'event_file': event_file, 'event_sha256': sha(folder / event_file)}
            stream.write(json.dumps(row, allow_nan=False) + '\n'); stream.flush()
            records[jid] = row; fresh += 1
            if len(records) % 30 == 0:
                dump(folder / 'progress.json', {'completed': len(records), 'total': len(work), 'status': 'RUNNING'})
                print(f'R1 {part} {len(records)}/{len(work)}', flush=True)
    dump(folder / 'summary.json', {'status': 'PASS' if len(records) == len(work) else 'PARTIAL',
                                 'labels': len(records), 'planned': len(work), 'new_confirmatory_samples': 0,
                                 'failures': 0, 'part': part, 'purpose': 'POST_FREEZE_EXPLORATORY_NOT_CONFIRMATORY'})


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--part', choices=('priority', 'scale'), required=True); p.add_argument('--limit', type=int)
    a = p.parse_args(); main(a.part, a.limit)
