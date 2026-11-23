"""Export one actual benchmark case for a self-contained all-method replay."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from revision_r4.common import OUT, Evidence, read_rows, dump
from sail.simulator import jsonable


def main():
    ev = Evidence(); case = next(c for c in ev.cases if c['variant'] == 'main')
    w, p, truth = ev.inputs(case['base_id']); fault = ev.failure(case)
    expected = {}
    for c in read_rows(OUT / 'exploratory/dispatch/metrics.jsonl'):
        if c['scenario_id'] == case['scenario_id'] and c['method'] != 'reference':
            expected[c['rule'] + '/' + c['method']] = {k: c[k] for k in ('awct', 'makespan', 'cdi', 'churn', 'workflow_completion', 'plan_sha256')}
    assert len(expected) == 14
    for r in case['runs']:
        key = 'strict/' + r['method']
        if key not in expected:
            expected[key] = {k: r[k] for k in ('awct', 'cdi', 'churn', 'workflow_completion', 'plan_sha256')}
    dump(ROOT / 'paper_v7/artifact/example_case/input.json', {'source_scenario_id': case['scenario_id'],
        'source_base_id': case['base_id'], 'workload': jsonable(w), 'platform': jsonable(p), 'truth': truth,
        'initial_queues': jsonable(ev.initial_plan(case['base_id']).queues), 'failure': jsonable(fault),
        'expected': expected, 'purpose': 'Full-method executable example from the actual benchmark; not an independent scientific sample.'})
    print('Self-contained actual case exported')


if __name__ == '__main__': main()
