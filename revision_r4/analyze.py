"""Paired root-block analysis of the separately registered R4 evidence."""
import json
import math
import sys
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path
from statistics import mean

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from revision_r4.common import OUT, METHODS, Evidence, read_rows, read_doc, extra_metrics, sha, dump, BS, PM, Q0, AL, check_protocol
from revision_r1.analyze import View, contrast, runs
from sail.frozen import result_from_json


def distribution(values, threshold=.05):
    a = np.asarray(values, dtype=float)
    return {'n': len(a), **{k: float(np.quantile(a, q)) for k, q in [('p50', .5), ('p90', .9), ('p95', .95), ('p99', .99)]},
            'max': float(max(a)), 'min': float(min(a)), 'mean': float(np.mean(a)),
            'threshold': threshold, 'above_5pct_count': int(np.sum(a > threshold + 1e-10)), 'above_5pct_rate': float(np.mean(a > threshold + 1e-10))}


def case_view(rows):
    groups = {}
    for r in rows:
        if r['method'] == 'reference': continue
        sid = r['scenario_id']
        if sid not in groups: groups[sid] = {**{k: r[k] for k in ('scenario_id', 'root_seed', 'mix', 'nodes', 'ccr', 'failure_fraction')}, 'runs': []}
        groups[sid]['runs'].append(r)
    assert all(set(runs(c)) == set(METHODS) for c in groups.values())
    return list(groups.values())


def summaries(cases):
    view = View(cases); answer = {}
    for m in METHODS:
        result = {}
        for key in ('cdi', 'awct', 'churn', 'protected_late_fraction', 'protected_p95_positive', 'protected_absolute', 'protected_signed'):
            result[key] = view.effect(lambda c: runs(c)[m][key])
        values, max_case, nofault = [], [], []
        for c in cases:
            r, pm = runs(c)[m], runs(c)[PM]
            changes = [t / pm['workflow_completion'][wf] - 1 for wf, t in r['workflow_completion'].items()]
            values.extend(changes); max_case.append(max(changes))
            nofault.extend(t / r['reference_workflow_completion'][wf] for wf, t in r['workflow_completion'].items())
        result['workflow_inflation_vs_PM'] = distribution(values)
        result['case_max_workflow_inflation_vs_PM'] = distribution(max_case)
        result['workflow_slowdown_vs_no_fault'] = distribution(nofault, 1.05)
        answer[m] = result
    return answer


def all_pairs(cases):
    return {a + '_minus_' + b: contrast(cases, a, b) for a, b in ((AL, 'B0'), (Q0, 'B0'), (BS, AL), (BS, Q0),
        (BS, PM), ('ProtectedFirst', BS), ('WorkflowGuard', BS), ('WorkflowGuard', AL), ('WorkflowGuard', Q0), ('WorkflowGuard', PM))}


def original_error_extra():
    output = OUT / 'analysis/original_error_extra.jsonl'
    if output.exists(): return read_rows(output)
    ev = Evidence(); records = []
    q0 = {r['scenario_id']: r for r in read_rows(ROOT / 'revision_r2/exploratory/Q0_error/metrics.jsonl')}
    guard = {r['scenario_id']: r for r in read_rows(ROOT / 'revision_r2/exploratory/guard_error/metrics.jsonl')}
    for case in (c for c in ev.cases if c['variant'] in ('cv0.1', 'cv0.3')):
        sid = case['scenario_id']; w, _, _ = ev.inputs(case['base_id']); ref = ev.result('ref-' + case['base_id'])
        for method in METHODS:
            if method in (Q0, 'WorkflowGuard'):
                r = (q0 if method == Q0 else guard)[sid]
                path = ROOT / ('revision_r2/exploratory/Q0_error' if method == Q0 else 'revision_r2/exploratory/guard_error') / r['event_file']
            elif method == 'ProtectedFirst':
                r = ev.priority[sid]; path = ROOT / 'revision_r1/exploratory/priority' / r['event_file']
            else:
                r = ev.raw[f'run-{sid}-{method}']; path = ROOT / 'results/g2_v2_20261025' / r['event_file']
            assert sha(path) == r['event_sha256']; run = result_from_json(read_doc(path))
            records.append({**{k: case[k] for k in ('scenario_id', 'base_id', 'root_seed', 'mix', 'nodes', 'ccr', 'failure_fraction', 'variant')},
                'method': method, 'draw': 0, 'awct': run.awct, 'cdi': mean(max(0., (dict(run.starts)[v] - dict(ref.starts)[v]) / w.pbar) for v in run.context.P),
                'churn': run.churn, **extra_metrics(run, ref, w), 'event_file': str(path.relative_to(ROOT)), 'event_sha256': sha(path)})
    output.write_text(''.join(json.dumps(r, allow_nan=False) + '\n' for r in records))
    return records


