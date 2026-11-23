"""Reconstruct candidate workflow forecasts and offline quality-tolerance choices."""
import json
import math
import sys
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from revision_r2.common import Evidence, sha, dump, capture, BS, PM
from sail.model import Plan
from sail.simulator import Simulator, content_hash
from sail.forecast import forecast_plan
from sail.policy import bounded_scopes, OnlineReference, predicted_cdi
from sail.scheduling import schedule_scope
from research_v2.policies import budget_schedule
from v2_preparation.frozen import verify_v2

THETAS = (0., .05, .1, .2, .5, 1.)
EPSILONS = (0., .01, .02, .05, .1, .15)


def construct(snapshot, context, name, theta):
    if name.startswith('v1_H'):
        schedule = schedule_scope(snapshot, context, bounded_scopes(snapshot.workload, context)[int(name[-1])])
    elif name == 'QueueRepair0': schedule = budget_schedule(snapshot, context, 0.)
    elif name.startswith('BudgetHEFT'): schedule = budget_schedule(snapshot, context, theta)
    elif name == 'B2': schedule = schedule_scope(snapshot, context, context.Q)
    else: raise ValueError(name)
    return schedule.plan, schedule.forecast


def choose(candidates, b2_awct, epsilon=.05, workflow_reference=None):
    mean_set = [c for c in candidates if c['awct'] <= (1 + epsilon) * b2_awct]
    possible = mean_set
    if workflow_reference is not None:
        possible = [c for c in mean_set if all(c['workflow_completion'][w] <= 1.05 * t + 1e-10 for w, t in workflow_reference.items())]
    if possible:
        chosen = min(possible, key=lambda c: (c['cdi'] or 0, c['awct'], c['churn'], c['name']))
    else:
        chosen = min(candidates, key=lambda c: (c['awct'], c['cdi'] or 0, c['churn'], c['name']))
    return chosen, bool(mean_set), bool(possible)


def main(limit=None):
    verify_v2(ROOT, ROOT / 'freeze/g2_v2_20261025')
    ev = Evidence(); out = ROOT / 'revision_r2/analysis/pool_cases.jsonl'
    done = {json.loads(s)['scenario_id'] for s in out.read_text().splitlines()} if out.exists() else set()
    cases = [c for c in ev.cases if c['variant'] in ('main', 'cv0.1', 'cv0.3') or c['variant'].startswith('theta')]
    @lru_cache(maxsize=12)
    def snapshot(bid, fraction):
        c = next(c for c in cases if c['base_id'] == bid and c['failure_fraction'] == fraction)
        return capture(ev, c)
    @lru_cache(maxsize=12)
    def initial_reference(bid):
        w, p, _ = ev.inputs(bid)
        predicted = Simulator(w, p, ev.initial_plan(bid)).run()
        return OnlineReference('PREDICTED_NO_FAULT', predicted.awct, predicted.starts)
    fresh = reconstructed = reused = 0
    with out.open('a') as stream:
        for case in cases:
            sid, bid = case['scenario_id'], case['base_id']
            if sid in done: continue
            if limit is not None and fresh >= limit: break
            exact = case['variant'] not in ('cv0.1', 'cv0.3')
            known_case = ev.main.get((bid, case['failure_fraction']))
            known = {r['plan_sha256']: r for r in (case['runs'] + (known_case['runs'] if known_case is not None else []))}
            candidates = []
            for c in case['candidates']:
                item = dict(c)
                if exact and c['plan_sha256'] in known:
                    row = known[c['plan_sha256']]
                    wf = row['workflow_completion']
                    assert math.isclose(sum(wf.values()) / len(wf), c['awct'], abs_tol=1e-8)
                    assert math.isclose(row['cdi'], c['cdi'], abs_tol=1e-8)
                    item.update({'workflow_completion': wf, 'source': 'same-plan saved execution under exact work'})
                    reused += 1
                else:
                    snap, ctx = snapshot(bid, case['failure_fraction'])
                    plan, forecast = construct(snap, ctx, c['name'], case['theta'])
                    assert content_hash(plan.queues) == c['plan_sha256']
                    assert math.isclose(forecast.awct, c['awct'], abs_tol=1e-8)
                    cdi = predicted_cdi(SimpleNamespace(forecast=forecast), ctx, initial_reference(bid), snap.workload.pbar)
                    assert math.isclose(cdi, c['cdi'], abs_tol=1e-8)
                    item.update({'workflow_completion': dict(forecast.workflow_finishes), 'source': 'public-snapshot forecast'})
                    if not exact: item['queues'] = plan.queues
                    reconstructed += 1
                candidates.append(item)
            if exact:
                b2 = next(r for r in known_case['runs'] if r['method'] == 'B2')
                b2_awct, b2_wf = b2['awct'], b2['workflow_completion']
            else:
                snap, ctx = snapshot(bid, case['failure_fraction'])
                old = ev.doc(f'run-{sid}-B2')
                plan = Plan(tuple(tuple(q) for q in old['applied_plan']['queues']))
                forecast = forecast_plan(snap, plan)
                b2_awct, b2_wf = forecast.awct, dict(forecast.workflow_finishes)
            original_mean = [c for c in candidates if c['quality_feasible']]
            assert [c['name'] for c in original_mean] == [c['name'] for c in candidates if c['awct'] <= 1.05 * b2_awct]
            pool = min(original_mean or candidates, key=lambda c: (c['awct'], c['churn'], c['name']))
            target = next(r for r in case['runs'] if r['method'].startswith('PoolMinAWCT'))
            assert pool['name'] == target['selected_candidate']
            ordinary, _, _ = choose(candidates, b2_awct)
            target = next(r for r in case['runs'] if r['method'].startswith('BudgetSelect'))
            assert ordinary['name'] == target['selected_candidate']
            guard, mean_ok, guard_ok = choose(candidates, b2_awct, workflow_reference=pool['workflow_completion'])
            assert not mean_ok or guard_ok  # The same-pool reference is always admissible.
            record = {k: case[k] for k in ('scenario_id', 'base_id', 'root_seed', 'mix', 'nodes', 'ccr', 'failure_fraction', 'variant', 'theta')}
            record.update({'candidates': candidates, 'b2_awct': b2_awct, 'b2_workflow_completion': b2_wf,
                           'pool_name': pool['name'], 'pool_workflow_reference': pool['workflow_completion'],
                           'guard': {**guard, 'mean_quality_feasible': mean_ok, 'guard_feasible': guard_ok},
                           'exact_work': exact})
            stream.write(json.dumps(record, allow_nan=False) + '\n'); stream.flush(); done.add(sid); fresh += 1
            if len(done) % 60 == 0: print(f'R2 candidate workflow forecasts {len(done)}/{len(cases)}', flush=True)
    dump(ROOT / 'revision_r2/reports/pool_reconstruction_receipt.json', {'status': 'PASS' if len(done) == len(cases) else 'PARTIAL',
         'cases': len(done), 'planned': len(cases), 'candidate_forecasts_reconstructed_this_invocation': reconstructed,
         'exact_same_plan_outcomes_reused_this_invocation': reused, 'journal_sha256': sha(out), 'new_confirmatory_samples': 0})
    if len(done) == len(cases):
        with (ROOT / 'revision_r2/analysis/guard_choices.jsonl').open('w') as stream:
            for line in out.read_text().splitlines():
                c = json.loads(line)
                if not c['exact_work']:
                    stream.write(json.dumps({'scenario_id': c['scenario_id'], **c['guard']}, allow_nan=False) + '\n')


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser(); p.add_argument('--limit', type=int)
    main(p.parse_args().limit)
