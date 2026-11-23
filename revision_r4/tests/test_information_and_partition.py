"""Critical new review checks; policy inputs contain no evaluator truth."""
from dataclasses import fields
from types import SimpleNamespace

import pytest

from sail.model import Workload, Task, Platform, Failure, Snapshot, TaskView, Plan, ModelError, validate_plan
from sail.scheduling import initial_heft
from sail.simulator import Simulator
from sail.policy import OnlineReference
from revision_r2.common import Capture, SnapshotReady
from revision_r4.common import WorkflowGuard, policy, METHODS


def fixture():
    w = Workload((Task('f1', 'w0', 2.), Task('f2', 'w0', 3., ('f1',)),
                  Task('p', 'w1', 4.), Task('q', 'w2', 2.5)), ())
    p = Platform((1., 1.3, .8), 1.)
    return w, p, initial_heft(w, p)


def test_multiple_roots_are_excluded_and_form_disjoint_partition():
    w, _, _ = fixture(); F = frozenset(('f1', 'f2')); Q = frozenset(w.task_map)
    D = (w.descendants(F) & Q) - F; P = Q - F - D
    assert D == frozenset() and F.isdisjoint(D)
    assert not (F & P or D & P) and F | D | P == Q


def test_hidden_future_work_cannot_change_public_state_or_any_policy_decision():
    w, p, initial = fixture(); snapshots = []
    for scale in (1., 1.7):
        engine = Capture(w, p, initial.plan, realized_work={t.id: t.work * scale for t in w.tasks},
                         failure=Failure(.1, 0), repair=lambda *_: None)
        with pytest.raises(SnapshotReady): engine.run()
        snapshots.append((engine.public_snapshot, engine.original_context))
    assert snapshots[0] == snapshots[1]
    assert not any('realized' in f.name or 'truth' in f.name for cls in (Snapshot, TaskView) for f in fields(cls))
    for method in METHODS:
        decisions = [policy(method, initial)(s, c) for s, c in snapshots]
        assert decisions[0] == decisions[1]
    reference = OnlineReference.from_initial(initial)
    assert reference.starts == initial.forecast.starts


def test_combined_queue_dependency_cycle_is_rejected():
    w, p, _ = fixture()
    with pytest.raises(ModelError):
        validate_plan(w, p, Plan((('f2', 'f1'), ('p',), ('q',))))


def test_workflow_guard_full_policy_has_a_valid_same_pool_witness():
    w, p, initial = fixture(); pi = WorkflowGuard(OnlineReference.from_initial(initial), .1)
    run = Simulator(w, p, initial.plan, failure=Failure(.1, 0), repair=pi).run()
    assert run.applied_plan is not None
    assert not pi.last_quality_feasible or pi.guard_feasible