def repeated_error(rows):
    out = {}
    original_guard={r['scenario_id']:r for r in read_rows(ROOT/'revision_r2/exploratory/guard_error/metrics.jsonl')}
    for variant in ('cv0.1', 'cv0.3'):
        selected = [r for r in rows if r['variant'] == variant and r['method'] != 'reference']
        per_draw = {d: case_view([r for r in selected if r['draw'] == d]) for d in (0, 1, 2)}
        merged = {}
        for d, cases in per_draw.items():
            for c in cases:
                sid = c['scenario_id'].removesuffix(f'-draw{d}')
                if sid not in merged: merged[sid] = {**c, 'draw_runs': {}}
                merged[sid]['draw_runs'][d] = runs(c)
        cases = list(merged.values()); assert len(cases) == 60 and all(set(c['draw_runs']) == {0, 1, 2} for c in cases)
        v = View(cases); effects = {}
        for a, b in ((BS, AL), (BS, Q0), (BS, PM), ('WorkflowGuard', AL), ('WorkflowGuard', Q0), ('WorkflowGuard', BS)):
            effects[a + '_minus_' + b] = {
                'cdi': v.effect(lambda c: mean(rr[a]['cdi'] - rr[b]['cdi'] for rr in c['draw_runs'].values())),
                'relative_awct': v.effect(lambda c: mean(rr[a]['awct'] / rr[b]['awct'] - 1 for rr in c['draw_runs'].values()))}
        signs = {}
        for b in (AL, Q0, PM):
            ds = [runs(c)[BS]['cdi'] - runs(c)[b]['cdi'] for group in per_draw.values() for c in group]
            signs[b] = {'n': len(ds), 'improved': sum(x < -1e-9 for x in ds), 'worsened': sum(x > 1e-9 for x in ds), 'tied': sum(abs(x) <= 1e-9 for x in ds)}
        tails = {}
        for m in METHODS:
            wf, case_max = [], []
            for group in per_draw.values():
                for c in group:
                    rr = runs(c); dd = [t / rr[PM]['workflow_completion'][wf] - 1 for wf, t in rr[m]['workflow_completion'].items()]
                    wf.extend(dd); case_max.append(max(dd))
            tails[m] = {'workflow_inflation_vs_PM': distribution(wf), 'case_max_workflow_inflation_vs_PM': distribution(case_max)}
        attribution={'guard_feasible_cases':0,'fallback_cases':0,'violating_guard_feasible_cases':0,'violating_fallback_cases':0,
                     'violating_guard_feasible_workflows':0,'violating_fallback_workflows':0,'violating_scenario_ids':[]}
        for group in per_draw.values():
            for c in group:
                rr=runs(c);wg=rr['WorkflowGuard'];flag=wg['guard_feasible'] if 'guard_feasible' in wg else original_guard[c['scenario_id']]['guard_feasible']
                label='guard_feasible' if flag else 'fallback';attribution[label+'_cases']+=1
                violations=sum(t/rr[PM]['workflow_completion'][wf]-1>.05+1e-10 for wf,t in wg['workflow_completion'].items())
                if violations:
                    attribution['violating_'+label+'_cases']+=1;attribution['violating_'+label+'_workflows']+=violations
                    attribution['violating_scenario_ids'].append(c['scenario_id'])
        out[variant] = {'draws': 3, 'environment_roots': 10, 'distinct_condition_cells': 60, 'case_realizations': 180,
            'paired_effects_averaging_draws_within_root_cell': effects, 'signs_by_case_realization': signs, 'tails': tails,
            'guard_violation_attribution':attribution,
            'per_draw': {str(d): {'contrasts': all_pairs(g), 'summaries': summaries(g)} for d, g in per_draw.items()}}
    return out


