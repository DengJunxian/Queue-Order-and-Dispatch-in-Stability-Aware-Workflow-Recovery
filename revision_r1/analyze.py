"""Post-freeze descriptive estimates; preserve original endpoints and root blocks."""
import json
import math
import sys
from collections import Counter
from functools import lru_cache
from pathlib import Path
from statistics import mean

import numpy as np
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from revision_r1.io import dump

BS, PM, BH = 'BudgetSelect10', 'PoolMinAWCT10', 'BudgetHEFT10'
Q0, LOCK = 'QueueRepair0', 'B0AssignmentReorder'
TOL = 1e-9


@lru_cache(maxsize=3)
def counts(n):
    rng = np.random.Generator(np.random.PCG64(83000))
    indices = rng.integers(0, n, size=(5000, n))
    out = np.zeros((5000, n), dtype=np.int32)
    np.add.at(out, (np.repeat(np.arange(5000), n), indices.ravel()), 1)
    return np.vstack((np.ones((1, n), dtype=np.int32), out))


def number(x):
    return float(x) if np.isfinite(x) else None


class View:
    """Each case supplies one cell observation; missing groups stay missing."""
    def __init__(self, cases, roots=None):
        self.cases = cases
        self.roots = sorted(roots if roots is not None else {c['root_seed'] for c in cases})
        self.cells = sorted({(c['mix'], c['nodes'], c['ccr'], c['failure_fraction']) for c in cases})
        self.mix_columns = [[j for j, c in enumerate(self.cells) if c[0] == m] for m in sorted({c[0] for c in self.cells})]
        self.i = {v: i for i, v in enumerate(self.roots)}
        self.j = {v: j for j, v in enumerate(self.cells)}
        seen = set()
        for c in cases:
            k = self.position(c)
            assert k not in seen, ('duplicate case grid', k)
            seen.add(k)

    def position(self, c):
        return self.i[c['root_seed']], self.j[c['mix'], c['nodes'], c['ccr'], c['failure_fraction']]

    def curve(self, function):
        a = np.full((len(self.roots), len(self.cells)), np.nan)
        for c in self.cases:
            x = function(c)
            if x is not None:
                a[self.position(c)] = x
        valid = np.isfinite(a)
        ct = counts(len(self.roots))
        sums = ct @ np.where(valid, a, 0)
        den = ct @ valid.astype(np.int32)
        cm = np.divide(sums, den, out=np.full(sums.shape, np.nan), where=den > 0)
        mm = []
        for columns in self.mix_columns:
            part = cm[:, columns]
            n = np.isfinite(part).sum(axis=1)
            mm.append(np.divide(np.nansum(part, axis=1), n, out=np.full(len(ct), np.nan), where=n > 0))
        estimates = np.mean(np.stack(mm), axis=0)
        return estimates, int(valid.sum()), int(a.size - valid.sum())

    @staticmethod
    def describe(curve, defined, absent):
        draws = curve[1:]
        complete = np.isfinite(draws).all()
        return {'point': number(curve[0]), 'ci95': [float(x) for x in np.quantile(draws, [.025, .975])] if complete else None,
                'upper95': float(np.quantile(draws, .95)) if complete else None, 'defined_pairs': defined,
                'undefined_pairs': absent, 'defined_bootstrap_draws': int(np.isfinite(draws).sum())}

    def effect(self, function):
        return self.describe(*self.curve(function))

    def ratio(self, a, b):
        ca, n, na = self.curve(a)
        cb, nb, nab = self.curve(b)
        assert (n, na) == (nb, nab)
        ratio = np.divide(ca, cb, out=np.full(ca.shape, np.nan), where=cb != 0) - 1
        return self.describe(ratio, n, na)


def runs(c):
    return {r['method']: r for r in c['runs']}


