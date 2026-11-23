"""Recipient populations, pending failure-cone delays and exact wait accounting."""
import json
import math
import sys
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from revision_r2.common import Evidence, sha, dump, BS, PM, Q0, AL
from revision_r2.wait_accounting import wait_components, CATEGORIES
from v2_preparation.frozen import verify_v2


def main(limit=None):
    verify_v2(ROOT, ROOT / 'freeze/g2_v2_20261025')
    ev = Evidence(); output = ROOT / 'revision_r2/analysis/log_cases.jsonl'
    done = {json.loads(s)['scenario_id'] for s in output.read_text().splitlines()} if output.exists() else set()
    cases = [c for c in ev.cases if c['variant'] == 'main']; fresh = events = identities = 0
    with output.open('a') as stream:
        for case in cases:
            sid, bid = case['scenario_id'], case['base_id']
            if sid in done: continue
            if limit is not None and fresh >= limit: break
            w, platform, _ = ev.inputs(bid); fault = ev.failure(case)
            ref = ev.doc('ref-' + bid); s0 = dict(ref['starts']); pbar = w.pbar
            b0 = ev.doc(f'run-{sid}-B0'); ctx = b0['context']
            P, F, Q = (set(ctx[k]) for k in ('P', 'F', 'Q'))
            D = set(w.descendants(F)) & Q
            affected = {w.task_map[v].workflow for v in F}
            groups = {'protected_all': P, 'protected_affected': {v for v in P if w.task_map[v].workflow in affected},
                      'protected_unaffected': {v for v in P if w.task_map[v].workflow not in affected},
                      'mandatory': F, 'descendants': D, 'fault_cone': F | D, 'all_pending': Q}
            assert (F | D) == Q - P and not F & D
            base_wait = wait_components(ref, w, fault.time, P)
            rows = {}
            for method in ('B0', AL, Q0, BS, PM, 'B2', 'ProtectedFirst'):
                if method == 'ProtectedFirst':
                    r = ev.priority[sid]; path = ROOT / 'revision_r1/exploratory/priority' / r['event_file']
                    assert sha(path) == r['event_sha256']; doc = json.loads(path.read_text())
                else: doc = ev.doc(f'run-{sid}-{method}')
                assert doc['context'] == ctx
                starts = dict(doc['starts']); events += len(doc['events'])
                metrics = {}
                for name, population in groups.items():
                    differences = [(starts[v] - s0[v]) / pbar for v in population]
                    metrics[name] = {'count': len(population), 'positive': mean(max(0., x) for x in differences) if differences else None,
                                     'signed': mean(differences) if differences else None,
                                     'late_fraction': mean(x > 1e-9 for x in differences) if differences else None}
                waits = wait_components(doc, w, fault.time, P)
                components = {k: mean((waits[v][k] - base_wait[v][k]) * (starts[v] > s0[v]) for v in P) / pbar for k in CATEGORIES}
                signed = {k: mean(waits[v][k] - base_wait[v][k] for v in P) / pbar for k in CATEGORIES}
                assert math.isclose(sum(components.values()), metrics['protected_all']['positive'], abs_tol=1e-8)
                assert math.isclose(sum(signed.values()), metrics['protected_all']['signed'], abs_tol=1e-8)
                identities += 2 * len(P)
                rows[method] = {'groups': metrics, 'cdi_components': components, 'signed_components': signed,
                                'post_fault_wait': {k: mean(waits[v][k] for v in P) / pbar for k in CATEGORIES},
                                'awct': doc['awct'], 'cdi': metrics['protected_all']['positive']}
            record = {k: case[k] for k in ('scenario_id', 'base_id', 'root_seed', 'mix', 'nodes', 'ccr', 'failure_fraction')}
            record.update({'variant': 'main', 'P_count': len(P), 'F_count': len(F), 'D_count': len(D),
                           'group_counts': {k: len(v) for k, v in groups.items()},
                           'capacity_fraction_lost': platform.speeds[fault.node] / sum(platform.speeds), 'methods': rows,
                           'task_wait_identities_checked': 2 * len(P) * len(rows), 'event_records_read': events})
            # Counts above are per invocation for receipt only; case data retain local identities.
            stream.write(json.dumps(record, allow_nan=False) + '\n'); stream.flush(); fresh += 1; done.add(sid)
            if len(done) % 60 == 0: print(f'R2 log accounting {len(done)}/{len(cases)}', flush=True)
    dump(ROOT / 'revision_r2/reports/log_accounting_receipt.json', {'status': 'PASS' if len(done) == 1440 else 'PARTIAL',
         'cases': len(done), 'fresh_cases': fresh, 'event_records_read_this_invocation': events,
         'task_wait_identities_checked_this_invocation': identities, 'journal_sha256': sha(output), 'new_confirmatory_samples': 0,
         'interpretation': 'Additive signed waiting-category accounting. Positive-CDI components are conditional on delayed tasks and may be negative; not a causal mediation estimate.'})


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser(); p.add_argument('--limit', type=int)
    main(p.parse_args().limit)
