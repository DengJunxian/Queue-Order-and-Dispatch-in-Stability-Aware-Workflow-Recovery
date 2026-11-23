"""R2 descriptive estimates from preserved, source-bound case records.

Bootstrap unit, cells, NA handling and draw seed are the frozen R1 rules.
No added execution becomes a new independent environment or confirmation.
"""
import json
import sys
from collections import Counter
from pathlib import Path
from statistics import mean

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from revision_r1.analyze import View, contrast, runs
from revision_r2.common import dump, sha, BS, PM, Q0, AL, BH
from revision_r2.pool_analysis import THETAS, EPSILONS, choose
from revision_r2.wait_accounting import CATEGORIES


def lines(path): return [json.loads(s) for s in (ROOT / path).read_text().splitlines()]


def merge(original, extra):
    out = {c['scenario_id']: {**c, 'runs': list(c['runs'])} for c in original}
    for r in extra:
        assert r['method'] not in runs(out[r['scenario_id']])
        out[r['scenario_id']]['runs'].append(r)
    return list(out.values())


def summarize(cases, methods):
    view = View(cases)
    return {m: {k: view.effect(lambda c, m=m, k=k: runs(c)[m][k]) for k in ('cdi', 'awct', 'churn')}
            for m in methods}


def workflow_tails(cases, target, reference):
    deltas = [[runs(c)[target]['workflow_completion'][w] / t - 1
               for w, t in runs(c)[reference]['workflow_completion'].items()] for c in cases]
    worst = [max(x) for x in deltas]
    return {'cases': len(cases), 'workflow_observations': sum(map(len, deltas)),
            'worst_workflow_p50_p95_max': np.quantile(worst, [.5, .95, 1]).tolist(),
            'cases_any_workflow_gt_5pct': sum(x > .05 + 1e-9 for x in worst),
            'case_mean_relative_workflow_completion': View(cases).effect(lambda c: mean(
                runs(c)[target]['workflow_completion'][w] / t - 1 for w, t in runs(c)[reference]['workflow_completion'].items()))}


