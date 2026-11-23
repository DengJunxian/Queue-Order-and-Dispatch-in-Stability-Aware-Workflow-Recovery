from dataclasses import replace
import pytest

from sail.audit import audit_result
from sail.forecast import forecast_plan
from sail.model import Failure,ModelError,Plan,Platform,Task,Workload
from sail.scheduling import Baseline,baseline_scope,initial_heft,initial_snapshot,schedule_scope
from sail.simulator import Simulator,content_hash
from .helpers import graph
from .p2_oracles import check_all_gap_choices,continuation_oracle


def test_rank_and_real_gap_insertion_hand_calculation():
    w=graph({"a":10,"b":1,"c":12,"d":1},[("a","b",3)])
    p=Platform((1,2),1)
    s=initial_heft(w,p)
    assert dict(s.ranks)=={"a":11.25,"b":0.75,"c":9,"d":0.75}
    assert [x.task for x in s.placements]==["a","c","b","d"]
    assert s.plan==Plan((("d","b"),("a","c")))
    assert dict(s.forecast.starts)=={"a":0,"b":8,"c":5,"d":0}
    assert s.placements[-1].chosen.position==0
    r=Simulator(w,p,s.plan).run()
    assert r.starts==s.forecast.starts and r.finishes==s.forecast.finishes
    check_all_gap_choices(initial_snapshot(w,p),frozenset(w.task_map),s)
    audit_result(r,w,p)


def test_workflow_then_task_rank_tie_and_node_tie():
    w=Workload((Task("z","a_workflow",1),Task("a","b_workflow",1)))
    s=initial_heft(w,Platform((1,1),1))
    assert [x.task for x in s.placements]==["z","a"]
    assert s.plan==Plan((("z",),("a",)))


def test_single_node_zero_communication_serial_plan():
    w=graph({"a":1,"b":3,"c":2},[("a","c",0)])
    s=initial_heft(w,Platform((1,),1))
    assert s.forecast.makespan==6
    r=Simulator(w,Platform((1,),1),s.plan).run()
    assert r.transfer_bytes==0 and r.finishes==s.forecast.finishes


def test_EFT_tie_prefers_earlier_start_before_node_ID():
    w=graph({"a":12,"b":2,"v":3})
    p=Platform((3,1,1),1)
    policy=Baseline("B0")
    r=Simulator(w,p,Plan((("a",),("b",),("v",))),failure=Failure(0.1,2),repair=policy).run()
    step=policy.last_schedule.placements[0]
    assert step.task=="v" and step.chosen.node==1 and step.chosen.start==2 and step.chosen.finish==5
    assert {c.finish for c in step.candidates}=={5}
    assert dict(r.finishes)["v"]==5
    check_all_gap_choices(policy.last_snapshot,policy.last_schedule.scope,policy.last_schedule)


def test_baseline_scopes_and_frozen_queue_anchors():
    w=graph({"f":2,"r":4,"a":1,"b":3})
    p,plan=Platform((1,1,1),1),Plan((("r","a","b"),(),("f",)))
    policy=Baseline("B0")
    r=Simulator(w,p,plan,failure=Failure(1,2),repair=policy).run()
    s=policy.last_schedule
    order=[x.task for x in s.placements]
    assert order.index("a")<order.index("b") and dict(s.ranks)["b"]>dict(s.ranks)["a"]
    assert s.plan.assignment["a"]==s.plan.assignment["b"]==0
    assert s.scope==r.context.F==frozenset({"f"})
    check_all_gap_choices(policy.last_snapshot,s.scope,s)
    audit_result(r,w,p,expected_failure=Failure(1,2))


def test_B1_includes_all_pending_descendants_not_other_workflow():
    w=graph({"a":4,"b":1,"c":1,"r":8,"e":2},[("a","b",1),("b","c",1)])
    p,plan=Platform((1,1,1),1),Plan((("a",),("b","c"),("r","e")))
    policies=[Baseline(name) for name in ("B0","B1","B2")]
    results=[Simulator(w,p,plan,failure=Failure(1,0),repair=b).run() for b in policies]
    assert [b.last_schedule.scope for b in policies]==[frozenset({"a"}),frozenset({"a","b","c"}),frozenset({"a","b","c","e"})]
    assert results[0].context==results[1].context==results[2].context
    assert all(b.last_schedule.kernel=="protocol_v1_HEFT_EFT" for b in policies)
    for b in policies: check_all_gap_choices(b.last_snapshot,b.last_schedule.scope,b.last_schedule)


def test_empty_F_B0_B1_keep_assignment_while_B2_can_replan():
    w=graph({"a":4,"b":1})
    p,plan,f=Platform((1,1,1),1),Plan((("a","b"),(),())),Failure(1,2)
    policies=[Baseline(n) for n in ("B0","B1","B2")]
    results=[Simulator(w,p,plan,failure=f,repair=b).run() for b in policies]
    assert all(not r.context.F for r in results)
    assert policies[0].last_schedule.plan==policies[1].last_schedule.plan==plan
    assert policies[2].last_schedule.plan.assignment["b"]==1
    assert results[2].churn==1 and dict(results[2].starts)["b"]==1


