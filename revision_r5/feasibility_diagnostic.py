"""Post-hoc PS threshold membership; does not create or optimize a selector."""
import json
from collections import Counter

from revision_r5.run_control import OUT, ROOT, read, dump, sha


def main():
    specification = OUT / 'feasibility_diagnostic_protocol.json'
    assert read(specification)['classification'] == 'POST_HOC_DESCRIPTIVE_DIAGNOSTIC'
    ps = [json.loads(s) for s in (OUT / 'metrics.jsonl').read_text().splitlines()]
    ps = [r for r in ps if r['rule'] == 'strict']
    assert len(ps) == 1440
    original = [json.loads(s) for s in (ROOT / 'revision_r1/analysis/case_analysis.jsonl').read_text().splitlines()]
    cases = {c['scenario_id']: c for c in original if c['variant'] == 'main'}
    old_dispatch = [json.loads(s) for s in (ROOT / 'revision_r4/exploratory/dispatch/metrics.jsonl').read_text().splitlines()]
    pm = {r['scenario_id']: r for r in old_dispatch if r['rule'] == 'strict' and r['method'] == 'PoolMinAWCT10'}
    rows = []
    for p in ps:
        c = cases[p['scenario_id']]
        rr = {r['method']: r for r in c['runs']}
        b2 = rr['B2']['awct']
        mean = p['awct'] <= 1.05 * b2 + 1e-10
        ratios = {wf: t / pm[p['scenario_id']]['workflow_completion'][wf] for wf, t in p['workflow_completion'].items()}
        wf_guard = all(x <= 1.05 + 1e-10 for x in ratios.values())
        rows.append({'scenario_id': p['scenario_id'], 'mean_filter_pass': mean, 'workflow_filter_pass': wf_guard,
                     'both_pass': mean and wf_guard, 'PS_AWCT_over_B2': p['awct'] / b2,
                     'PS_workflow_completion_over_PM': ratios,
                     'original_quality_set_nonempty': rr['BudgetSelect10']['quality_feasible']})
    def summarize(group):
        return {'cases': len(group), **{k: sum(r[k] for r in group) for k in ('mean_filter_pass', 'workflow_filter_pass', 'both_pass')}}
    result = {'status': 'PASS', 'classification': 'POST_HOC_DESCRIPTIVE_DIAGNOSTIC', 'new_executions': 0,
              'original_candidate_pools_changed': False, 'overall': summarize(rows),
              'by_original_quality_set': {str(flag): summarize([r for r in rows if r['original_quality_set_nonempty'] == flag]) for flag in (False, True)},
              'case_ids_passing_both': [r['scenario_id'] for r in rows if r['both_pass']],
              'protocol_sha256': sha(specification),
              'input_sha256': {str(p.relative_to(ROOT)): sha(p) for p in (OUT / 'metrics.jsonl', ROOT / 'revision_r1/analysis/case_analysis.jsonl', ROOT / 'revision_r4/exploratory/dispatch/metrics.jsonl')},
              'records': rows}
    dump(OUT / 'analysis/feasibility_diagnostic.json', result)
    print(json.dumps({k: v for k, v in result.items() if k not in ('records', 'case_ids_passing_both', 'input_sha256')}))


if __name__ == '__main__': main()
