"""Paired exploratory analysis without changing any previous result artifact."""
import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from revision_r1.analyze import View, contrast, runs
from revision_r4.analyze import distribution
from revision_r5.run_control import OUT, sha, read, dump, verify_registration

PS = 'ProtectedSubsequence'
PM = 'PoolMinAWCT10'
COMPARATORS = ('B0', 'B0AssignmentReorder', 'QueueRepair0', 'BudgetSelect10', PM, 'ProtectedFirst', 'WorkflowGuard')


def main():
    protocol_hash = verify_registration()
    current = [json.loads(x) for x in (OUT / 'metrics.jsonl').read_text().splitlines()]
    old = [json.loads(x) for x in (ROOT / 'revision_r4/exploratory/dispatch/metrics.jsonl').read_text().splitlines()]
    assert len(current) == 2880
    result = {'classification': 'EXPLORATORY_NOT_CONFIRMATORY', 'new_confirmatory_samples': 0,
              'protocol_sha256': protocol_hash, 'dispatch': {}}
    check_count = 0
    max_difference = 0.
    rng = np.random.Generator(np.random.PCG64(83000))
    draws = rng.integers(0, 60, size=(5000, 60))

    def independent_check(cases, func, expected):
        nonlocal check_count, max_difference
        roots = sorted({c['root_seed'] for c in cases})
        values = np.asarray([[func(c) for c in cases if c['root_seed'] == root] for root in roots], float)
        assert values.shape == (60, 24) and np.isfinite(values).all()
        root_values = values.mean(axis=1)
        curve = root_values[draws].mean(axis=1)
        independent = [root_values.mean(), *np.quantile(curve, [.025, .975, .95])]
        wanted = [expected['point'], *expected['ci95'], expected['upper95']]
        for got, want in zip(independent, wanted):
            diff = abs(got - want)
            max_difference = max(max_difference, diff)
            assert math.isclose(got, want, rel_tol=1e-11, abs_tol=1e-10), (got, want)
            check_count += 1

    for rule in ('strict', 'skip-unready'):
        groups = {}
        for r in old + current:
            if r['rule'] != rule or r['method'] == 'reference': continue
            sid = r['scenario_id']
            groups.setdefault(sid, {k: r[k] for k in ('scenario_id', 'root_seed', 'mix', 'nodes', 'ccr', 'failure_fraction')})
            groups[sid].setdefault('runs', []).append(r)
        cases = sorted(groups.values(), key=lambda c: c['scenario_id'])
        assert len(cases) == 1440 and all(set(runs(c)) == set((*COMPARATORS, PS)) for c in cases)
        view = View(cases)
        summaries = {}
        fields = ('cdi', 'awct', 'churn', 'protected_late_fraction', 'protected_p95_positive', 'protected_signed', 'protected_absolute')
        for field in fields:
            f = lambda c, k=field: runs(c)[PS][k]
            summaries[field] = view.effect(f)
            independent_check(cases, f, summaries[field])
        wf, case_max = [], []
        for c in cases:
            rr = runs(c)
            shifts = [t / rr[PM]['workflow_completion'][g] - 1 for g, t in rr[PS]['workflow_completion'].items()]
            wf.extend(shifts); case_max.append(max(shifts))
        summaries['workflow_inflation_vs_PM'] = distribution(wf)
        summaries['case_max_workflow_inflation_vs_PM'] = distribution(case_max)
        contrasts = {}
        for name in COMPARATORS:
            effect = contrast(cases, PS, name)
            independent_check(cases, lambda c: runs(c)[PS]['cdi'] - runs(c)[name]['cdi'], effect['cdi'])
            independent_check(cases, lambda c: runs(c)[PS]['awct'] / runs(c)[name]['awct'] - 1, effect['relative_awct'])
            deltas = [runs(c)[PS]['cdi'] - runs(c)[name]['cdi'] for c in cases]
            effect['cdi_signs_at_1e_minus_9'] = {'better': sum(x < -1e-9 for x in deltas), 'tied': sum(abs(x) <= 1e-9 for x in deltas), 'worse': sum(x > 1e-9 for x in deltas)}
            contrasts[PS + '_minus_' + name] = effect
        rr = [r for r in current if r['rule'] == rule]
        result['dispatch'][rule] = {'cases': 1440, 'environment_roots': 60, 'summaries': {PS: summaries}, 'contrasts': contrasts,
                                   'protected_task_observations': sum(r['protected_count'] for r in rr),
                                   'positive_delay_cases_at_1e_minus_9': sum(r['cdi'] > 1e-9 for r in rr),
                                   'positive_delay_tasks_at_1e_minus_8': sum(r['protected_delay_violations_above_1e_minus_8'] for r in rr),
                                   'max_protected_start_shift': max(r['max_protected_start_shift'] for r in rr)}
        result['dispatch'][rule]['subgroups'] = {key: {str(value): contrast([c for c in cases if c[key] == value], PS, PM)
                                                   for value in sorted({c[key] for c in cases})}
                                                for key in ('mix', 'nodes', 'ccr', 'failure_fraction')}
    result['input_sha256'] = {'revision_r5/metrics.jsonl': sha(OUT / 'metrics.jsonl'),
                              'revision_r4/exploratory/dispatch/metrics.jsonl': sha(ROOT / 'revision_r4/exploratory/dispatch/metrics.jsonl')}
    result['independent_statistics'] = {'status': 'PASS', 'checks': check_count, 'max_abs_difference': max_difference,
                                        'method': 'Independently compute balanced root means from raw rows and resample root indices; compare point, 95% CI endpoints and one-sided upper95.'}
    dump(OUT / 'analysis/results.json', result)
    dump(OUT / 'analysis/independent_statistics.json', result['independent_statistics'])
    print(json.dumps(result['independent_statistics']))


if __name__ == '__main__': main()