def contrast(cases, a, b, roots=None):
    view = View(cases, roots)
    def field(c, method, metric):
        return runs(c).get(method, {}).get(metric)
    def delta(c, metric):
        x, y = field(c, a, metric), field(c, b, metric)
        return x - y if x is not None and y is not None else None
    def relative(c):
        x, y = field(c, a, 'awct'), field(c, b, 'awct')
        return x / y - 1 if x is not None and y is not None else None
    return {'target': a, 'comparator': b, 'cases': len(cases), 'root_blocks': len(view.roots),
            'cdi': view.effect(lambda c: delta(c, 'cdi')),
            'relative_awct': view.effect(relative),
            'relative_cdi_ratio_of_means': view.ratio(lambda c: field(c, a, 'cdi'), lambda c: field(c, b, 'cdi')),
            'equal_workflow_cdi': view.effect(lambda c: delta(c, 'equal_workflow_cdi'))}


def sign_counts(cases, comparator, predicate=lambda c: True):
    values = [runs(c)[BS]['cdi'] - runs(c)[comparator]['cdi'] for c in cases if predicate(c)]
    return {'n': len(values), 'strict_negative': sum(x < 0 for x in values), 'strict_positive': sum(x > 0 for x in values),
            'strict_zero': sum(x == 0 for x in values), 'negative_tol': sum(x < -TOL for x in values),
            'positive_tol': sum(x > TOL for x in values), 'tie_tol': sum(abs(x) <= TOL for x in values),
            'min': min(values, default=None), 'max': max(values, default=None)}


def prediction(cases, method):
    rr = [runs(c)[method] for c in cases]
    errors = np.array([r['cdi'] - r['predicted_cdi'] for r in rr])
    aa = np.array([r['awct'] - r['predicted_awct'] for r in rr])
    return {'n': len(rr), 'cdi_MAE': float(np.mean(abs(errors))), 'cdi_max_abs_error': float(max(abs(errors))),
            'cdi_mean_signed_error': float(np.mean(errors)),
            'cdi_Spearman': number(spearmanr([r['cdi'] for r in rr], [r['predicted_cdi'] for r in rr]).statistic),
            'awct_MAE': float(np.mean(abs(aa))), 'awct_max_abs_error': float(max(abs(aa)))}


def frequencies(cases):
    categories = ('v1_H0', 'v1_H1', 'v1_H2', 'QueueRepair0', 'BudgetHEFT', 'B2')
    out = {}
    for method in (BS, PM):
        if method not in runs(cases[0]):
            method = next(k for k in runs(cases[0]) if k.startswith(method.replace('10', '')))
        names = Counter('BudgetHEFT' if r['selected_candidate'].startswith('BudgetHEFT') else r['selected_candidate']
                        for r in (runs(c)[method] for c in cases))
        out[method] = {'n': len(cases), 'representative_counts': {k: names[k] for k in categories},
                       'fallbacks': sum(runs(c)[method]['quality_feasible'] is False for c in cases),
                       'plan_match_Q0': sum(runs(c)[method]['plan_sha256'] == runs(c)[Q0]['plan_sha256'] for c in cases if Q0 in runs(c)),
                       'plan_match_locked': sum(runs(c)[method]['plan_sha256'] == runs(c)[LOCK]['plan_sha256'] for c in cases if LOCK in runs(c)),
                       'Q0_comparable_cases': sum(Q0 in runs(c) for c in cases), 'locked_comparable_cases': sum(LOCK in runs(c) for c in cases)}
    return out


def workflow_analysis(cases):
    out = {'affected_workflow_count_distribution': dict(sorted(Counter(len(c['affected_workflows']) for c in cases).items())),
           'cases_P_in_affected_workflow': sum(c['P_in_affected_workflows'] > 0 for c in cases),
           'total_P_in_affected_workflows': sum(c['P_in_affected_workflows'] for c in cases),
           'total_P': sum(c['P_count'] for c in cases), 'contrasts': {}}
    for b in (PM, BH, 'B2', Q0, LOCK):
        pairs = {}
        for group in ('affected', 'unaffected', 'all'):
            def members(c):
                return [wf for wf in runs(c)[BS]['workflow_completion'] if group == 'all' or
                        ((wf in c['affected_workflows']) == (group == 'affected'))]
            def values(c):
                rr = runs(c)
                return [rr[BS]['workflow_completion'][w] / rr[b]['workflow_completion'][w] - 1 for w in members(c)]
            effect = View(cases).effect(lambda c: mean(values(c)) if values(c) else None)
            worst = [max(values(c)) for c in cases if values(c)]
            worst_stretch = [max(runs(c)[BS]['workflow_stretch'][w] for w in members(c)) for c in cases if members(c)]
            effect.update({'defined_cases': len(worst), 'missing_cases': len(cases) - len(worst),
                           'workflow_observations': sum(len(members(c)) for c in cases),
                           'worst_workflow_relative_effect_p50_p95_max': [float(x) for x in np.quantile(worst, [.5, .95, 1])] if worst else None,
                           'cases_any_workflow_gt_5pct': sum(x > .05 for x in worst),
                           'worst_reference_stretch_p50_p95_max': [float(x) for x in np.quantile(worst_stretch, [.5, .95, 1])] if worst_stretch else None})
            pairs[group] = effect
        out['contrasts'][b] = pairs
    return out


