import itertools
import networkx as nx
import pytest

from sail.audit import audit_result
from sail.data import actual_work,bandwidth_for_ccr,failure_node,speed_vector,synthetic_workload
from sail.metrics import paired_metrics
from sail.model import Failure,Platform
from sail.scheduling import Baseline,initial_heft,initial_snapshot
from sail.simulator import Simulator,content_hash
from .helpers import graph,recurrence_oracle
from .p2_oracles import check_all_gap_choices,continuation_oracle


def small_graph(mask):
    possible=list(itertools.combinations("abcd",2))
    edges=[(u,v,1+(i%3)) for i,(u,v) in enumerate(possible) if mask & (1<<i)]
    return graph({"a":1,"b":2,"c":0.5,"d":3},edges)


@pytest.mark.parametrize("mask,speeds",itertools.product(range(64),[(1,),(1,1.5),(1,1,1)]))
def test_initial_HEFT_all_gaps_vs_independent_arithmetic(mask,speeds,record_case):
    w,p=small_graph(mask),Platform(speeds,2.75)
    schedule=initial_heft(w,p)
    check_all_gap_choices(initial_snapshot(w,p),frozenset(w.task_map),schedule)
    starts,finishes=recurrence_oracle(w,p,schedule.plan)
    assert dict(schedule.forecast.starts)==pytest.approx(starts)
    assert dict(schedule.forecast.finishes)==pytest.approx(finishes)
    result=Simulator(w,p,schedule.plan).run()
    audit=audit_result(result,w,p)
    assert dict(result.starts)==pytest.approx(starts) and dict(result.finishes)==pytest.approx(finishes)
    record_case({"kind":"p2_initial_enumeration","id":f"mask{mask}-nodes{len(speeds)}","all_gap_choices_verified":True,
                 "events_checked":audit["events_checked"],"plan_sha256":content_hash(schedule.plan),
                 "max_finish_error":max(abs(dict(schedule.forecast.finishes)[v]-finishes[v]) for v in finishes)})


def verify_three(w,p,plan,reference,failure,truth=None,*,all_gaps=False):
    runs,policies,audits={},{},{}
    graph=nx.DiGraph();graph.add_nodes_from(w.task_map);graph.add_edges_from(w.edges)
    max_error=0.0
    for name in ("B0","B1","B2"):
        policy=Baseline(name)
        r=Simulator(w,p,plan,realized_work=truth,failure=failure,repair=policy).run()
        a=audit_result(r,w,p,realized_work=truth,expected_failure=failure,reference=reference)
        context=r.context
        descendants=set().union(*(nx.descendants(graph,v) for v in context.F)) if context.F else set()
        expected={"B0":context.F,"B1":context.F | (frozenset(descendants)&context.Q),"B2":context.Q}[name]
        assert policy.last_schedule.scope==expected
        assert [e for e in r.events if e["time"]<failure.time]==[e for e in reference.events if e["time"]<failure.time]
        starts,finishes=continuation_oracle(policy.last_snapshot,policy.last_schedule.plan)
        predicted=policy.last_schedule.forecast
        assert dict(predicted.starts)==pytest.approx(starts)
        assert dict(predicted.finishes)==pytest.approx(finishes)
        max_error=max(max_error,max(abs(dict(predicted.finishes)[v]-finishes[v]) for v in finishes))
        if all_gaps:
            check_all_gap_choices(policy.last_snapshot,expected,policy.last_schedule)
            assert dict(predicted.starts)==pytest.approx(dict(r.starts))
            assert dict(predicted.finishes)==pytest.approx(dict(r.finishes))
        runs[name],policies[name],audits[name]=r,policy,a
    assert runs["B0"].context==runs["B1"].context==runs["B2"].context
    assert len({r.case_key for r in runs.values()})==1
    assert len({r.wasted_work for r in runs.values()})==len({r.wasted_cpu_seconds for r in runs.values()})==1
    assert dict(runs["B0"].attempts)==dict(runs["B1"].attempts)==dict(runs["B2"].attempts)
    metrics={}
    for name in runs:
        value=paired_metrics(runs[name],reference,w,same_fault_b0=runs["B0"])
        assert value["cdi"]==pytest.approx(audits[name]["cdi"]) if value["cdi"] is not None else audits[name]["cdi"] is None
        P=runs[name].context.P
        signed=sum(audits[name]["starts"][v]-audits["B0"]["starts"][v] for v in P)/len(P)/w.pbar if P else None
        assert value["same_fault_signed_delay"]==pytest.approx(signed) if signed is not None else value["same_fault_signed_delay"] is None
        metrics[name]={"awct":value["awct"],"cdi":value["cdi"],"churn":value["churn"],"same_fault_signed_delay":value["same_fault_signed_delay"]}
    return runs,policies,audits,metrics,max_error


