import hashlib
import json
import sys
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sail.experiment import workload_from_json
from sail.frozen import result_from_json
from sail.model import Plan, Platform, Failure, RepairDecision
from sail.simulator import Simulator, jsonable
from revision_r1.io import dump as _dump

FREEZE = ROOT / 'freeze/g2_v2_20261025'
RUNS = ROOT / 'results/g2_v2_20261025'
BS, PM, BH, Q0, AL = 'BudgetSelect10', 'PoolMinAWCT10', 'BudgetHEFT10', 'QueueRepair0', 'B0AssignmentReorder'


def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def dump(path, data): return _dump(path, jsonable(data))


class Evidence:
    def __init__(self):
        self.raw = {r['job_id']: r for r in (json.loads(s) for s in (RUNS / 'metrics.jsonl').read_text().splitlines())}
        self.cases = [json.loads(s) for s in (ROOT / 'revision_r1/analysis/case_analysis.jsonl').read_text().splitlines()]
        self.manifest = json.loads((FREEZE / 'scenario_manifest.json').read_text())
        self.bases = {b['id']: b for b in self.manifest['bases']}
        self.scenarios = {s['id']: s for s in self.manifest['scenarios']}
        self.main = {(c['base_id'], c['failure_fraction']): c for c in self.cases if c['variant'] == 'main'}
        self.priority = {r['scenario_id']: r for r in (json.loads(s) for s in (ROOT / 'revision_r1/exploratory/priority/metrics.jsonl').read_text().splitlines())}

    @lru_cache(maxsize=16)
    def doc(self, jid):
        row = self.raw[jid]
        p = RUNS / row['event_file']
        assert sha(p) == row['event_sha256']
        return json.loads(p.read_text())

    def result(self, jid): return result_from_json(self.doc(jid))

    @lru_cache(maxsize=16)
    def inputs(self, bid):
        b = self.bases[bid]
        w = workload_from_json(json.loads((FREEZE / b['workload_file']).read_text()))
        return w, Platform(tuple(b['speeds']), b['bandwidth']), json.loads((FREEZE / b['truth_file']).read_text())

    def initial_plan(self, bid): return Plan(tuple(tuple(q) for q in self.doc('ref-' + bid)['events'][0]['details']['queues']))

    def failure(self, case):
        s = self.scenarios[case['scenario_id']]
        w, _, _ = self.inputs(case['base_id'])
        return Failure(self.doc('ref-' + case['base_id'])['makespan'] * s['failure_fraction'], s['failed_node'], s['control_delay_pbar_units'] * w.pbar)


class SnapshotReady(Exception): pass


class Capture(Simulator):
    def _apply(self):
        self.public_snapshot, self.original_context = self.snapshot(), self._context
        raise SnapshotReady


def capture(evidence, case):
    w, p, truth = evidence.inputs(case['base_id'])
    engine = Capture(w, p, evidence.initial_plan(case['base_id']), realized_work=truth,
                     failure=evidence.failure(case), repair=lambda *_: None)
    try: engine.run()
    except SnapshotReady: pass
    return engine.public_snapshot, engine.original_context


class FixedDecision:
    def __init__(self, document):
        self.document = document
    def __call__(self, snapshot, context):
        assert sorted(context.P) == self.document['context']['P']
        assert sorted(context.F) == self.document['context']['F']
        event = next(e for e in self.document['events'] if e['kind'] == 'PLAN_APPLIED')
        return RepairDecision(frozenset(event['details']['scope']), Plan(tuple(tuple(q) for q in event['details']['queues'])))
