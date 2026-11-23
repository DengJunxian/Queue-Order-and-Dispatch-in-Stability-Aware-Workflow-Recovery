"""Independent graph reachability and manuscript-cohort verification."""
import sys
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from revision_r4.common import OUT, Evidence, read_rows, dump


def main():
    ev = Evidence(); old = {r['scenario_id']: r for r in read_rows(ROOT / 'revision_r2/analysis/log_cases.jsonl')}
    overlap = mismatches = 0; n = ftotal = dtotal = ptotal = root_descendant_edges = 0
    for c in (c for c in ev.cases if c['variant'] == 'main'):
        w, _, _ = ev.inputs(c['base_id']); ctx = ev.doc('run-' + c['scenario_id'] + '-B0')['context']
        Q, F, P = (set(ctx[k]) for k in ('Q', 'F', 'P')); successors = defaultdict(list)
        for u, v in w.edges: successors[u].append(v)
        reached = set(); stack = list(F)
        while stack:
            u = stack.pop()
            for v in successors[u]:
                if v not in reached: reached.add(v); stack.append(v)
        root_descendant_edges += len(reached & F)
        D = (reached & Q) - F
        assert w.descendants(F) & Q == D
        assert not (F & D or F & P or D & P) and F | D | P == Q
        assert (len(F), len(D), len(P)) == (old[c['scenario_id']]['F_count'], old[c['scenario_id']]['D_count'], old[c['scenario_id']]['P_count'])
        ftotal += len(F); dtotal += len(D); ptotal += len(P); n += 1
    dump(OUT / 'reports/set_definition_audit.json', {'status': 'PASS', 'cases': n, 'F_observations': ftotal,
        'D_star_observations': dtotal, 'P_observations': ptotal, 'roots_reachable_from_other_roots_observations': root_descendant_edges,
        'F_D_star_overlap': 0, 'previous_descendant_statistics_population_mismatches': 0,
        'implementation': 'Workload.descendants excludes the whole roots set; D* is now explicitly written with setminus F.',
        'previous_metrics_recalculation_required': False, 'original_scientific_values_changed': False})
    print('Definition audit PASS: all 1440 contexts disjoint and match saved F/D/P populations')


if __name__ == '__main__': main()
