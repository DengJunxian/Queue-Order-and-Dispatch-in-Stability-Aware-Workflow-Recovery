"""Meaningful new-control checks against the sealed baseline and arithmetic oracle."""
import itertools
import math

import pytest

from research_v2.policies import BudgetPolicy,BudgetSelect,budget_schedule
from sail.audit import audit_result
from sail.model import Failure,ModelError,Plan,Platform
from sail.policy import OnlineReference
from sail.scheduling import Baseline,initial_heft
from sail.simulator import Simulator
from tests.helpers import graph
from tests.p2_oracles import continuation_oracle


@pytest.mark.parametrize('mask,delay',itertools.product(range(64),(0,.1)))
def test_new_controls_match_oracles_and_respect_budget(mask,delay):
    edges=[(u,v,1+i%3) for i,(u,v) in enumerate(itertools.combinations('abcd',2)) if mask&(1<<i)]
    w=graph({'a':1,'b':2,'c':.5,'d':3,'e':2,'f':.7},edges,{'a':'x','b':'x','c':'x','d':'x','e':'y','f':'z'})
    p=Platform((1,1.5,.8),2.75);initial=initial_heft(w,p);ref=Simulator(w,p,initial.plan).run()
    f=Failure(.3*ref.makespan,mask%3,delay*w.pbar);b2=Baseline('B2')
    r=Simulator(w,p,initial.plan,failure=f,repair=b2).run();snap=b2.last_snapshot;ctx=r.context
    uncapped=budget_schedule(snap,ctx,None)
    assert uncapped.plan==b2.last_schedule.plan and uncapped.forecast==b2.last_schedule.forecast
    for theta in (0,.1,.5):
        policy=BudgetPolicy(theta);run=Simulator(w,p,initial.plan,failure=f,repair=policy).run()
        a=audit_result(run,w,p,expected_failure=f,reference=ref)
        assert run.context==ctx
        assert run.churn<=theta+1e-12
        schedule=policy.last_schedule;assert schedule.optional_moves<=math.floor(theta*max(1,len(ctx.Q)))
        starts,finishes=continuation_oracle(snap,schedule.plan)
        assert dict(schedule.forecast.starts)==pytest.approx(starts)
        assert dict(schedule.forecast.finishes)==pytest.approx(finishes)
        assert [e for e in run.events if e['time']<f.time]==[e for e in ref.events if e['time']<f.time]
        if theta==0:
            assert all(run.applied_plan.assignment[v]==dict(ctx.old_assignment)[v] for v in ctx.Q-ctx.F)
        assert a['churn']==run.churn
    policy=BudgetSelect(OnlineReference.from_initial(initial))
    selected=Simulator(w,p,initial.plan,failure=f,repair=policy).run()
    audit_result(selected,w,p,expected_failure=f,reference=ref)
    assert selected.churn<=.1+1e-12 and selected.context==ctx
    assert not policy.last_quality_feasible or policy.last_selected['awct']<=1.05*b2.last_schedule.forecast.awct
    again=Simulator(w,p,initial.plan,failure=f,repair=BudgetSelect(OnlineReference.from_initial(initial))).run()
    assert again==selected


def test_zero_move_control_releases_queue_order_only():
    w=graph({'a':10,'b':1,'c':2});p=Platform((1,1,1),100);plan=Plan((('b','a'),('c',),()))
    policy=BudgetPolicy(0);run=Simulator(w,p,plan,failure=Failure(0,2),repair=policy).run()
    assert not run.context.F and run.applied_plan.queues[0]==('a','b') and run.churn==0
    assert run.context.P==frozenset(w.task_map)


@pytest.mark.parametrize('theta',[-1,1.1,float('nan'),float('inf'),True,'0.1'])
def test_invalid_budget_rejected(theta):
    with pytest.raises(ModelError):budget_schedule(None,None,theta)