def main():
    source = ROOT / 'revision_r1/analysis/case_analysis.jsonl'
    cases = [json.loads(s) for s in source.read_text().splitlines()]
    assert len(cases) == 1920
    maincases = [c for c in cases if c['variant'] == 'main']
    assert len(maincases) == 1440
    frozen = json.loads((ROOT / 'results/g2_v2_20261025/statistics.json').read_text())
    checks = []
    primary = {}
    for b in (PM, BH):
        primary[b] = {}
        for label in ('overall', 'A', 'B', 'C'):
            view = maincases if label == 'overall' else [c for c in maincases if c['mix'] == label]
            s = contrast(view, BS, b)
            expected = frozen['primary'][b]['overall' if label == 'overall' else 'mixes']
            if label != 'overall': expected = expected[label]
            for metric in ('cdi', 'relative_awct'):
                for key in ('point', 'upper95'):
                    checks.append(abs(s[metric][key] - expected[metric][key]))
                checks.extend(abs(x - y) for x, y in zip(s[metric]['ci95'], expected[metric]['ci95']))
                for k in ('defined_pairs', 'undefined_pairs', 'defined_bootstrap_draws'):
                    assert s[metric][k] == expected[metric][k]
            primary[b][label] = s
    assert max(checks) < 1e-12
    new = {b: {label: contrast(maincases if label == 'overall' else [c for c in maincases if c['mix'] == label], BS, b)
               for label in ('overall', 'A', 'B', 'C')} for b in (Q0, LOCK, 'B2')}
    mechanism = {method: contrast(maincases, method, 'B0') for method in (Q0, LOCK, BS)}
    m1, freq, robustness = {}, {}, {}
    for variant in ('main', 'cv0.1', 'cv0.3', 'control_delay'):
        view = [c for c in cases if c['variant'] == variant]
        m1[variant] = {'against_pool': sign_counts(view, PM), 'against_budgetheft': sign_counts(view, BH),
                       'pool_fallback': sign_counts(view, PM, lambda c: c['quality_feasible_count'] == 0),
                       'pool_quality_nonempty': sign_counts(view, PM, lambda c: c['quality_feasible_count'] > 0),
                       'bh_in_quality_set': sign_counts(view, BH, lambda c: c['quality_feasible_count'] > 0 and c['budgetheft_quality_feasible']),
                       'bh_outside_quality_set_or_fallback': sign_counts(view, BH, lambda c: not (c['quality_feasible_count'] > 0 and c['budgetheft_quality_feasible'])),
                       'predictions': {m: prediction(view, m) for m in (BS, PM)}}
        freq[variant] = frequencies(view)
        if variant != 'main': robustness[variant] = {b: contrast(view, BS, b) for b in (PM, BH, LOCK, 'B2')}
    subset = [c for c in maincases if c['root_seed'] < 81010 and c['nodes'] == 4 and c['failure_fraction'] == .6]
    freq['theta0.1'] = frequencies(subset)
    for theta in ('0', '0.05', '0.2', '0.5', '1'):
        freq['theta' + theta] = frequencies([c for c in cases if c['variant'] == 'theta' + theta])
    nonempty = [c for c in maincases if c['F_count'] > 0]
    sensitivity = {'F_nonempty': {'cases': len(nonempty), 'contrasts': {b: contrast(nonempty, BS, b, range(81000, 81060)) for b in (PM, BH, Q0, LOCK, 'B2')}},
                   'F_empty': {'cases': 1440 - len(nonempty),
                               'B0_max_cdi': max(runs(c)['B0']['cdi'] for c in maincases if not c['F_count'])}}
    signed = {m: {metric: View(maincases).effect(lambda c, m=m, metric=metric: runs(c)[m][metric])
                  for metric in ('same_fault_signed_delay', 'mean_advance_vs_b0', 'mean_added_delay_vs_b0', 'advance_fraction_vs_b0', 'delay_fraction_vs_b0')}
              for m in (BS, Q0, LOCK, PM, BH, 'B2')}
    view = View(maincases)
    a, _, _ = view.curve(lambda c: runs(c)['B0']['cdi'] - runs(c)[BS]['cdi'])
    denom, _, _ = view.curve(lambda c: runs(c)['B0']['cdi'] - c['pool_cdi_floor'])
    envelope = view.describe(np.divide(a, denom, out=np.full(a.shape, np.nan), where=denom != 0), len(maincases), 0)
    shares = {}
    for m in (Q0, LOCK):
        num, n, na = view.curve(lambda c, m=m: runs(c)['B0']['cdi'] - runs(c)[m]['cdi'])
        shares[m] = view.describe(num / a, n, na)
    traces = []
    for p in sorted((ROOT / 'v2_preparation/data/processed').glob('*.json')):
        d = json.loads(p.read_text())
        if 'tasks' not in d: continue
        runtime = [t['runtime_seconds'] for t in d['tasks']]
        traces.append({'file': p.name, 'tasks': len(runtime), 'mean_runtime_seconds': mean(runtime),
                       'median_runtime_seconds': float(np.median(runtime)),
                       'BS_p50_application_over_mean_trace': .35274575 / mean(runtime),
                       'BS_p95_application_over_mean_trace': .93384916 / mean(runtime)})
    assert len(traces) == 6, 'all six processed runtime traces are required for descriptive recomputation'
    worst_examples = {}
    for comparator in (PM, 'B2'):
        observations = []
        for c in maincases:
            rr = runs(c)
            for wf, completion in rr[BS]['workflow_completion'].items():
                baseline = rr[comparator]['workflow_completion'][wf]
                observations.append({'scenario_id': c['scenario_id'], 'workflow': wf, 'comparator': comparator,
                                     'relative_completion_change': completion / baseline - 1,
                                     'BS_completion': completion, 'control_completion': baseline,
                                     'workflow_affected': wf in c['affected_workflows'],
                                     'selected_candidate': rr[BS]['selected_candidate'],
                                     'predicted_quality_feasible': rr[BS]['quality_feasible']})
        worst_examples[comparator] = sorted(observations, key=lambda r: r['relative_completion_change'], reverse=True)[:10]
    result = {'purpose': 'POST_FREEZE_DESCRIPTIVE_NOT_NEW_CONFIRMATION',
              'statistics': {'root_bootstrap_draws': 5000, 'seed': 83000, 'intervals': 'unadjusted percentile 95%',
                             'relative_CDI': 'ratio of equally weighted aggregate means minus one',
                             'relative_AWCT': 'mean of per-case ratios minus one', 'sign_tolerance': TOL},
              'frozen_primary_reproduction': {'status': 'PASS', 'metric_results': 16, 'max_abs_error': max(checks)},
              'primary': primary, 'additional_main': new, 'mechanism': mechanism, 'M1': m1,
              'candidate_frequencies': freq, 'robustness': robustness, 'workflow_groups': workflow_analysis(maincases),
              'sensitivities': sensitivity, 'signed_delay': signed, 'queue_aggregate_reduction_shares': shares,
              'observed_pool_capture_fraction': envelope, 'trace_runtime_context': traces,
              'largest_workflow_completion_changes': worst_examples,
              'budget_audit_labels': {'main': 6 * 1440, 'robustness': 5 * 180, 'extra_budgets': 3 * 300, 'total': 10440}}
    dump(ROOT / 'revision_r1/analysis/descriptive_results.json', result)
    print(json.dumps({'status': 'PASS', 'cases': len(cases), 'reproduction_max_error': max(checks), 'additional_main': {b: new[b]['overall'] for b in new}}))


if __name__ == '__main__':
    main()
