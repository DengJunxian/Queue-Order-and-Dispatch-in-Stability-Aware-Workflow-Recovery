from dataclasses import replace
import pytest

from sail.audit import audit_result
from sail.metrics import paired_metrics
from sail.model import Failure, ModelError, Plan, Platform
from sail.simulator import Simulator, SimulationError
from .helpers import graph, fixed_repair, keep_plan


def checked(w,p,plan,**kwargs):
    r = Simulator(w,p,plan,**kwargs).run()
    audit_result(r,w,p,realized_work=kwargs.get("realized_work"),expected_failure=kwargs.get("failure"))
    return r


def test_single_node_chain_hand_calculation():
    w = graph({"a":1,"b":2},[("a","b",100)])
    r = checked(w,Platform((1,),1),Plan((("a","b"),)))
    assert dict(r.starts)=={"a":0,"b":1}
    assert dict(r.finishes)=={"a":1,"b":3}
    assert r.transfer_bytes==0 and r.awct==3 and r.cpu_seconds==3


def test_diamond_all_parents_then_serial_inputs():
    w = graph({"a":1,"b":3,"c":1},[("a","c",2),("b","c",4)])
    r = checked(w,Platform((1,1,1),2),Plan((("a",),("b",),("c",))))
    assert dict(r.starts)["c"]==6
    assert r.makespan==7 and r.transfer_bytes==6


def test_staging_overlaps_other_cpu_work():
    w = graph({"a":1,"b":10,"c":1},[("a","c",2)])
    r = checked(w,Platform((1,1),1),Plan((("a",),("b","c"))))
    events = [e for e in r.events if e["task"]=="c"]
    assert next(e["time"] for e in events if e["kind"]=="INPUT_START")==1
    assert next(e["time"] for e in events if e["kind"]=="INPUT_READY")==3
    assert dict(r.starts)["c"]==10


def test_strict_head_order_prevents_ready_backfill():
    w = graph({"a":5,"b":1,"c":1},[("a","b",0)])
    r = checked(w,Platform((1,1),1),Plan((("a",),("b","c"))))
    assert dict(r.starts)=={"a":0,"b":5,"c":6}


def test_restart_discards_lost_computation_and_old_completion():
    w,p,plan = graph({"a":2}),Platform((1,1),1),Plan((("a",),()))
    r = checked(w,p,plan,failure=Failure(0.5,0),repair=fixed_repair(((),("a",))))
    assert dict(r.starts)["a"]==0.5 and r.makespan==2.5
    assert dict(r.attempts)["a"]==2
    assert r.cpu_seconds==2.5 and r.wasted_cpu_seconds==0.5 and r.wasted_work==0.5
    assert any(e["kind"]=="STALE_EVENT" and e["details"]["event"]=="CPU_DONE" for e in r.events)


def test_stale_event_after_last_commit_does_not_inflate_makespan():
    w,p,plan = graph({"a":10}),Platform((1,10),1),Plan((("a",),()))
    r = checked(w,p,plan,failure=Failure(1,0),repair=fixed_repair(((),("a",))))
    assert r.makespan==2 and r.events[-1]["time"]==10
    assert sum(e["kind"]=="CPU_DONE" for e in r.events)==1


def test_completion_wins_failure_tie_and_output_is_durable():
    w = graph({"a":1,"b":1},[("a","b",4)])
    r = checked(w,Platform((1,1),2),Plan((("a","b"),())),failure=Failure(1,0),repair=fixed_repair(((),("b",))))
    assert r.context.F==frozenset({"b"})
    assert dict(r.attempts)=={"a":1,"b":1}
    assert dict(r.starts)["b"]==3 and r.makespan==4 and r.transfer_bytes==4
    assert r.wasted_cpu_seconds==0
    at1 = [e["kind"] for e in r.events if e["time"]==1]
    assert at1.index("CPU_DONE")<at1.index("FAILURE")<at1.index("PLAN_APPLIED")


def test_source_failure_during_transfer_continues_from_storage():
    w = graph({"a":0.5,"b":1},[("a","b",2)])
    r = checked(w,Platform((1,1,1),1),Plan((("a",),("b",),())),failure=Failure(1,0),repair=keep_plan)
    assert not r.context.F
    assert dict(r.starts)["b"]==2.5 and r.transfer_bytes==2
    assert not any(e["kind"]=="INPUT_CANCEL" for e in r.events)


def test_prepared_healthy_input_survives_source_failure():
    w = graph({"a":1,"b":10,"c":1},[("a","c",1)])
    r = checked(w,Platform((1,1),1),Plan((("a",),("b","c"))),failure=Failure(3,0),repair=keep_plan)
    assert dict(r.starts)["c"]==10 and r.transfer_bytes==1
    assert sum(e["kind"]=="INPUT_START" and e["task"]=="c" for e in r.events)==1


