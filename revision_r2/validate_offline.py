"""Check 20 prespecified offline pool choices by complete event execution."""
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from revision_r2.common import Evidence, capture, dump, sha
from revision_r2.pool_analysis import THETAS, EPSILONS, choose, construct
from sail.simulator import Simulator, content_hash
from sail.model import RepairDecision
from sail.audit import audit_result
from sail.metrics import paired_metrics


def main():
    ev = Evidence()
    pool = [json.loads(s) for s in (ROOT / 'revision_r2/analysis/pool_cases.jsonl').read_text().splitlines()]
    cases = [c for c in ev.cases if c['variant'] == 'main' and c['root_seed'] < 81010 and c['nodes'] == 4 and c['failure_fraction'] == .6][:20]
    folder = ROOT / 'revision_r2/exploratory/offline_validation'
    folder.mkdir(parents=True, exist_ok=True)
    rows = []
    for i, case in enumerate(cases):
        theta, epsilon = THETAS[i % 6], EPSILONS[(i // 6 + i) % 6]
        pc = next(p for p in pool if p['base_id'] == case['base_id'] and p['failure_fraction'] == case['failure_fraction'] and p['theta'] == theta)
        choice, feasible, _ = choose(pc['candidates'], pc['b2_awct'], epsilon)
        snap, ctx = capture(ev, case)
        plan, forecast = construct(snap, ctx, choice['name'], theta)
        assert content_hash(plan.queues) == choice['plan_sha256']
        w, p, truth = ev.inputs(case['base_id'])
        run = Simulator(w, p, ev.initial_plan(case['base_id']), realized_work=truth,
                        failure=ev.failure(case), repair=lambda *_: RepairDecision(ctx.Q, plan)).run()
        ref = ev.result('ref-' + case['base_id'])
        audit = audit_result(run, w, p, realized_work=truth, expected_failure=ev.failure(case), reference=ref)
        metrics = paired_metrics(run, ref, w)
        assert math.isclose(metrics['cdi'], choice['cdi'], abs_tol=1e-8)
        assert math.isclose(run.awct, choice['awct'], abs_tol=1e-8)
        assert all(math.isclose(t, choice['workflow_completion'][wf], abs_tol=1e-8) for wf, t in run.workflow_finishes)
        event_file = f'events/offline-{i:02d}.json'
        dump(folder / event_file, run)
        rows.append({**{k: case[k] for k in ('scenario_id', 'base_id', 'root_seed', 'mix', 'nodes', 'ccr', 'failure_fraction', 'variant')},
                     'job_id': f'r2-offline-validation-{i:02d}', 'method': 'OfflineChoice', 'kind': 'failure', 'status': 'COMPLETE',
                     'theta': theta, 'epsilon': epsilon, 'selected_candidate': choice['name'], 'quality_feasible': feasible,
                     **metrics, 'workflow_completion': dict(run.workflow_finishes), 'events_checked': audit['events_checked'],
                     'event_file': event_file, 'event_sha256': sha(folder / event_file), 'purpose': 'VALIDATION_NOT_NEW_SAMPLE'})
    (folder / 'metrics.jsonl').write_text(''.join(json.dumps(r, allow_nan=False) + '\n' for r in rows))
    dump(folder / 'summary.json', {'status': 'PASS', 'executions': len(rows), 'planned': 20,
         'events_checked': sum(r['events_checked'] for r in rows), 'violations': 0,
         'journal_sha256': sha(folder / 'metrics.jsonl'), 'new_confirmatory_samples': 0})
    print('PASS: 20 offline choices match complete execution, including workflow completions')


if __name__ == '__main__': main()