def test_partial_staging_progress_kept_and_reassignment_restarts():
    w=graph({"a":1,"b":1},[("a","b",10)])
    p,plan,f=Platform((1,1,1),1),Plan((("a",),("b",),())),Failure(2,2)
    b0,b2=Baseline("B0"),Baseline("B2")
    r0=Simulator(w,p,plan,failure=f,repair=b0).run()
    r2=Simulator(w,p,plan,failure=f,repair=b2).run()
    assert b0.last_schedule.placements[0].chosen.input_ready==11
    assert dict(r0.starts)["b"]==11 and r0.transfer_bytes==10
    assert b2.last_schedule.plan.assignment["b"]==0
    assert dict(r2.starts)["b"]==2 and r2.transfer_bytes==1
    for b in (b0,b2):
        starts,finishes=continuation_oracle(b.last_snapshot,b.last_schedule.plan)
        assert dict(b.last_schedule.forecast.starts)==pytest.approx(starts)
        assert dict(b.last_schedule.forecast.finishes)==pytest.approx(finishes)


def test_failed_source_local_data_read_from_durable_store():
    w=graph({"a":1,"b":1},[("a","b",4)])
    p,plan=Platform((1,1),2),Plan((("a","b"),()))
    b=Baseline("B0")
    r=Simulator(w,p,plan,failure=Failure(1,0),repair=b).run()
    assert b.last_schedule.placements[0].chosen.input_ready==3
    assert dict(r.starts)["b"]==3 and r.transfer_bytes==4
    assert b.last_schedule.forecast.finishes==r.finishes


def test_control_delay_rebases_after_healthy_running_completes():
    w=graph({"r":1,"f":4})
    p,plan,f=Platform((1,1),1),Plan((("r",),("f",))),Failure(0.5,1,2)
    b=Baseline("B0")
    r=Simulator(w,p,plan,failure=f,repair=b).run()
    assert b.last_snapshot.time==2.5 and b.last_snapshot.completed==frozenset({"r"})
    assert b.last_context.Q==frozenset({"f"})
    assert dict(r.starts)["f"]==2.5 and r.makespan==6.5
    assert b.last_schedule.forecast.finishes==r.finishes


@pytest.mark.parametrize("name",["B0","B1","B2"])
def test_estimation_overrun_and_future_isolation(name):
    w=graph({"a":1,"b":1})
    p,plan,f=Platform((1,1,1),1),Plan((("a","b"),(),())),Failure(4,2)
    schedules=[]
    for duration in (10,20):
        policy=Baseline(name)
        Simulator(w,p,plan,realized_work={"a":duration,"b":1},failure=f,repair=policy).run()
        schedules.append(policy.last_schedule)
        assert dict(policy.last_schedule.forecast.finishes)["a"]==pytest.approx(4+1e-9)
    assert schedules[0]==schedules[1]


def test_empty_pending_set_keeps_running_reservation():
    w=graph({"a":2})
    b=Baseline("B2")
    r=Simulator(w,Platform((1,1),1),Plan((("a",),())),failure=Failure(1,1),repair=b).run()
    assert not b.last_schedule.scope and not b.last_schedule.placements
    assert b.last_schedule.forecast.finishes==r.finishes


def test_completed_workload_forecast_does_not_use_current_time_as_makespan():
    w=graph({"a":1})
    b=Baseline("B0")
    r=Simulator(w,Platform((1,1),1),Plan((("a",),())),failure=Failure(2,1),repair=b).run()
    assert b.last_schedule.forecast.makespan==r.makespan==1


def test_scope_and_baseline_invalid_inputs_rejected():
    with pytest.raises(ModelError): Baseline("DaTR")
    w,p=graph({"a":1}),Platform((1,1),1)
    snap=initial_snapshot(w,p)
    with pytest.raises(ModelError): schedule_scope(snap,None,frozenset())
    with pytest.raises(ModelError): schedule_scope(snap,None,{"a"})
    with pytest.raises(ModelError): forecast_plan(snap,Plan((("a","a"),())))


def test_prepared_ready_input_is_preserved_in_prediction():
    w=graph({"a":1,"r":20,"b":1},[("a","b",1)])
    b=Baseline("B0")
    p,plan,f=Platform((1,1,1),1),Plan((("a",),("r","b"),())),Failure(3,2)
    r=Simulator(w,p,plan,failure=f,repair=b).run()
    assert b.last_schedule.placements[0].chosen.input_ready==3
    assert dict(b.last_schedule.forecast.starts)["b"]==dict(r.starts)["b"]==20
