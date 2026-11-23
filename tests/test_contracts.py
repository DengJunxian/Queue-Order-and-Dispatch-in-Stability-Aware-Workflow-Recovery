from dataclasses import FrozenInstanceError, replace
import copy
import pytest

from sail.audit import AuditError, audit_events, audit_result
from sail.metrics import paired_metrics
from sail.model import DataFile, Failure, ModelError, Plan, Platform, RepairDecision, Task, Workload
from sail.simulator import Simulator, jsonable
from .helpers import graph, fixed_repair, keep_plan, serial_repair


@pytest.mark.parametrize("bad",[0,-1,float("nan"),float("inf"),True])
def test_invalid_work_rejected(bad):
    with pytest.raises(ModelError): Workload((Task("a","w",bad),))


@pytest.mark.parametrize("bad",[0,-1,float("nan"),float("inf")])
def test_invalid_platform_rejected(bad):
    with pytest.raises(ModelError): Platform((1,),bad)
    with pytest.raises(ModelError): Platform((bad,),1)


@pytest.mark.parametrize("queues",[(("a","a"),), ((),), (("unknown",),)])
def test_plan_requires_every_task_once(queues):
    with pytest.raises(ModelError): Simulator(graph({"a":1}),Platform((1,),1),Plan(queues))


def test_queue_cycle_rejected_before_execution():
    w = graph({"a":1,"b":1},[("a","b",1)])
    with pytest.raises(ModelError,match="cycle"):
        Simulator(w,Platform((1,),1),Plan((("b","a"),)))


def test_cross_node_resource_cycle_rejected():
    w = graph({"a":1,"b":1,"c":1,"d":1},[("a","c",1),("b","d",1)])
    with pytest.raises(ModelError,match="cycle"):
        Simulator(w,Platform((1,1),1),Plan((("d","a"),("c","b"))))


@pytest.mark.parametrize("fault",[(-1,0,0),(0,-1,0),(0,0,-1),(float("nan"),0,0),(0,False,0)])
def test_invalid_fault_rejected(fault):
    with pytest.raises(ModelError): Failure(*fault)


def test_missing_repair_callback_is_not_silently_a_baseline():
    with pytest.raises(ModelError,match="explicit"):
        Simulator(graph({"a":1}),Platform((1,1),1),Plan((("a",),())),failure=Failure(0.5,0))


def test_cannot_move_healthy_running_task():
    w,p,plan = graph({"a":4,"b":4}),Platform((1,1,1),1),Plan((("a",),("b",),()))
    with pytest.raises(ModelError,match="healthy running"):
        Simulator(w,p,plan,failure=Failure(1,0),repair=fixed_repair(((),("a",),("b",)),{"a"})).run()


def test_cannot_omit_mandatory_F():
    w,p,plan = graph({"a":4}),Platform((1,1),1),Plan((("a",),()))
    with pytest.raises(ModelError,match="contain F"):
        Simulator(w,p,plan,failure=Failure(1,0),repair=fixed_repair(((),("a",)),set())).run()


def test_cannot_assign_to_failed_node():
    with pytest.raises(ModelError,match="failed node"):
        Simulator(graph({"a":2}),Platform((1,1),1),Plan((("a",),())),failure=Failure(1,0),repair=keep_plan).run()


def test_H_external_assignment_fixed():
    w,p,plan = graph({"a":4,"b":4,"c":1}),Platform((1,1,1),1),Plan((("a",),("b","c"),()))
    with pytest.raises(ModelError,match="assignment outside H"):
        Simulator(w,p,plan,failure=Failure(1,0),repair=fixed_repair(((),("b","a"),("c",)))).run()


def test_H_external_relative_order_fixed():
    w,p,plan = graph({"a":4,"b":4,"c":1,"d":1}),Platform((1,1),1),Plan((("a",),("b","c","d")))
    with pytest.raises(ModelError,match="relative queue order"):
        Simulator(w,p,plan,failure=Failure(1,0),repair=fixed_repair(((),("b","d","c","a")))).run()


def test_F_P_use_logic_descendants_not_resource_queue_descendants():
    w = graph({"a":4,"b":1,"c":1,"d":3,"e":1},[("a","b",1),("b","c",1)])
    p,plan = Platform((1,1,1),1),Plan((("a",),("b","c"),("d","e")))
    captured = []
    def policy(snapshot,context):
        captured.append(context)
        return serial_repair(snapshot,context)
    r = Simulator(w,p,plan,failure=Failure(1,0),repair=policy).run()
    assert r.context.F==frozenset({"a"}) and r.context.Q==frozenset({"a","b","c","e"})
    assert r.context.P==frozenset({"e"}) and captured[0]==r.context
    audit_result(r,w,p,expected_failure=Failure(1,0))


def test_churn_excludes_mandatory_changes_with_common_Q_denominator():
    w = graph({"a":4,"b":4,"c":1})
    p,plan = Platform((1,1,1),1),Plan((("a",),("b","c"),()))
    r = Simulator(w,p,plan,failure=Failure(1,0),repair=fixed_repair(((),("b","a"),("c",)),{"a","c"})).run()
    assert r.context.Q==frozenset({"a","c"}) and r.churn==0.5
    audit_result(r,w,p,expected_failure=Failure(1,0))


