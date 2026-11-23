import gzip
import hashlib
import json
import math
from pathlib import Path
from statistics import mean

import numpy as np

from revision_r2.common import ROOT, Evidence, sha, dump, BS, PM, Q0, AL, capture
from revision_r2.pool_analysis import construct
from research_v2.policies import BudgetSelect
from revision_r1.policies import ProtectedFirst
from sail.forecast import forecast_plan
from sail.model import Plan, RepairDecision
from sail.policy import OnlineReference
from sail.simulator import Simulator, jsonable
from v2_preparation.experiment import make_method

METHODS = ('B0', AL, Q0, BS, PM, 'ProtectedFirst', 'WorkflowGuard')
OUT = ROOT / 'revision_r4'


def read_doc(path):
    path = Path(path)
    return json.loads(gzip.decompress(path.read_bytes()) if path.suffix == '.gz' else path.read_bytes())


def save_doc(path, result):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(jsonable(result), separators=(',', ':'), allow_nan=False).encode()
    path.write_bytes(gzip.compress(raw, mtime=0))


def read_rows(path):
    p = Path(path)
    return [json.loads(s) for s in p.read_text().splitlines()] if p.exists() else []


def extra_metrics(run, reference, workload):
    s, s0 = dict(run.starts), dict(reference.starts)
    ds = [(s[v] - s0[v]) / workload.pbar for v in sorted(run.context.P)]
    pos = [max(0., x) for x in ds]
    return {'workflow_completion': dict(run.workflow_finishes),
            'reference_workflow_completion': dict(reference.workflow_finishes),
            'protected_late_fraction': mean(x > 1e-9 / workload.pbar for x in ds) if ds else None,
            'protected_signed': mean(ds) if ds else None,
            'protected_absolute': mean(abs(x) for x in ds) if ds else None,
            'protected_p95_positive': float(np.quantile(pos, .95)) if ds else None,
            'F_count': len(run.context.F), 'Q_count': len(run.context.Q)}


class WorkflowGuard(BudgetSelect):
    def __call__(self, snapshot, context):
        super().__call__(snapshot, context)
        quality = [c for c in self.last_candidates if c['quality_feasible']]
        pm = min(quality or self.last_candidates, key=lambda c: (c['awct'], c['churn'], c['name'], c['plan'].queues))
        self.workflow_reference = dict(forecast_plan(snapshot, pm['plan']).workflow_finishes)
        candidates = []
        for c in quality:
            times = dict(forecast_plan(snapshot, c['plan']).workflow_finishes)
            if all(times[w] <= 1.05 * t + 1e-10 for w, t in self.workflow_reference.items()): candidates.append(c)
        assert not quality or candidates
        self.guard_feasible = bool(candidates)
        if candidates:
            self.last_selected = min(candidates, key=lambda c: (c['cdi'] or 0., c['awct'], c['churn'], c['name'], c['plan'].queues))
        return RepairDecision(context.Q, self.last_selected['plan'])


def policy(method, initial):
    if method == 'WorkflowGuard': return WorkflowGuard(OnlineReference.from_initial(initial), .1)
    if method == 'ProtectedFirst': return ProtectedFirst()
    return make_method(method, initial, .1)


def error_work(w, root, mix, draw, cv):
    sigma = math.sqrt(math.log1p(cv * cv)); values = {}
    for t in w.tasks:
        key = f'R4_ERROR|{draw}|{root}|{mix}|{t.id}'.encode()
        seed = int.from_bytes(hashlib.sha256(key).digest()[:16], 'little')
        z = float(np.random.Generator(np.random.PCG64(seed)).normal())
        values[t.id] = t.work * math.exp(sigma * z - .5 * sigma * sigma)
    return values


def check_protocol():
    p = OUT / 'protocol.json'; f = OUT / 'protocol_sha256.txt'
    if not f.exists(): f.write_text(sha(p) + '\n')
    assert sha(p) == f.read_text().strip(), 'R4 protocol changed after registration'
    return sha(p)


def fixed_guard_document(ev, case, guard):
    same = next((r for r in case['runs'] if r['plan_sha256'] == guard['plan_sha256']), None)
    if same is not None:
        doc = ev.doc('run-' + case['scenario_id'] + '-' + same['method'])
        queues = doc['applied_plan']['queues']
    else:
        snap, ctx = capture(ev, case)
        plan, fc = construct(snap, ctx, guard['name'], .1)
        from sail.simulator import content_hash
        assert content_hash(plan.queues) == guard['plan_sha256']
        queues = plan.queues
    context = ev.doc('run-' + case['scenario_id'] + '-B0')['context']
    return {'context': context, 'events': [{'kind': 'PLAN_APPLIED', 'details': {'scope': context['Q'], 'queues': queues}}]}