def error_distribution():
    ev = Evidence(); result = {}
    for cv in (.1, .3):
        by_draw = {}
        for draw in (0, 1, 2):
            ratios = []; seen = set()
            for c in (c for c in ev.cases if c['variant'] == f'cv{cv:g}'):
                key = (c['root_seed'], c['mix'])
                if key in seen: continue
                seen.add(key); w, _, truth = ev.inputs(c['base_id'])
                if draw:
                    from revision_r4.common import error_work
                    path = OUT / 'exploratory/error/truth' / f'draw{draw}-{key[0]}-{key[1]}-{c["variant"]}.json'
                    truth = read_doc(path)
                    assert truth == error_work(w, *key, draw, cv)
                ratios.extend(truth[t.id] / t.work for t in w.tasks)
            a = np.array(ratios)
            by_draw[str(draw)] = {'distinct_root_mix_vectors': len(seen), 'task_multipliers': len(a), 'mean': float(a.mean()),
                'sample_CV': float(a.std(ddof=1) / a.mean()), 'p01': float(np.quantile(a, .01)), 'p05': float(np.quantile(a, .05)),
                'p50': float(np.quantile(a, .5)), 'p95': float(np.quantile(a, .95)), 'p99': float(np.quantile(a, .99)),
                'min': float(a.min()), 'max': float(a.max()), 'mean_absolute_error_from_one': float(np.mean(abs(a - 1)))}
        result[f'cv{cv:g}'] = by_draw
    return result


def cached_diagnostics():
    cases = [c for c in read_rows(ROOT / 'revision_r1/analysis/case_analysis.jsonl') if c['variant'] == 'main']
    pool = [c for c in read_rows(ROOT / 'revision_r2/analysis/pool_cases.jsonl') if c['variant'] == 'main']
    sizes = [len(c['candidates']) for c in cases]; fs = [c for c in cases if not runs(c)[BS]['quality_feasible']]
    frequencies = {m: dict(Counter(runs(c)[m]['selected_candidate'] for c in cases)) for m in (BS, PM)}
    fallback_margins = {key: dict(Counter(str(c[key]) for c in fs)) for key in ('mix', 'nodes', 'ccr', 'failure_fraction', 'root_seed')}
    timing = {}
    for m in ('B0', 'B1', 'B2', AL, Q0, 'BudgetHEFT10', BS, PM):
        values = [runs(c)[m]['full_application_seconds'] for c in cases]
        timing[m] = {k: float(np.quantile(values, q)) for k, q in [('p50', .5), ('p95', .95), ('p99', .99)]}
    subgroup = {}
    for key in ('mix', 'nodes', 'failure_fraction', 'ccr'):
        subgroup[key] = {str(x): {'BS_vs_AL': contrast([c for c in cases if c[key] == x], BS, AL),
                                  'BS_vs_Q0': contrast([c for c in cases if c[key] == x], BS, Q0)} for x in sorted({c[key] for c in cases})}
    logs = read_rows(ROOT / 'revision_r2/analysis/log_cases.jsonl'); lv = View(logs)
    components = {}
    for a, b in ((AL, 'B0'), (Q0, 'B0'), (BS, AL)):
        components[a + '_minus_' + b] = {k: lv.effect(lambda c: c['methods'][a]['cdi_components'][k] - c['methods'][b]['cdi_components'][k])
                                        for k in ('predecessor', 'input_staging', 'competition', 'HOL')}
    return {'pool_sizes': {'counts': dict(Counter(sizes)), 'mean': mean(sizes), 'median': float(np.median(sizes)), 'max': max(sizes), 'min': min(sizes)},
        'representative_selection_counts': frequencies, 'fallbacks': {'n': len(fs), 'marginals': fallback_margins, 'scenario_ids': [c['scenario_id'] for c in fs]},
        'original_application_wall_seconds': timing, 'subgroup_effects': subgroup, 'signed_component_differences': components}


