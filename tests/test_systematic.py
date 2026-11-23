from dataclasses import replace
import itertools
import pytest

from sail.audit import audit_result
from sail.data import actual_work, bandwidth_for_ccr, failure_node, speed_vector, synthetic_workload
from sail.metrics import paired_metrics
from sail.model import Failure, Plan, Platform, Workload
from sail.simulator import Simulator
from .helpers import graph, fixed_repair, ordered_round_robin, recurrence_oracle, serial_repair


@pytest.mark.parametrize("mask",range(64))
def test_all_four_task_DAGs_and_two_node_assignments(mask,record_case):
    # All edge subsets under one topological labeling; 16 assignments per graph.
    possible = list(itertools.combinations("abcd",2))
    edges = [(u,v,1+(i%3)) for i,(u,v) in enumerate(possible) if mask & (1<<i)]
    w,p = graph({"a":1,"b":2,"c":0.5,"d":3},edges),Platform((1,1.5),2.75)
    for assignment in itertools.product(range(2),repeat=4):
        plan = Plan(tuple(tuple(v for v,j in zip("abcd",assignment) if j==node) for node in range(2)))
        r = Simulator(w,p,plan).run()
        starts,finishes = recurrence_oracle(w,p,plan)
        assert dict(r.starts)==pytest.approx(starts), (mask,assignment)
        assert dict(r.finishes)==pytest.approx(finishes), (mask,assignment)
        a = audit_result(r,w,p)
        record_case({"kind":"exhaustive_fixed_plan","id":f"mask{mask:02d}-"+"".join(map(str,assignment)),
                     "tasks":4,"oracle_max_finish_error":max(abs(dict(r.finishes)[v]-finishes[v]) for v in finishes),
                     "events_checked":a["events_checked"],"trace_sha256":r.trace_hash})


@pytest.mark.parametrize("seed,mix,nodes",itertools.product(range(10000,10010),("A","B","C"),(4,8)))
def test_synthetic_failure_replay_and_invariants(seed,mix,nodes,record_case):
    w = synthetic_workload(seed,mix)
    i = seed-10000
    ccr,cv = (0.5,2)[i%2],(0,0.1,0.3)[i%3]
    p = Platform(speed_vector(seed,mix,nodes),bandwidth_for_ccr(w,ccr))
    truth = actual_work(w,seed,mix,cv)
    plan = ordered_round_robin(w,nodes)
    reference = Simulator(w,p,plan,realized_work=truth).run()
    starts,finishes = recurrence_oracle(w,p,plan,truth)
    assert dict(reference.starts)==pytest.approx(starts)
    assert dict(reference.finishes)==pytest.approx(finishes)
    ar = audit_result(reference,w,p,realized_work=truth)
    f = Failure(reference.makespan*(0.3,0.6)[i%2],failure_node(seed,mix,nodes),0.1*w.pbar if i%2 else 0)
    r = Simulator(w,p,plan,realized_work=truth,failure=f,repair=serial_repair).run()
    a = audit_result(r,w,p,realized_work=truth,expected_failure=f,reference=reference)
    metrics = paired_metrics(r,reference,w)
    assert metrics["cdi"]==pytest.approx(a["cdi"]) if a["cdi"] is not None else metrics["cdi"] is None
    assert [e for e in r.events if e["time"]<f.time]==[e for e in reference.events if e["time"]<f.time]
    repeated = Simulator(w,p,plan,realized_work=truth,failure=f,repair=serial_repair).run()
    assert r.trace_hash==repeated.trace_hash
    record_case({"kind":"synthetic_failure","id":f"{seed}-{mix}-{nodes}","tasks":len(w.tasks),
                 "ccr":ccr,"cv":cv,"failure_node":f.node,"delay":f.control_delay,
                 "effective_failure":bool(r.context.F),"protected_count":len(r.context.P),
                 "events_checked":a["events_checked"]+ar["events_checked"],
                 "determinism_verified":True,"metrics_recomputed":True,
                 "reference_trace_sha256":reference.trace_hash,"fault_trace_sha256":r.trace_hash})


def test_signed_same_fault_delay_can_be_positive_and_negative():
    w = graph({"a":4,"b":1,"c":2},workflows={"a":"w0","b":"w1","c":"w1"})
    p,plan,f = Platform((1,1),1),Plan((("a",),("b","c"))),Failure(0.5,0)
    reference = Simulator(w,p,plan).run()
    late = Simulator(w,p,plan,failure=f,repair=fixed_repair(((),("b","a","c")))).run()
    early = Simulator(w,p,plan,failure=f,repair=fixed_repair(((),("b","c","a")))).run()
    a = audit_result(late,w,p,expected_failure=f)
    b = audit_result(early,w,p,expected_failure=f)
    expected = (a["starts"]["c"]-b["starts"]["c"])/w.pbar
    assert expected==pytest.approx(12/7)
    assert paired_metrics(late,reference,w,same_fault_b0=early)["same_fault_signed_delay"]==pytest.approx(expected)
    assert paired_metrics(early,reference,w,same_fault_b0=late)["same_fault_signed_delay"]==pytest.approx(-expected)


def test_uniform_time_unit_change_preserves_CDI_and_churn():
    w = graph({"a":4,"b":1,"c":2},workflows={"a":"w0","b":"w1","c":"w1"})
    plan,f = Plan((("a",),("b","c"))),Failure(0.5,0,0.1)
    results = []
    for factor in (1,7):
        scaled = Workload(tuple(replace(t,work=t.work*factor) for t in w.tasks),w.files)
        p = Platform((1,1),1/factor)
        fault = Failure(f.time*factor,f.node,f.control_delay*factor)
        ref = Simulator(scaled,p,plan).run()
        r = Simulator(scaled,p,plan,failure=fault,repair=fixed_repair(((),("b","a","c")))).run()
        audit_result(r,scaled,p,expected_failure=fault,reference=ref)
        results.append((r,paired_metrics(r,ref,scaled)))
    assert results[1][0].makespan==pytest.approx(7*results[0][0].makespan)
    assert results[1][1]["cdi"]==pytest.approx(results[0][1]["cdi"])
    assert results[1][1]["churn"]==results[0][1]["churn"]
