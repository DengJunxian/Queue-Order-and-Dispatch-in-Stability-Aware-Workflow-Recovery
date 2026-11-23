"""One command executes every recovery constructor and both dispatch rules."""
import argparse
import json
import math
import sys
from pathlib import Path

PAPER = Path(__file__).resolve().parents[1]
ROOT = PAPER.parent
sys.path.insert(0, str(ROOT))
from sail.experiment import workload_from_json
from sail.model import Platform, Failure
from sail.simulator import Simulator, jsonable, content_hash
from sail.scheduling import initial_heft
from sail.metrics import paired_metrics
from sail.audit import audit_result
from revision_r2.audit_dispatch import audit_result as audit_skip
from revision_r2.dispatch import SkipUnready
from revision_r2.common import FixedDecision
from revision_r4.common import METHODS, policy
from v2_preparation.experiment import make_method


def main(output):
    data = json.loads((PAPER / 'artifact/example_case/input.json').read_text())
    w = workload_from_json(data['workload']); p = Platform(tuple(data['platform']['speeds']), data['platform']['bandwidth'])
    initial = initial_heft(w, p); assert jsonable(initial.plan.queues) == data['initial_queues']
    fault = Failure(**data['failure']); truth = data['truth']; records = []; checked = 0
    strict_reference = Simulator(w, p, initial.plan, realized_work=truth).run()
    skip_reference = SkipUnready(w, p, initial.plan, realized_work=truth, switch_time=fault.time).run()
    checked += audit_result(strict_reference, w, p, realized_work=truth)['events_checked']
    checked += audit_skip(skip_reference, w, p, realized_work=truth, dispatch_switch_time=fault.time)['events_checked']
    for method in (*METHODS, 'B1', 'B2', 'BudgetHEFT10', 'LegacySAIL'):
        pi = policy(method, initial) if method in METHODS else make_method(method, initial)
        strict = Simulator(w, p, initial.plan, realized_work=truth, failure=fault, repair=pi).run()
        skip = SkipUnready(w, p, initial.plan, realized_work=truth, failure=fault, repair=FixedDecision(jsonable(strict)), switch_time=fault.time).run()
        assert strict.applied_plan == skip.applied_plan and strict.context == skip.context
        for rule, run, reference in (('strict', strict, strict_reference), ('skip-unready', skip, skip_reference)):
            if method in (*METHODS, 'BudgetHEFT10'):
                moves=sum(run.applied_plan.assignment[v]!=dict(run.context.old_assignment)[v] for v in run.context.Q-run.context.F)
                cap=0 if method in ('B0','B0AssignmentReorder','QueueRepair0','ProtectedFirst') else math.floor(.1*max(1,len(run.context.Q)))
                assert moves<=cap
            auditor = audit_skip if rule == 'skip-unready' else audit_result
            audit = auditor(run, w, p, realized_work=truth, expected_failure=fault, reference=reference,
                            **({'dispatch_switch_time': fault.time} if rule == 'skip-unready' else {})); checked += audit['events_checked']
            metrics = paired_metrics(run, reference, w)
            metrics.update({'workflow_completion': dict(run.workflow_finishes), 'plan_sha256': content_hash(run.applied_plan.queues)})
            expect = data['expected'].get(rule + '/' + method)
            if expect:
                for key, value in expect.items():
                    if isinstance(value, dict): assert all(math.isclose(metrics[key][k], x, abs_tol=1e-9) for k, x in value.items())
                    elif isinstance(value, (int, float)): assert math.isclose(metrics[key], value, abs_tol=1e-9)
                    else: assert metrics[key] == value
            records.append({'method': method, 'rule': rule, **metrics, 'saved_benchmark_available': expect is not None, 'matches_saved_benchmark': True if expect is not None else None})
    result = {'status': 'PASS', 'source_scenario_id': data['source_scenario_id'], 'methods': 11, 'dispatch_rules': 2,
        'physical_validation_executions': 24, 'independent_event_checks': checked, 'new_scientific_samples': 0, 'records': records}
    Path(output).write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'records'}))


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--output', default='/private/tmp/cscwd-r4-example-replay.json')
    main(p.parse_args().output)