def main():
    protocol = check_protocol()
    dr = read_rows(OUT / 'exploratory/dispatch/metrics.jsonl'); assert len(dr) == 23040
    dispatch = {}
    by_rule = {rule: case_view([r for r in dr if r['rule'] == rule]) for rule in ('strict', 'skip-unready')}
    for rule, cases in by_rule.items():
        assert len(cases) == 1440
        dispatch[rule] = {'cases': len(cases), 'roots': 60, 'summaries': summaries(cases), 'contrasts': all_pairs(cases)}
    strict = {c['scenario_id']: c for c in by_rule['strict']}; skip = {c['scenario_id']: c for c in by_rule['skip-unready']}
    v = View(list(strict.values())); interaction = {}
    for m in (AL, Q0, BS, 'ProtectedFirst', 'WorkflowGuard'):
        interaction[m] = v.effect(lambda c: (runs(skip[c['scenario_id']])[m]['cdi'] - runs(skip[c['scenario_id']])['B0']['cdi']) -
                                    (runs(c)[m]['cdi'] - runs(c)['B0']['cdi']))
    er = read_rows(OUT / 'exploratory/error/metrics.jsonl'); assert len(er) == 1920
    errors = repeated_error(original_error_extra() + er)
    lr = read_rows(OUT / 'exploratory/latency/metrics.jsonl'); assert len(lr) == 480
    latency = {}
    for delay in (0., .1, 1.):
        if delay == 0:
            cs = [c for c in by_rule['strict'] if c['root_seed'] < 81010 and c['nodes'] == 4 and c['failure_fraction'] == .6]
        else:
            groups = {}
            for r in (x for x in lr if x['delay_pbar'] == delay):
                sid = r['original_scenario_id']; original = strict[sid]
                if sid not in groups: groups[sid] = {**original, 'runs': []}
                groups[sid]['runs'].append(r)
            cs = list(groups.values())
        assert len(cs) == 60
        view = View(cs)
        latency[str(delay)] = {'cases': 60, 'contrasts': {a + '_minus_' + b: contrast(cs, a, b) for a, b in ((BS, AL), ('WorkflowGuard', AL), ('ProtectedFirst', BS))},
            'means': {m: {k: view.effect(lambda c: runs(c)[m][k]) for k in ('cdi', 'awct', 'protected_late_fraction')} for m in (AL, BS, 'WorkflowGuard', 'ProtectedFirst')}}
    input_paths = [OUT / 'protocol.json', OUT / 'exploratory/dispatch/metrics.jsonl', OUT / 'exploratory/error/metrics.jsonl',
                   OUT / 'exploratory/latency/metrics.jsonl', OUT / 'analysis/original_error_extra.jsonl', ROOT / 'revision_r1/analysis/case_analysis.jsonl', ROOT / 'revision_r2/analysis/log_cases.jsonl']
    result = {'status': 'PASS', 'protocol_sha256': protocol, 'new_confirmatory_samples': 0,
        'dispatch': dispatch, 'dispatch_interaction_difference_in_differences_vs_B0': interaction, 'errors': errors,
        'latency': latency, 'diagnostics': cached_diagnostics(), 'work_error_distributions': error_distribution(),
        'input_sha256': {str(p.relative_to(ROOT)): sha(p) for p in input_paths}}
    dump(OUT / 'analysis/results.json', result)
    dump(OUT/'analysis/diagnostics.json',result['diagnostics'])
    dump(OUT/'analysis/repeated_error_results.json',result['errors'])
    dump(OUT/'analysis/work_error_distributions.json',result['work_error_distributions'])
    print('R4 saved-result statistics PASS', flush=True)


if __name__ == '__main__': main()
