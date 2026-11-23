"""Read immutable event files; reconstruct public forecasts without changing policies."""
import hashlib
import json
import math
import sys
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sail.development import dump
from sail.experiment import workload_from_json
from sail.model import Failure, Platform
from sail.scheduling import initial_heft
from sail.policy import OnlineReference
from sail.simulator import Simulator, content_hash
from research_v2.policies import BudgetSelect
from v2_preparation.frozen import verify_v2

OUT = ROOT / 'revision_r1/analysis'
FROZEN = ROOT / 'freeze/g2_v2_20261025'
RUNS = ROOT / 'results/g2_v2_20261025'


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


class SnapshotReady(Exception):
    pass


class Capture(Simulator):
    def _apply(self):
        self.public_snapshot, self.original_context = self.snapshot(), self._context
        raise SnapshotReady


def main(limit=None):
    _, manifest = verify_v2(ROOT, FROZEN)
    raw = [json.loads(s) for s in (RUNS / 'metrics.jsonl').read_text().splitlines()]
    indexed = {r['job_id']: r for r in raw}
    jobs = defaultdict(list)
    for j in manifest['jobs']:
        if j['kind'] == 'failure':
            jobs[j['scenario_id']].append(j)
    bases = {b['id']: b for b in manifest['bases']}
    OUT.mkdir(exist_ok=True)
    journal = OUT / 'case_analysis.jsonl'
    completed = {}
    if journal.exists():
        for line in journal.read_text().splitlines():
            d = json.loads(line)
            assert d['scenario_id'] not in completed
            completed[d['scenario_id']] = d
    hashes = {}
    event_records = 0
    @lru_cache(maxsize=12)
    def event(job_id):
        nonlocal event_records
        row = indexed[job_id]
        p = RUNS / row['event_file']
        data = p.read_bytes()
        observed = hashlib.sha256(data).hexdigest()
        assert observed == row['event_sha256'], row['event_file']
        doc = json.loads(data)
        if row['event_file'] not in hashes:
            hashes[row['event_file']] = observed
            event_records += len(doc['events'])
        return doc
    @lru_cache(maxsize=12)
    def inputs(bid):
        b = bases[bid]
        w = workload_from_json(json.loads((FROZEN / b['workload_file']).read_text()))
        p = Platform(tuple(b['speeds']), b['bandwidth'])
        truth = json.loads((FROZEN / b['truth_file']).read_text())
        initial = initial_heft(w, p)
        return w, p, truth, initial
    @lru_cache(maxsize=96)
    def captured(bid, fraction, control_delay):
        w, p, truth, initial = inputs(bid)
        reference = event('ref-' + bid)
        scenario = next(s for s in manifest['scenarios'] if s['base_id'] == bid and s['failure_fraction'] == fraction and s['control_delay_pbar_units'] == control_delay)
        failure = Failure(reference['makespan'] * fraction, scenario['failed_node'], control_delay * w.pbar)
        engine = Capture(w, p, initial.plan, realized_work=truth, failure=failure, repair=lambda *_: None)
        try:
            engine.run()
        except SnapshotReady:
            pass
        return engine.public_snapshot, engine.original_context
    fresh = 0
    with journal.open('a') as stream:
        for scenario in manifest['scenarios']:
            sid = scenario['id']
            if sid in completed:
                continue
            if limit is not None and fresh >= limit:
                break
            bid = scenario['base_id']
            w, p, truth, initial = inputs(bid)
            ref = event('ref-' + bid)
            ref_starts, ref_finishes = dict(ref['starts']), dict(ref['workflow_finishes'])
            bjid = jobs[sid][0]['reference_b0_job']
            b0 = event(bjid)
            b0starts = dict(b0['starts'])
            ctx = b0['context']
            F, P = set(ctx['F']), set(ctx['P'])
            workflows = sorted(ref_finishes)
            f_by_w = {wf: sum(v in F for v, t in w.task_map.items() if t.workflow == wf) for wf in workflows}
            p_by_w = {wf: [v for v in P if w.task_map[v].workflow == wf] for wf in workflows}
            affected = [wf for wf in workflows if f_by_w[wf] > 0]
            derived = []
            for job in jobs[sid]:
                r, doc = indexed[job['id']], event(job['id'])
                assert doc['context'] == ctx
                starts = dict(doc['starts'])
                cdis = {wf: mean(max(0, starts[v] - ref_starts[v]) / w.pbar for v in ids) if ids else None
                        for wf, ids in p_by_w.items()}
                cdi = mean(max(0, starts[v] - ref_starts[v]) / w.pbar for v in P) if P else None
                assert cdi is None if r['cdi'] is None else math.isclose(cdi, r['cdi'], abs_tol=1e-9)
                difference = [(starts[v] - b0starts[v]) / w.pbar for v in P]
                d = {k: r[k] for k in ('job_id', 'method', 'root_seed', 'mix', 'nodes', 'ccr', 'failure_fraction', 'variant', 'awct', 'cdi', 'churn', 'quality_feasible', 'selected_candidate', 'full_application_seconds', 'protected_count', 'status')}
                d.update({'workflow_cdi': cdis, 'equal_workflow_cdi': mean(v for v in cdis.values() if v is not None) if P else None,
                          'workflow_completion': dict(doc['workflow_finishes']),
                          'workflow_stretch': {wf: t / ref_finishes[wf] for wf, t in doc['workflow_finishes']},
                          'plan_sha256': content_hash(tuple(tuple(q) for q in doc['applied_plan']['queues'])),
                          'F_count': len(F), 'P_by_workflow': {wf: len(v) for wf, v in p_by_w.items()},
                          'F_by_workflow': f_by_w, 'affected_workflows': affected,
                          'same_fault_signed_delay': mean(difference) if P else None,
                          'mean_advance_vs_b0': mean(min(0, x) for x in difference) if P else None,
                          'mean_added_delay_vs_b0': mean(max(0, x) for x in difference) if P else None,
                          'advance_fraction_vs_b0': sum(x < -1e-9 for x in difference) / len(P) if P else None,
                          'delay_fraction_vs_b0': sum(x > 1e-9 for x in difference) / len(P) if P else None})
                if r['same_fault_signed_delay'] is not None:
                    assert math.isclose(d['same_fault_signed_delay'], r['same_fault_signed_delay'], abs_tol=1e-9)
                derived.append(d)
            snapshot, context = captured(bid, scenario['failure_fraction'], scenario['control_delay_pbar_units'])
            assert content_hash(context) == indexed[jobs[sid][0]['id']]['context_sha256']
            theta = jobs[sid][0].get('budget_theta', .1)
            policy = BudgetSelect(OnlineReference.from_initial(initial), theta)
            policy(snapshot, context)
            candidates = [{k: c[k] for k in ('name', 'awct', 'cdi', 'churn', 'quality_feasible')} |
                          {'plan_sha256': content_hash(c['plan'].queues)} for c in policy.last_candidates]
            feasible = [c for c in candidates if c['quality_feasible']]
            pool = min(feasible or candidates, key=lambda c: (c['awct'], c['churn'], c['name'], c['plan_sha256']))
            # Names are unique after deduplication, so the queue tie is never reached after name.
            target = next(r for r in derived if r['method'].startswith('BudgetSelect'))
            pm = next(r for r in derived if r['method'].startswith('PoolMinAWCT'))
            selected = next(c for c in candidates if c['name'] == policy.last_selected['name'])
            assert selected['name'] == target['selected_candidate']
            assert selected['plan_sha256'] == target['plan_sha256']
            assert pool['name'] == pm['selected_candidate'] and pool['plan_sha256'] == pm['plan_sha256']
            assert bool(feasible) == target['quality_feasible'] == pm['quality_feasible']
            predicted = {'BudgetSelect': selected, 'PoolMinAWCT': pool}
            for label, row in [('BudgetSelect', target), ('PoolMinAWCT', pm)]:
                row['predicted_cdi'] = predicted[label]['cdi']
                row['predicted_awct'] = predicted[label]['awct']
            bh = next(r for r in derived if r['method'].startswith('BudgetHEFT'))
            bh_candidate = next(c for c in candidates if c['plan_sha256'] == bh['plan_sha256'])
            record = {'scenario_id': sid, 'base_id': bid, 'variant': scenario['variant'],
                      'root_seed': scenario['root_seed'], 'mix': scenario['mix'], 'nodes': scenario['nodes'],
                      'ccr': scenario['ccr'], 'failure_fraction': scenario['failure_fraction'], 'theta': theta,
                      'Q_count': len(context.Q), 'F_count': len(F), 'P_count': len(P),
                      'affected_workflows': affected, 'P_in_affected_workflows': sum(len(p_by_w[wf]) for wf in affected),
                      'budgetheft_quality_feasible': bh_candidate['quality_feasible'],
                      'quality_feasible_count': len(feasible), 'candidates': candidates, 'runs': derived,
                      'pool_cdi_floor': min(c['cdi'] for c in candidates if c['cdi'] is not None) if P else None,
                      'scope': 'POST_FREEZE_DESCRIPTIVE; existing outcomes and public forecast reconstruction'}
            stream.write(json.dumps(record, allow_nan=False) + '\n')
            stream.flush()
            completed[sid] = record
            fresh += 1
            if len(completed) % 30 == 0:
                dump(ROOT / 'revision_r1/reports/analysis_progress.json', {'completed_scenarios': len(completed), 'total': len(manifest['scenarios']), 'status': 'RUNNING'})
                print(f'R1 descriptive cases {len(completed)}/{len(manifest["scenarios"])}', flush=True)
    dump(ROOT / 'revision_r1/reports/extraction_receipt.json', {
        'status': 'PASS' if len(completed) == len(manifest['scenarios']) else 'PARTIAL',
        'cases': len(completed), 'fresh_cases_this_invocation': fresh,
        'physical_event_files_hashed_this_invocation': len(hashes), 'event_records_read_this_invocation': event_records,
        'journal_sha256': sha(journal), 'new_confirmatory_samples': 0,
        'note': 'Saved-log metric derivation plus public snapshot/forecast reconstruction; not a repeat of the full independent constraint audit.'})
    dump(ROOT / 'revision_r1/reports/analysis_progress.json', {'completed_scenarios': len(completed), 'total': len(manifest['scenarios']),
                                                           'status': 'COMPLETE' if len(completed) == len(manifest['scenarios']) else 'PARTIAL'})


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser(); p.add_argument('--limit', type=int)
    main(p.parse_args().limit)
