import random
from dataclasses import replace

import pytest

from tests.helpers import graph, ordered_round_robin
from sail.model import Plan, Platform, Failure, ModelError
from sail.simulator import Simulator
from sail.metrics import paired_metrics
from sail.audit import audit_result
from revision_r2.common import Capture, SnapshotReady
from revision_r5.control import ProtectedSubsequence, protected_subsequence
from sail.scheduling import schedule_scope


def fixture(seed):
    rng = random.Random(seed)
    ids = [f't{i:02}' for i in range(14)]
    w = graph({v: rng.uniform(.2, 5.) for v in ids},
              [(a, b, rng.uniform(.1, 3.)) for i, a in enumerate(ids)
               for b in ids[i + 1:] if rng.random() < .13])
    p = Platform((1., 1.3, .8), 2.)
    return w, p, ordered_round_robin(w, 3)


@pytest.mark.parametrize('seed', range(20))
def test_zero_strict_cdi_and_valid_execution_with_unobserved_work_errors(seed):
    w, p, initial = fixture(seed)
    rng = random.Random(1000 + seed)
    truth = {t.id: t.work * rng.uniform(.35, 2.2) for t in w.tasks}
    ref = Simulator(w, p, initial, realized_work=truth).run()
    fault = Failure(ref.makespan * .31, seed % 3)
    run = Simulator(w, p, initial, realized_work=truth, failure=fault,
                    repair=ProtectedSubsequence()).run()
    result = audit_result(run, w, p, realized_work=truth, reference=ref, expected_failure=fault)
    assert result['events_checked'] == len(run.events)
    assert run.churn == 0.
    starts, reference = dict(run.starts), dict(ref.starts)
    assert all(starts[v] <= reference[v] + 1e-9 for v in run.context.P)
    assert paired_metrics(run, ref, w)['cdi'] in (None, 0.)


def test_transformation_preserves_b0_assignment_and_each_group_subsequence():
    w, p, initial = fixture(20)
    engine = Capture(w, p, initial, failure=Failure(.1, 0), repair=lambda *_: None)
    with pytest.raises(SnapshotReady): engine.run()
    s, c = engine.public_snapshot, engine.original_context
    b = schedule_scope(s, c, c.F).plan
    d = protected_subsequence(s, c, b)
    assert d.plan.assignment == b.assignment
    for old, new in zip(b.queues, d.plan.queues):
        for group in (c.P, c.Q - c.P, s.running):
            assert tuple(v for v in old if v in group) == tuple(v for v in new if v in group)
    # Reject a changed protected set with a pending external predecessor.
    pair = next(((u, v) for u, v in w.edges if u in c.Q and v in c.Q), None)
    assert pair is not None
    bad = replace(c, P=frozenset((pair[1],)))
    with pytest.raises(ModelError, match='predecessor closed'):
        protected_subsequence(s, bad, b)