def main():
    original = lines('revision_r1/analysis/case_analysis.jsonl')
    maincases = [c for c in original if c['variant'] == 'main']
    logs = lines('revision_r2/analysis/log_cases.jsonl')
    pools = lines('revision_r2/analysis/pool_cases.jsonl')
    assert len(maincases) == len(logs) == 1440 and len(pools) == 1860
    frozen = json.loads((ROOT / 'results/g2_v2_20261025/statistics.json').read_text())
    original_check = []
    for comp in (PM, BH):
        for label in ('overall', 'A', 'B', 'C'):
            got = contrast(maincases if label == 'overall' else [c for c in maincases if c['mix'] == label], BS, comp)
            expected = frozen['primary'][comp]['overall'] if label == 'overall' else frozen['primary'][comp]['mixes'][label]
            for metric in ('cdi', 'relative_awct'):
                for key in ('point', 'upper95'):
                    original_check.append(abs(got[metric][key] - expected[metric][key]))
                original_check.extend(abs(a-b) for a,b in zip(got[metric]['ci95'], expected[metric]['ci95']))
    assert max(original_check) < 1e-12
    result = {'purpose': 'POST_FREEZE_DESCRIPTIVE_AND_EXPLORATORY', 'new_confirmatory_samples': 0,
              'protocol_sha256': sha(ROOT / 'revision_r2/protocol.json'), 'original_primary_max_abs_difference': max(original_check),
              'inference': '5000 paired original-root bootstrap draws, seed 83000; equal defined cells within Mix then equal Mix; no topology-population inference; unadjusted exploratory intervals.'}
    methods = ('B0', AL, Q0, BS, PM, 'B2', 'ProtectedFirst')
    lv = View(logs)
    groups = list(logs[0]['group_counts'])
    result['recipients'] = {g: {'total_tasks': sum(c['group_counts'][g] for c in logs),
        'defined_cases': sum(c['group_counts'][g] > 0 for c in logs),
        'means': {m: {k: lv.effect(lambda c, m=m, k=k, g=g: c['methods'][m]['groups'][g][k])
                      for k in ('positive', 'signed', 'late_fraction')} for m in methods},
        'contrasts': {m + '_minus_' + b: lv.effect(lambda c, m=m, b=b, g=g:
                     c['methods'][m]['groups'][g]['positive'] - c['methods'][b]['groups'][g]['positive']
                     if c['group_counts'][g] else None) for m,b in ((BS,PM),(BS,AL),(BS,Q0),(AL,'B0'),(Q0,'B0'))}}
        for g in groups}
    result['waiting'] = {'interpretation': 'Signed accounting over tasks with positive start delay; components add to CDI but can be negative. Differences do not identify causal mediation.',
        'means': {m: {kind: {k: lv.effect(lambda c, m=m, k=k, kind=kind: c['methods'][m][kind][k]) for k in CATEGORIES}
                       for kind in ('cdi_components', 'signed_components', 'post_fault_wait')} for m in methods},
        'contrasts': {m + '_minus_B0': {k: lv.effect(lambda c, m=m, k=k: c['methods'][m]['cdi_components'][k] - c['methods']['B0']['cdi_components'][k])
                                      for k in CATEGORIES} for m in (AL,Q0,BS)},
        'accounting_identities': sum(c['task_wait_identities_checked'] for c in logs)}
    print('R2 recipients and waiting complete', flush=True)

    priority = lines('revision_r1/exploratory/priority/metrics.jsonl')
    strict = merge([c for c in maincases if c['root_seed'] < 81010], [r for r in priority if r['variant'] == 'main' and r['root_seed'] < 81010])
    dispatch = lines('revision_r2/exploratory/dispatch/metrics.jsonl')
    index = {c['scenario_id']: {**c, 'runs': [], 'strict': runs(c)} for c in strict}
    for r in dispatch:
        if r['kind'] != 'reference': index[r['scenario_id']]['runs'].append(r)
    wc = list(index.values())
    assert len(wc) == 240 and all(len(c['runs']) == 6 for c in wc)
    wcmethods = ('B0', AL, Q0, BS, PM, 'ProtectedFirst')
    dispatch_result = {}
    for label in ('all', '4', '8'):
        cc = wc if label == 'all' else [c for c in wc if c['nodes'] == int(label)]
        sv = [{**c, 'runs': list(c['strict'].values())} for c in cc]
        view = View(cc)
        dispatch_result[label] = {'cases': len(cc), 'root_blocks': 10, 'strict_summaries': summarize(sv, wcmethods),
            'skip_summaries': summarize(cc, wcmethods),
            'strict_contrasts': {m + '_minus_' + b: contrast(sv,m,b) for m,b in ((AL,'B0'),(Q0,'B0'),(BS,Q0),(BS,AL),(BS,PM),('ProtectedFirst',BS),('ProtectedFirst',PM))},
            'skip_contrasts': {m + '_minus_' + b: contrast(cc,m,b) for m,b in ((AL,'B0'),(Q0,'B0'),(BS,Q0),(BS,AL),(BS,PM),('ProtectedFirst',BS),('ProtectedFirst',PM))},
            'change_in_CDI_contrast': {m + '_minus_B0': view.effect(lambda c, m=m:
                (runs(c)[m]['cdi'] - runs(c)['B0']['cdi']) - (c['strict'][m]['cdi'] - c['strict']['B0']['cdi'])) for m in (AL,Q0,BS)},
            'skip_minus_strict_CDI': {m: view.effect(lambda c, m=m: runs(c)[m]['cdi'] - c['strict'][m]['cdi']) for m in wcmethods}}
    result['dispatch'] = dispatch_result
    print('R2 dispatch comparisons complete', flush=True)

    errors = merge([c for c in original if c['variant'] in ('cv0.1','cv0.3')],
                   lines('revision_r2/exploratory/Q0_error/metrics.jsonl') + lines('revision_r2/exploratory/guard_error/metrics.jsonl'))
    result['error_controls'] = {}
    for variant in ('cv0.1','cv0.3'):
        cc = [c for c in errors if c['variant'] == variant]
        result['error_controls'][variant] = {'cases': len(cc), 'root_blocks': 10,
            'summaries': summarize(cc,(AL,Q0,BS,PM,'WorkflowGuard')),
            'contrasts': {m + '_minus_' + b: contrast(cc,m,b) for m,b in ((BS,Q0),(BS,AL),('WorkflowGuard',BS),('WorkflowGuard',PM),('WorkflowGuard',Q0),('WorkflowGuard',AL))},
            'guard_vs_pool_workflow_tails': workflow_tails(cc,'WorkflowGuard',PM),
            'predicted_guard_infeasible': sum(not runs(c)['WorkflowGuard']['guard_feasible'] for c in cc)}

    mainpool = [c for c in pools if c['variant'] == 'main']
    guardcases = merge(maincases,[{'scenario_id': c['scenario_id'], 'method': 'WorkflowGuard',
         **{k: c['guard'][k] for k in ('cdi','awct','churn','workflow_completion')}} for c in mainpool])
    result['workflow_guard'] = {'scope': 'Offline exact-work choices, not new environment samples',
        'changed_plan_cases': sum(c['guard']['plan_sha256'] != runs(o)[BS]['plan_sha256'] for c,o in zip(mainpool,maincases)),
        'fallbacks': sum(not c['guard']['mean_quality_feasible'] for c in mainpool),
        'guard_feasible_cases': sum(c['guard']['guard_feasible'] for c in mainpool),
        'summaries': summarize(guardcases,('WorkflowGuard',BS,PM)),
        'contrasts': {b: contrast(guardcases,'WorkflowGuard',b) for b in (BS,PM,Q0,AL)},
        'guard_vs_pool_workflow_tails': workflow_tails(guardcases,'WorkflowGuard',PM),
        'original_vs_pool_workflow_tails': workflow_tails(guardcases,BS,PM)}

    frontier = []
    for theta in THETAS:
        cc = [c for c in pools if c['theta'] == theta and c['root_seed'] < 81010 and c['nodes'] == 4 and c['failure_fraction'] == .6 and c['exact_work']]
        assert len(cc) == 60, (theta,len(cc))
        for epsilon in EPSILONS:
            choices = {c['scenario_id']: choose(c['candidates'],c['b2_awct'],epsilon) for c in cc}
            view = View(cc)
            def selected(c): return choices[c['scenario_id']][0]
            frontier.append({'theta':theta,'epsilon':epsilon,'cases':60,'root_blocks':10,
                'cdi': view.effect(lambda c: selected(c)['cdi']), 'awct':view.effect(lambda c: selected(c)['awct']),
                'paired_relative_awct_vs_B2': view.effect(lambda c: selected(c)['awct']/c['b2_awct']-1),
                'churn':view.effect(lambda c: selected(c)['churn']),
                'fallbacks':sum(not choices[c['scenario_id']][1] for c in cc),
                'selected_candidates':dict(Counter(selected(c)['name'] for c in cc))})
    result['budget_tolerance_grid'] = frontier
    print('R2 error, guard and grid complete', flush=True)

    scale = lines('revision_r1/exploratory/scale/metrics.jsonl')
    capcases = [{**c, 'capacity_fraction_lost': next(x['capacity_fraction_lost'] for x in logs if x['scenario_id'] == c['scenario_id'])}
                for c in maincases if c['root_seed'] < 81010]
    si = {}
    for r in scale:
        if r['kind'] == 'reference' or r['variant'] != 'main': continue
        sid = r['scenario_id']
        if sid not in si: si[sid] = {**{k:r[k] for k in ('scenario_id','root_seed','mix','nodes','ccr','failure_fraction','capacity_fraction_lost')},'runs':[]}
        si[sid]['runs'].append(r)
    capcases += list(si.values())
    assert len(capcases) == 480
    bins = [('lt10pct',0,.1),('10to20pct',.1,.2),('ge20pct',.2,2)]
    result['capacity_loss_strata'] = {}
    for label,lo,hi in bins:
        cc = [c for c in capcases if lo <= c['capacity_fraction_lost'] < hi]
        result['capacity_loss_strata'][label] = {'cases':len(cc),'nodes':dict(Counter(c['nodes'] for c in cc)),
            'fraction_lost_range':[min(c['capacity_fraction_lost'] for c in cc),max(c['capacity_fraction_lost'] for c in cc)],
            'contrasts':{b:contrast(cc,BS,b,range(81000,81010)) for b in (Q0,AL,PM)}}

    worst = max(((runs(c)[BS]['workflow_completion'][w]/t-1,c,w) for c in guardcases for w,t in runs(c)[PM]['workflow_completion'].items()),key=lambda t:t[0])
    relative,c,wf = worst
    result['largest_workflow_cost'] = {'scenario_id':c['scenario_id'],'workflow':wf,'relative_completion_vs_pool':relative,
        'case':{k:c[k] for k in ('base_id','root_seed','mix','nodes','ccr','failure_fraction','F_count','P_count')},
        'methods':{m:{'cdi':runs(c)[m]['cdi'],'awct':runs(c)[m]['awct'],'workflow_completion':runs(c)[m]['workflow_completion']} for m in ('B0',AL,Q0,BS,PM,'B2','WorkflowGuard')},
        'selected_candidate':runs(c)[BS]['selected_candidate']}
    result['new_execution_receipts'] = {part:json.loads((ROOT/f'revision_r2/exploratory/{part}/summary.json').read_text())
                                       for part in ('dispatch','Q0_error','guard_error','offline_validation')}
    assert all(x['status']=='PASS' for x in result['new_execution_receipts'].values())
    result['new_physical_executions'] = sum(x['executions'] for x in result['new_execution_receipts'].values())
    result['new_audited_events'] = sum(x['events_checked'] for x in result['new_execution_receipts'].values())
    assert result['new_physical_executions'] == 1940
    sources = ('revision_r1/analysis/case_analysis.jsonl','revision_r1/exploratory/priority/metrics.jsonl','revision_r1/exploratory/scale/metrics.jsonl',
               'revision_r2/analysis/log_cases.jsonl','revision_r2/analysis/pool_cases.jsonl')
    result['input_sha256'] = {p:sha(ROOT/p) for p in sources}
    dump(ROOT/'revision_r2/analysis/results.json',result)
    print(json.dumps({'status':'PASS','original_primary_max_abs_difference':max(original_check),'executions':1940,'events':result['new_audited_events']}))


if __name__ == '__main__': main()
