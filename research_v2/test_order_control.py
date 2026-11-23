import itertools
import pytest

from research_v2.order_control import B0AssignmentReorder
from sail.audit import audit_result
from sail.model import Failure,Platform
from sail.scheduling import Baseline,initial_heft
from sail.simulator import Simulator
from tests.helpers import graph


@pytest.mark.parametrize('mask',range(64))
def test_only_queue_order_changes_from_B0(mask):
    edges=[(u,v,1+i%3) for i,(u,v) in enumerate(itertools.combinations('abcd',2)) if mask&(1<<i)]
    w=graph({'a':1,'b':2,'c':.5,'d':3,'e':2},edges,{'a':'x','b':'x','c':'x','d':'x','e':'y'})
    p=Platform((1,1.5,.8),2.75);initial=initial_heft(w,p);ref=Simulator(w,p,initial.plan).run()
    f=Failure(.3*ref.makespan,mask%3,.1*w.pbar)
    b0=Simulator(w,p,initial.plan,failure=f,repair=Baseline('B0')).run()
    r=Simulator(w,p,initial.plan,failure=f,repair=B0AssignmentReorder()).run()
    assert r.applied_plan.assignment==b0.applied_plan.assignment and r.context==b0.context and r.churn==0
    audit_result(r,w,p,expected_failure=f,reference=ref)