def test_transfer_destination_failure_counts_partial_and_restart():
    w = graph({"a":1,"b":1},[("a","b",10)])
    r = checked(w,Platform((1,1,1),1),Plan((("a",),("b",),())),failure=Failure(2,1),repair=fixed_repair(((),(),("b",))))
    assert r.transfer_bytes==11 and dict(r.starts)["b"]==12 and r.makespan==13
    assert r.context.F==frozenset({"b"}) and r.context.P==frozenset()
    assert dict(r.attempts)["b"]==1


def test_input_completion_wins_destination_failure_tie():
    w = graph({"a":1,"b":1},[("a","b",1)])
    r = checked(w,Platform((1,1,1),1),Plan((("a",),("b",),())),failure=Failure(2,1),repair=fixed_repair(((),(),("b",))))
    at2 = [e["kind"] for e in r.events if e["time"]==2]
    assert at2.index("INPUT_READY")<at2.index("FAILURE")
    assert dict(r.attempts)["b"]==1 and dict(r.starts)["b"]==3 and r.transfer_bytes==2


def test_optional_move_cancels_staging_and_counts_churn():
    w = graph({"a":1,"b":1},[("a","b",10)])
    r = checked(w,Platform((1,1,1,1),1),Plan((("a",),("b",),(),())),failure=Failure(2,3),repair=fixed_repair(((),(),("b",),()),{"b"}))
    assert r.context.P==frozenset({"b"}) and not r.context.F
    assert r.churn==1 and r.transfer_bytes==11 and r.makespan==13


def test_control_delay_gates_cpu_only_and_preserves_staging():
    w = graph({"a":1,"b":1},[("a","b",0.5)])
    p,plan = Platform((1,1,1),1),Plan((("a",),("b",),()))
    r = checked(w,p,plan,failure=Failure(0.5,2,2),repair=keep_plan)
    assert dict(r.finishes)["a"]==1 and dict(r.starts)["b"]==2.5
    assert next(e["time"] for e in r.events if e["task"]=="b" and e["kind"]=="INPUT_START")==1
    assert next(e["time"] for e in r.events if e["task"]=="b" and e["kind"]=="INPUT_READY")==1.5


def test_fault_at_zero_prevents_initial_failed_node_dispatch():
    w = graph({"a":1})
    r = checked(w,Platform((1,1),1),Plan((("a",),())),failure=Failure(0,0),repair=fixed_repair(((),("a",))))
    assert dict(r.attempts)["a"]==1 and r.wasted_work==0
    assert all(e["node"]==1 for e in r.events if e["kind"]=="CPU_START")


def test_queued_failed_task_is_mandatory_before_it_is_ready():
    w = graph({"a":4,"b":1},[("a","b",2)])
    r = checked(w,Platform((1,1),1),Plan((("a",),("b",))),failure=Failure(1,1),repair=fixed_repair((("a","b"),())))
    assert r.context.F==frozenset({"b"}) and r.wasted_cpu_seconds==0
    assert dict(r.starts)["a"]==0 and dict(r.finishes)["a"]==4
    assert dict(r.starts)["b"]==4 and r.transfer_bytes==0


def test_cdi_empty_is_none_and_useless_fault_retained():
    w,p,plan = graph({"a":2}),Platform((1,1),1),Plan((("a",),()))
    reference = checked(w,p,plan)
    r = checked(w,p,plan,failure=Failure(1,1),repair=keep_plan)
    metrics = paired_metrics(r,reference,w)
    assert metrics["cdi"] is None and not metrics["effective_failure"]
    assert r.context.Q==r.context.F==r.context.P==frozenset()
    assert r.makespan==reference.makespan


def test_hand_computed_protected_delay_and_churn_denominator():
    w = graph({"a":4,"b":1,"c":2},workflows={"a":"w0","b":"w1","c":"w1"})
    p,plan = Platform((1,1),1),Plan((("a",),("b","c")))
    reference = checked(w,p,plan)
    r = checked(w,p,plan,failure=Failure(0.5,0),repair=fixed_repair(((),("b","a","c"))))
    # b is already running, c is P, a is mandatory; c moves from time1 to5.
    metrics = paired_metrics(r,reference,w,same_fault_b0=r)
    a = audit_result(r,w,p,expected_failure=Failure(0.5,0),reference=reference)
    assert r.context.Q==frozenset({"a","c"}) and r.context.P==frozenset({"c"})
    assert metrics["cdi"]==pytest.approx(4/(7/3))==pytest.approx(a["cdi"])
    assert metrics["same_fault_signed_delay"]==0 and metrics["churn"]==0
    assert r.awct==6 and r.makespan==7


def test_unmatched_counterfactual_rejected():
    w,p,plan = graph({"a":1}),Platform((1,),1),Plan((("a",),))
    r = checked(w,p,plan)
    other = checked(w,p,plan,realized_work={"a":2})
    with pytest.raises(ModelError,match="matched"): paired_metrics(r,other,w)


def test_executor_is_one_shot():
    sim = Simulator(graph({"a":1}),Platform((1,),1),Plan((("a",),)))
    sim.run()
    with pytest.raises(SimulationError,match="one-shot"): sim.run()