def test_snapshot_is_immutable_and_future_work_is_not_exposed():
    w,p,plan = graph({"a":1,"b":1}),Platform((1,1),1),Plan((("a","b"),()))
    views,decisions = [],[]
    def policy(snapshot,context):
        with pytest.raises(FrozenInstanceError): snapshot.time=999
        with pytest.raises(FrozenInstanceError): snapshot.tasks[0].node=999
        for key in ["_realized","realized_work","_events","future_events","case_key","result"]:
            assert not hasattr(snapshot,key)
        a = next(t for t in snapshot.tasks if t.id=="a")
        assert a.estimated_remaining==pytest.approx(1e-9)
        views.append(jsonable(snapshot))
        decision = keep_plan(snapshot,context)
        decisions.append(decision)
        return decision
    # Same observed prefix through t=4; latent remaining execution differs.
    for actual in (10,20):
        r = Simulator(w,p,plan,realized_work={"a":actual,"b":1},failure=Failure(4,1),repair=policy).run()
        audit_result(r,w,p,realized_work={"a":actual,"b":1},expected_failure=Failure(4,1))
    assert views[0]==views[1] and decisions[0]==decisions[1]


def test_external_inputs_are_prestaged():
    w = Workload((Task("a","w",1,(),("external",)),),(DataFile("external",1e9,None),))
    r = Simulator(w,Platform((1,),1),Plan((("a",),))).run()
    assert r.makespan==1 and r.transfer_bytes==0
    audit_result(r,w,Platform((1,),1))


def test_shared_file_consumed_by_two_tasks_is_charged_per_consumer():
    w = Workload((Task("a","w",1),Task("b","w",1,("a",),("f",)),Task("c","w",1,("a",),("f",))),
                 (DataFile("f",5,"a"),))
    p,plan = Platform((1,1,1),1),Plan((("a",),("b",),("c",)))
    r = Simulator(w,p,plan).run()
    assert r.transfer_bytes==10 and r.makespan==7
    audit_result(r,w,p)


def test_repaired_queue_cycle_is_rejected():
    w = graph({"a":4,"b":1,"c":1},[("b","c",1)])
    p,plan = Platform((1,1),1),Plan((("a",),("b","c")))
    with pytest.raises(ModelError,match="cycle"):
        Simulator(w,p,plan,failure=Failure(0,0),repair=fixed_repair(((),("a","c","b")),{"a","b","c"})).run()


@pytest.fixture
def trace_case():
    w = graph({"a":1,"b":2},[("a","b",3)])
    p,plan = Platform((1,1),1),Plan((("a",),("b",)))
    return w,p,Simulator(w,p,plan).run()


@pytest.mark.parametrize("mutation",["early_cpu","bad_bytes","unknown_task","duplicate_commit","missing_commit","stored_metric","wrong_initial_order","unissued_stale"])
def test_independent_auditor_rejects_corruption(trace_case,mutation):
    w,p,r = trace_case
    if mutation=="stored_metric":
        with pytest.raises(AuditError): audit_result(replace(r,awct=r.awct+1),w,p)
        return
    events = copy.deepcopy(list(r.events))
    if mutation=="early_cpu":
        event = next(e for e in events if e["kind"]=="CPU_START" and e["task"]=="b")
        event["time"] -= 0.5
    elif mutation=="bad_bytes":
        next(e for e in events if e["kind"]=="INPUT_READY" and e["task"]=="b")["details"]["bytes"] += 1
    elif mutation=="unknown_task":
        next(e for e in events if e["kind"]=="CPU_START")["task"] = "forged"
    elif mutation=="duplicate_commit":
        events.append(copy.deepcopy(events[-1]))
    elif mutation=="missing_commit":
        events = [e for e in events if not(e["kind"]=="CPU_DONE" and e["task"]=="b")]
    elif mutation=="wrong_initial_order":
        events[0]["details"]["queues"] = [["a","b"],[]]
    elif mutation=="unissued_stale":
        events.append({"seq":0,"time":events[-1]["time"],"kind":"STALE_EVENT","task":"a","node":None,"details":{"event":"CPU_DONE","attempt":42}})
    for i,e in enumerate(events): e["seq"]=i
    with pytest.raises(AuditError): audit_events(w,p,events)


def test_auditor_rejects_changed_P_and_control_delay():
    w,p,plan = graph({"a":1,"b":1}),Platform((1,1),1),Plan((("a","b"),()))
    f = Failure(0.5,1,1)
    r = Simulator(w,p,plan,failure=f,repair=keep_plan).run()
    for field,value in [("P",[]),("control_delay",99)]:
        events = copy.deepcopy(list(r.events))
        e = next(e for e in events if e["kind"]=="FAILURE")
        if field=="P": e["details"]["context"]["P"]=value
        else: e["details"][field]=value
        with pytest.raises(AuditError): audit_events(w,p,events,expected_failure=f)
