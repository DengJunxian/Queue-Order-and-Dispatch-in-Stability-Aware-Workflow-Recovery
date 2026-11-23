import copy

import pytest

from sail.model import Task, Workload, Platform, Plan
from sail.simulator import Simulator, jsonable
from revision_r2.audit_dispatch import audit_result, AuditError
from revision_r2.dispatch import SkipUnready
from revision_r2.wait_accounting import wait_components


def instance():
    w = Workload((Task('a', 'w', 6), Task('h', 'w', 1, ('a',)), Task('p', 'w', 1)))
    p = Platform((1., 1.), 10.)
    return w, p, Plan((('a',), ('h', 'p')))


def test_ready_task_skips_unready_head_and_decomposition_is_exact():
    w, p, plan = instance()
    strict = Simulator(w, p, plan).run()
    loose = SkipUnready(w, p, plan, switch_time=0).run()
    assert dict(strict.starts)['p'] == 7 and dict(loose.starts)['p'] == 0
    assert dict(loose.starts)['h'] == 6
    audit_result(loose, w, p, dispatch_switch_time=0)
    parts = wait_components(jsonable(strict), w, 0, ('p',))['p']
    assert parts == {'predecessor': 0, 'input_staging': 0, 'competition': 1, 'HOL': 6}
    assert sum(wait_components(jsonable(loose), w, 0, ('p',))['p'].values()) == 0


@pytest.mark.parametrize('switch', (1., 3., 6., 8.))
def test_switch_time_and_healthy_running_heads(switch):
    w, p, plan = instance()
    loose = SkipUnready(w, p, plan, switch_time=switch).run()
    audit_result(loose, w, p, dispatch_switch_time=switch)
    assert dict(loose.finishes)['a'] == 6
    assert dict(loose.starts)['p'] == (switch if switch < 6 else 7)


def test_auditor_rejects_false_promotion_and_early_switch():
    w, p, plan = instance()
    run = SkipUnready(w, p, plan, switch_time=0).run()
    with pytest.raises(AuditError): audit_result(run, w, p, dispatch_switch_time=1)
    from dataclasses import replace
    events = copy.deepcopy(list(run.events))
    next(e for e in events if e['kind'] == 'QUEUE_SKIP')['details']['skipped'] = []
    with pytest.raises(AuditError): audit_result(replace(run, events=tuple(events)), w, p, dispatch_switch_time=0)


def test_all_ready_dispatch_agrees_with_original_executor():
    w = Workload(tuple(Task(str(i), 'w', i + 1) for i in range(4)))
    p = Platform((1., 2.), 5.)
    plan = Plan((('0', '2'), ('1', '3')))
    assert SkipUnready(w, p, plan, switch_time=0).run().events == Simulator(w, p, plan).run().events
