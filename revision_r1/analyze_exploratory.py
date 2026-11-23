"""Summarize separate post-freeze runs and matched original capacity views."""
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from revision_r1.analyze import View, BS, PM, BH, Q0, LOCK, contrast
from revision_r1.io import dump


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def load(part, compact=False):
    folder = ROOT / 'revision_r1/exploratory' / part
    summary = json.loads((folder / 'summary.json').read_text())
    assert summary['status'] == 'PASS'
    rows = [json.loads(s) for s in (folder / 'metrics.jsonl').read_text().splitlines()]
    assert len(rows) == summary['planned'] and len({r['job_id'] for r in rows}) == len(rows)
    events = 0
    for r in rows:
        assert r['status'] == 'COMPLETE'
        if not compact:
            assert sha(folder / r['event_file']) == r['event_sha256']
        events += r['events_checked']
    return rows, {'labels': len(rows), 'events_checked': events, 'journal_sha256': sha(folder / 'metrics.jsonl'),
                  'references': sum(r['kind'] == 'reference' for r in rows), 'event_hashes_verified': 0 if compact else len(rows)}


def merged_cases(cases, extra):
    indexed = {c['scenario_id']: {**c, 'runs': list(c['runs'])} for c in cases}
    for r in extra:
        c = indexed[r['scenario_id']]
        assert all(s['method'] != r['method'] for s in c['runs'])
        assert r['F_count'] == c['F_count']
        c['runs'].append(r)
    return list(indexed.values())


def summaries(cases):
    groups = defaultdict(list)
    for c in cases:
        for r in c['runs']:
            groups[r['method']].append(r)
    out = {}
    for method, rows in groups.items():
        applications = [r['full_application_seconds'] for r in rows if r['full_application_seconds'] is not None]
        out[method] = {'n': len(rows), 'mean_awct': mean(r['awct'] for r in rows),
                       'mean_cdi': mean(r['cdi'] for r in rows if r['cdi'] is not None) if any(r['cdi'] is not None for r in rows) else None,
                       'cdi_undefined': sum(r['cdi'] is None for r in rows), 'mean_churn': mean(r['churn'] for r in rows),
                       'application_p50_p95_seconds': [float(x) for x in np.quantile(applications, [.5, .95])] if applications else None}
    return out


def main(compact=False):
    if not compact:
        from v2_preparation.frozen import verify_v2
        verify_v2(ROOT, ROOT / 'freeze/g2_v2_20261025')
    original = [json.loads(s) for s in (ROOT / 'revision_r1/analysis/case_analysis.jsonl').read_text().splitlines()]
    assert len(original) == 1920
    priority, pr = load('priority', compact)
    scale, sr = load('scale', compact)
    fixed_cases = merged_cases([c for c in original if c['variant'] in ('main', 'cv0.1', 'cv0.3', 'control_delay')], priority)
    new_cases = {}
    for row in scale:
        if row['kind'] == 'reference': continue
        sid = row['scenario_id']
        if sid not in new_cases:
            new_cases[sid] = {k: row[k] for k in ('scenario_id', 'root_seed', 'mix', 'nodes', 'ccr', 'failure_fraction', 'variant')}
            new_cases[sid].update({'runs': [], 'F_count': row['F_count']})
        new_cases[sid]['runs'].append(row)
    assert len(new_cases) == 360
    pf = {}
    for variant in ('main', 'cv0.1', 'cv0.3', 'control_delay'):
        view = [c for c in fixed_cases if c['variant'] == variant]
        pf[variant] = {'summary': summaries(view)['ProtectedFirst'], 'BS_minus_ProtectedFirst': contrast(view, BS, 'ProtectedFirst'),
                       'ProtectedFirst_minus_B0': contrast(view, 'ProtectedFirst', 'B0'),
                       'ProtectedFirst_minus_B2': contrast(view, 'ProtectedFirst', 'B2'),
                       'actual_AWCT_above_1_05_B2': sum(next(r for r in c['runs'] if r['method'] == 'ProtectedFirst')['awct'] >
                                                      1.05 * next(r for r in c['runs'] if r['method'] == 'B2')['awct'] for c in view)}
    scale_results = {}
    for variant in ('main', 'cv0.3'):
        allcases = [c for c in fixed_cases if c['variant'] == variant and c['root_seed'] < 81010]
        allcases += [c for c in new_cases.values() if c['variant'] == variant]
        scale_results[variant] = {}
        for nodes in sorted({c['nodes'] for c in allcases}):
            view = [c for c in allcases if c['nodes'] == nodes]
            present = set.intersection(*(set(r['method'] for r in c['runs']) for c in view))
            effects = {b: contrast(view, BS, b) for b in (PM, BH, 'B2', Q0, LOCK, 'ProtectedFirst') if b in present}
            scale_results[variant][str(nodes)] = {'cases': len(view), 'root_blocks': len({c['root_seed'] for c in view}),
                                                  'F_empty': sum(c['F_count'] == 0 for c in view),
                                                  'summaries': summaries(view), 'contrasts': effects}
    result = {'purpose': 'POST_FREEZE_EXPLORATORY_NOT_CONFIRMATORY', 'new_confirmatory_samples': 0,
              'receipts': {'priority': pr, 'scale': sr}, 'physical_executions': pr['labels'] + sr['labels'],
              'priority_control': pf, 'capacity_exploration': scale_results,
              'timing_caveat': 'New timings were collected during concurrent local processes; do not compare their speed with original isolated-run timings.',
              'inference': 'Ten fixed original roots and the same six topology groups; unadjusted root-block intervals. No optional-stopping or new confirmation.'}
    if compact:
        result['compact_recomputation_scope'] = 'Saved structured metrics only; no event-constraint or frozen-source verification.'
    dump(ROOT / ('revision_r1/analysis/exploratory_recalculation_compact.json' if compact else 'revision_r1/analysis/exploratory_results.json'), result)
    print(json.dumps({'status': 'PASS', 'physical_executions': result['physical_executions'], 'references': pr['references'] + sr['references']}))


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser(); p.add_argument('--compact', action='store_true')
    main(p.parse_args().compact)
