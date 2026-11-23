"""Offline nested-pool ablation of the original six fixed budget levels."""
import json
import math
import sys
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from revision_r4.common import OUT, Evidence, read_rows, sha, dump, check_protocol
from revision_r2.common import capture
from revision_r2.pool_analysis import construct, THETAS, EPSILONS
from revision_r1.analyze import View
from sail.simulator import content_hash


def main():
    check_protocol(); ev = Evidence(); groups = defaultdict(dict)
    for r in read_rows(ROOT / 'revision_r2/analysis/pool_cases.jsonl'):
        if r['exact_work'] and r['root_seed'] < 81010 and r['nodes'] == 4 and r['failure_fraction'] == .6:
            groups[r['base_id']][r['theta']] = r
    assert len(groups) == 60 and all(set(g) == set(THETAS) for g in groups.values())

    @lru_cache(maxsize=16)
    def snap(bid): return capture(ev, ev.main[bid, .6])

    @lru_cache(maxsize=128)
    def queues(bid, theta, name, digest):
        s, ctx = snap(bid); plan, _ = construct(s, ctx, name, theta)
        assert content_hash(plan.queues) == digest
        return plan.queues

    def select(candidates, b2, eps, bid):
        feasible = [c for c in candidates if c['awct'] <= (1 + eps) * b2]
        def key(c): return ((c['cdi'] or 0.), c['awct'], c['churn'], c['name']) if feasible else (c['awct'], (c['cdi'] or 0.), c['churn'], c['name'])
        best = min(key(c) for c in feasible or candidates)
        tied = [c for c in feasible or candidates if key(c) == best]
        chosen = min(tied, key=lambda c: queues(bid, c['source_theta'], c['name'], c['plan_sha256'])) if len(tied) > 1 else tied[0]
        return chosen, bool(feasible)

    records = []; losses = eligible = violations = 0
    for bid, g in sorted(groups.items()):
        union = {}; previous = {}
        original = ev.main[bid, .6]
        for theta in THETAS:
            row = g[theta]; assert math.isclose(row['b2_awct'], g[0.]['b2_awct'], abs_tol=1e-8)
            for c in row['candidates']: union.setdefault(c['plan_sha256'], {**c, 'source_theta': theta})
            for c in union.values():
                assert round(c['churn'] * max(1, original['Q_count'])) <= math.floor(theta * max(1, original['Q_count']))
            for eps in EPSILONS:
                chosen, ok = select(list(union.values()), row['b2_awct'], eps, bid)
                ordinary, original_ok = select([{**c, 'source_theta': theta} for c in row['candidates']], row['b2_awct'], eps, bid)
                if eps in previous:
                    before, before_ok = previous[eps]
                    if before_ok and ok:
                        eligible += 1; violations += chosen['cdi'] > before['cdi'] + 1e-9
                    if not before_ok and ok and chosen['cdi'] > before['cdi'] + 1e-9: losses += 1
                previous[eps] = (chosen, ok)
                records.append({**{k: row[k] for k in ('base_id', 'root_seed', 'mix', 'nodes', 'ccr', 'failure_fraction')},
                    'theta': theta, 'epsilon': eps, 'ordinary_pool_size': len(row['candidates']), 'nested_pool_size': len(union),
                    'ordinary': {k: ordinary[k] for k in ('name', 'plan_sha256', 'cdi', 'awct', 'churn', 'source_theta')},
                    'nested': {k: chosen[k] for k in ('name', 'plan_sha256', 'cdi', 'awct', 'churn', 'source_theta')},
                    'ordinary_quality_feasible': original_ok, 'nested_quality_feasible': ok})
    assert len(records) == 2160 and violations == 0
    (OUT / 'analysis/nested_choices.jsonl').write_text(''.join(json.dumps(r, allow_nan=False) + '\n' for r in records))
    grid = []
    for theta in THETAS:
        for eps in EPSILONS:
            cs = [r for r in records if r['theta'] == theta and r['epsilon'] == eps]; v = View(cs)
            grid.append({'theta': theta, 'epsilon': eps,
                'ordinary_cdi': v.effect(lambda c: c['ordinary']['cdi']), 'nested_cdi': v.effect(lambda c: c['nested']['cdi']),
                'nested_minus_ordinary_cdi': v.effect(lambda c: c['nested']['cdi'] - c['ordinary']['cdi']),
                'nested_relative_awct_vs_ordinary': v.effect(lambda c: c['nested']['awct'] / c['ordinary']['awct'] - 1),
                'plan_changes': sum(c['nested']['plan_sha256'] != c['ordinary']['plan_sha256'] for c in cs),
                'ordinary_fallbacks': sum(not c['ordinary_quality_feasible'] for c in cs), 'nested_fallbacks': sum(not c['nested_quality_feasible'] for c in cs)})
    dump(OUT / 'analysis/nested_results.json', {'status': 'PASS', 'cases': 60, 'offline_choices': 2160, 'grid': grid,
        'quality_feasible_adjacent_budget_comparisons': eligible, 'CDI_monotonicity_violations_while_quality_feasible': violations,
        'CDI_increases_on_fallback_to_quality_transition': losses, 'new_simulation_executions': 0, 'new_confirmatory_samples': 0,
        'source_sha256': sha(ROOT / 'revision_r2/analysis/pool_cases.jsonl'), 'choices_sha256': sha(OUT / 'analysis/nested_choices.jsonl')})
    print('Nested pool PASS: 2160 choices, quality-feasible monotonicity verified')


if __name__ == '__main__': main()