@pytest.mark.parametrize("mask",range(64))
def test_all_small_DAG_fault_nodes_and_scopes(mask,record_case):
    w,p=small_graph(mask),Platform((1,1.5),2.75)
    plan=initial_heft(w,p).plan
    reference=Simulator(w,p,plan).run()
    for node,fraction in itertools.product(range(2),(0.3,0.6)):
        failure=Failure(reference.makespan*fraction,node)
        runs,policies,audits,metrics,error=verify_three(w,p,plan,reference,failure,all_gaps=True)
        context=runs["B0"].context
        record_case({"kind":"p2_small_fault_enumeration","id":f"mask{mask}-node{node}-fraction{fraction}",
                     "baseline_runs":3,"all_gap_choices_verified":True,"F_empty":not context.F,"P_empty":not context.P,
                     "events_checked":sum(a["events_checked"] for a in audits.values()),"max_finish_error":error,
                     "metrics":metrics,"trace_sha256":{name:r.trace_hash for name,r in runs.items()}})


@pytest.mark.parametrize("seed,mix,nodes,ccr,fraction",itertools.product(range(10010,10013),("A","B","C"),(4,8),(0.5,2),(0.3,0.6)))
def test_protocol_development_grid_baseline_correctness(seed,mix,nodes,ccr,fraction,record_case):
    w=synthetic_workload(seed,mix)
    p=Platform(speed_vector(seed,mix,nodes),bandwidth_for_ccr(w,ccr))
    initial=initial_heft(w,p)
    cv=(0,0.1,0.3)[seed-10010]
    truth=actual_work(w,seed,mix,cv)
    reference=Simulator(w,p,initial.plan,realized_work=truth).run()
    ar=audit_result(reference,w,p,realized_work=truth)
    failure=Failure(reference.makespan*fraction,failure_node(seed,mix,nodes),0.1*w.pbar if fraction==0.6 else 0)
    runs,policies,audits,metrics,error=verify_three(w,p,initial.plan,reference,failure,truth)
    repeated_initial=initial_heft(w,p)
    assert repeated_initial==initial
    repeated=Simulator(w,p,initial.plan,realized_work=truth,failure=failure,repair=Baseline("B2")).run()
    assert repeated.trace_hash==runs["B2"].trace_hash
    context=runs["B0"].context
    record_case({"kind":"p2_development_baselines","id":f"{seed}-{mix}-{nodes}-{ccr}-{fraction}","tasks":len(w.tasks),
                 "baseline_runs":3,"cv":cv,"control_delay":failure.control_delay,"F_empty":not context.F,"P_empty":not context.P,
                 "events_checked":ar["events_checked"]+sum(a["events_checked"] for a in audits.values()),
                 "max_finish_error":error,"determinism_verified":True,"shared_context_verified":True,
                 "metrics":metrics,"initial_plan_sha256":content_hash(initial.plan),
                 "baseline_plan_sha256":{name:content_hash(b.last_schedule.plan) for name,b in policies.items()},
                 "trace_sha256":{name:r.trace_hash for name,r in runs.items()}})
