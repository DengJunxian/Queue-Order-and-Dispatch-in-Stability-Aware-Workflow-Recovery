from dataclasses import replace
from unittest.mock import patch
import pytest

from sail.audit import audit_result
from sail.forecast import forecast_plan
from sail.model import Failure,FailureContext,ModelError,Plan,Platform
from sail.policy import Candidate,FixedScopePolicy,OnlineReference,SAILPolicy,bounded_scopes,generate_candidates,select_candidate
from sail.scheduling import Baseline,initial_heft,initial_snapshot,schedule_scope
from sail.simulator import Simulator
from .helpers import graph


def context(Q,F):
    return FailureContext(0,0,frozenset(Q),frozenset(F),frozenset(),(),())


def test_hops_use_shortest_logical_distance_and_union_F():
    w=graph(dict.fromkeys("abcd",1),[("a","b",1),("b","c",1),("c","d",1),("a","d",1)])
    assert bounded_scopes(w,context("abcd","a"))==(frozenset("a"),frozenset("abd"),frozenset("abcd"))
    assert bounded_scopes(w,context("acd","a"))==(frozenset("a"),frozenset("ad"),frozenset("acd"))
    assert bounded_scopes(w,context("abcd","ac"))[0]==frozenset("ac")
    assert bounded_scopes(w,context("abcd",""))==(frozenset(),)*3


def manual_case(speeds=(1,2,1)):
    w=graph({"a":4,"b":3,"r":8,"e":1},[("a","b",1)])
    p,plan=Platform(speeds,1),Plan((("a",),("r","e"),("b",)))
    forecast=forecast_plan(initial_snapshot(w,p),plan)
    ref=OnlineReference("PREDICTED_NO_FAULT",forecast.awct,forecast.starts)
    return w,p,plan,ref


def test_scope_dedup_generation_once_and_distinct_plan_reuse():
    w,p,plan,ref=manual_case()
    policy=SAILPolicy(ref,1,0.1)
    with patch("sail.policy.schedule_scope",wraps=schedule_scope) as called:
        r=Simulator(w,p,plan,failure=Failure(1,0),repair=policy).run()
        assert called.call_count==2
    c=policy.last_candidates
    assert c.unique_scopes==2 and c.unique_plans==2
    assert [x.aliases for x in c.candidates]==[(0,),(1,2)]
    assert policy.last_selection.candidate.hop==1
    audit_result(r,w,p,expected_failure=Failure(1,0))


def test_identical_plans_merge_across_different_scopes():
    w,p,plan,ref=manual_case((1,1,1))
    policy=SAILPolicy(ref,1,0.1)
    r=Simulator(w,p,plan,failure=Failure(1,0),repair=policy).run()
    assert policy.last_candidates.unique_scopes==2 and policy.last_candidates.unique_plans==1
    assert policy.last_candidates.candidates[0].aliases==(0,1,2)
    assert policy.last_selection.candidate.hop==0
    audit_result(r,w,p,expected_failure=Failure(1,0))


def score_fixture(hop,ratio,cdi,churn,scope):
    s=initial_heft(graph({"a":1}),Platform((1,),1))
    return Candidate(hop,(hop,),replace(s,scope=frozenset(scope)),ratio,cdi,churn)


def test_known_score_and_effective_ablation_weights():
    a=score_fixture(0,0.9,1,0,"a")
    b=score_fixture(1,1.0,0.1,0.2,"ab")
    result=select_candidate((a,b),1,0.1)
    assert result.candidate==b and result.score==pytest.approx(1.12)
    assert select_candidate((a,b),0,0.1).candidate==a
    ref=OnlineReference.from_initial(initial_heft(graph({"a":1}),Platform((1,),1)))
    assert SAILPolicy(ref,3,0.1,"NoStability").lambda_value==0
    assert SAILPolicy(ref,3,0.1,"NoStability").mu_value==0.1
    assert SAILPolicy(ref,3,0.1,"NoChurn").lambda_value==3
    assert SAILPolicy(ref,3,0.1,"NoChurn").mu_value==0


def test_score_tolerance_uses_global_minimum_then_declared_ties():
    a=score_fixture(0,1.0,None,0.5,"a")
    b=score_fixture(1,1.0+1e-13,None,0,"ab")
    assert select_candidate((a,b),0,0).candidate==b
    assert select_candidate((replace(b,awct_ratio=1.0+2e-12),a),0,0).candidate==a
    a=replace(a,churn=0)
    b=replace(b,awct_ratio=1.0)
    assert select_candidate((b,a),0,0).candidate==a
    assert select_candidate((a,replace(a,hop=2)),0,0).candidate.hop==0


def test_empty_P_is_not_applicable_and_scored_as_zero():
    w=graph({"a":2});p=Platform((1,1),1)
    initial=initial_heft(w,p);ref=OnlineReference.from_initial(initial)
    policy=SAILPolicy(ref,3,0.1)
    fault=Failure(0.5,initial.plan.assignment["a"])
    r=Simulator(w,p,initial.plan,failure=fault,repair=policy).run()
    assert policy.last_candidates.protected_count==0
    assert all(c.predicted_cdi is None for c in policy.last_candidates.candidates)
    assert policy.last_selection.score==pytest.approx(policy.last_selection.candidate.awct_ratio)


@pytest.mark.parametrize("variant",["SAIL","NoStability","NoChurn"])
def test_all_variants_future_information_isolation(variant):
    w=graph(dict.fromkeys("abcd",1));p=Platform((1,1,1),1)
    initial=initial_heft(w,p);ref=OnlineReference.from_initial(initial)
    outputs=[]
    for duration in (10,20):
        policy=SAILPolicy(ref,1,0.1,variant)
        truth=dict.fromkeys("abcd",1);truth["a"]=duration
        r=Simulator(w,p,initial.plan,realized_work=truth,failure=Failure(2,2),repair=policy).run()
        outputs.append((policy.last_candidates,policy.last_selection))
        audit_result(r,w,p,realized_work=truth,expected_failure=Failure(2,2))
    assert outputs[0]==outputs[1]


def test_fixed_H0_is_B0_without_new_algorithm():
    w,p,plan,_=manual_case()
    f=Failure(1,0)
    a=Simulator(w,p,plan,failure=f,repair=FixedScopePolicy(0)).run()
    b=Simulator(w,p,plan,failure=f,repair=Baseline("B0")).run()
    assert a.trace_hash==b.trace_hash


@pytest.mark.parametrize("hop",[1,2])
def test_fixed_hops_use_exact_scope_and_common_kernel(hop):
    w,p,plan,_=manual_case()
    policy=FixedScopePolicy(hop)
    r=Simulator(w,p,plan,failure=Failure(1,0),repair=policy).run()
    assert policy.last_schedule.scope==bounded_scopes(w,r.context)[hop]
    audit_result(r,w,p,expected_failure=Failure(1,0))


@pytest.mark.parametrize("weight",[-1,float("nan"),float("inf"),True])
def test_invalid_scores_rejected(weight):
    with pytest.raises(ModelError): select_candidate((score_fixture(0,1,None,0,"a"),),weight,0)


def test_online_reference_cannot_be_actual_execution_result():
    w=graph({"a":1});p=Platform((1,),1)
    initial=initial_heft(w,p);actual=Simulator(w,p,initial.plan).run()
    with pytest.raises(ModelError): OnlineReference.from_initial(actual)
