import pytest
from sail.audit import audit_result
from sail.data import speed_vector, failure_node as original_failure
from sail.model import Platform, Failure
from sail.scheduling import initial_heft
from sail.simulator import Simulator
from tests.helpers import graph
from revision_r1.policies import ProtectedFirst
from revision_r1.run_exploratory import generalized_platform, failure_node


@pytest.mark.parametrize('seed', [81000, 81001, 81009])
@pytest.mark.parametrize('mix', list('ABC'))
@pytest.mark.parametrize('nodes', [4, 8])
def test_generalized_random_fields_preserve_original(seed, mix, nodes):
    w = graph({'a': 1, 'b': 2}, [('a', 'b', 1)])
    p = generalized_platform(seed, mix, nodes, w, .5)
    assert p.speeds == speed_vector(seed, mix, nodes)
    assert failure_node(seed, mix, nodes) == original_failure(seed, mix, nodes)


@pytest.mark.parametrize('nodes', [2, 4, 16, 32])
@pytest.mark.parametrize('fraction', [.1, .6])
def test_priority_repair_valid_and_assignment_locked(nodes, fraction):
    w = graph({'a': 4, 'b': 2, 'c': 1, 'p': 2, 'q': 3, 'r': 1},
              [('a', 'b', 1), ('b', 'c', 1), ('p', 'q', 2)],
              {'a': 'w0', 'b': 'w0', 'c': 'w0', 'p': 'w1', 'q': 'w1', 'r': 'w2'})
    platform = Platform(tuple(1 + j / nodes for j in range(nodes)), 2)
    initial = initial_heft(w, platform)
    reference = Simulator(w, platform, initial.plan).run()
    run = Simulator(w, platform, initial.plan, failure=Failure(reference.makespan * fraction, 0), repair=ProtectedFirst()).run()
    a = audit_result(run, w, platform, expected_failure=Failure(reference.makespan * fraction, 0), reference=reference)
    assert a['events_checked'] > 0 and run.churn == 0
    for q in run.applied_plan.queues:
        location = {v: i for i, v in enumerate(q)}
        assert all(location[p] < location[f] for p in run.context.P & location.keys() for f in run.context.F & location.keys())
