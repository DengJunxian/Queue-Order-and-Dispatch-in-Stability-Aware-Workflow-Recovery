"""Executed, hand-specified counterexample to transferring the strict guarantee.

This is a correctness witness, not a new benchmark sample or an empirical rate.
The supplied B0 plan is feasible and preserves all optional assignments/order.
It is not asserted to be the output of a particular EFT tie-breaking rule.
"""
from __future__ import annotations
import json
from pathlib import Path
from sail.model import Task, Workload, Platform, Plan, Failure
from sail.simulator import Simulator
from sail.audit import audit_result
from sail.metrics import paired_metrics
from revision_r2.dispatch import SkipUnready
from revision_r2.audit_dispatch import audit_result as audit_skip
from revision_r5.control import ProtectedSubsequence


def check():
    w = Workload((Task('r', 'a', 2.), Task('p', 'a', 1., ('r',)),
                  Task('f', 'b', 10.)))
    platform = Platform((1., 1., 1.), 1.)
    initial = Plan((('p',), ('r',), ('f',)))
    b0 = Plan((('p', 'f'), ('r',), ()))
    failure = Failure(.5, 2)
    rows = []
    audited_events = 0
    for rule in ('strict', 'skip-unready'):
        cls = Simulator if rule == 'strict' else SkipUnready
        kw = {} if rule == 'strict' else {'switch_time': .5}
        ref = cls(w, platform, initial, **kw).run()
        run = cls(w, platform, initial, failure=failure,
                  repair=ProtectedSubsequence(b0), **kw).run()
        for item in (ref, run):
            auditor = audit_result if rule == 'strict' else audit_skip
            receipt = auditor(item, w, platform, reference=ref if item is run else None,
                              expected_failure=failure if item is run else None,
                              **({'dispatch_switch_time': .5} if rule != 'strict' else {}))
            audited_events += receipt['events_checked']
        metrics = paired_metrics(run, ref, w)
        assert run.context.P == frozenset(('p',))
        assert run.churn == 0.
        assert run.applied_plan == b0
        pstart, sref = dict(run.starts)['p'], dict(ref.starts)['p']
        assert sref == 2.
        assert pstart == (2. if rule == 'strict' else 10.5)
        rows.append({'dispatcher': rule, 'reference_p_start': sref,
                     'recovery_p_start': pstart, 'delay': pstart - sref,
                     'cdi': metrics['cdi'], 'optional_churn': run.churn,
                     'recovery_events': list(run.events), 'reference_events': list(ref.events)})
    return {'status': 'PASS', 'kind': 'constructive_correctness_witness',
            'benchmark_samples_added': 0, 'validation_executions': 4,
            'audited_events': audited_events,
            'claim': 'The strict protected-start guarantee need not hold under skip-unready.',
            'baseline_note': 'An explicit valid B0-style plan, not an EFT optimality claim.',
            'workload': {'r': 2., 'p': 1., 'f': 10., 'edge': ['r', 'p']},
            'platform_speeds': [1., 1., 1.], 'fault_time': .5, 'failed_node': 2,
            'initial_queues': initial.queues, 'repaired_queues': b0.queues, 'rows': rows}

if __name__ == '__main__':
    result = check()
    target = Path(__file__).parent / 'reports' / 'projection_dispatch_witness.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k:v for k,v in result.items() if k not in {'rows'}}, indent=2))
