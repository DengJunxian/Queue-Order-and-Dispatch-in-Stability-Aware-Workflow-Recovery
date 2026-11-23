import itertools
import math
import random

import pytest

from research_v2.policies import BudgetSelect
from sail.audit import audit_result
from sail.model import Failure,Platform
from sail.policy import OnlineReference
from sail.scheduling import initial_heft
from sail.simulator import Simulator
from tests.helpers import graph
from v2_preparation.metrics import inversion_count,queue_disturbance
from v2_preparation.policies import PoolMinAWCT


@pytest.mark.parametrize('mask,delay',itertools.product(range(64),(0,.1)))
def test_identical_pool_and_quality_eligibility(mask,delay):
    edges=[(u,v,1+i%3) for i,(u,v) in enumerate(itertools.combinations('abcd',2)) if mask&(1<<i)]
    w=graph({'a':1,'b':2,'c':.5,'d':3,'e':2,'f':.7},edges,{'a':'x','b':'x','c':'x','d':'x','e':'y','f':'z'})
    p=Platform((1,1.5,.8),2.75);initial=initial_heft(w,p);ref=Simulator(w,p,initial.plan).run();f=Failure(.3*ref.makespan,mask%3,delay*w.pbar)
    reference=OnlineReference.from_initial(initial);a=BudgetSelect(reference);b=PoolMinAWCT(reference)
    ar=Simulator(w,p,initial.plan,failure=f,repair=a).run();br=Simulator(w,p,initial.plan,failure=f,repair=b).run()
    assert a.last_candidates==b.last_candidates and a.last_quality_feasible==b.last_quality_feasible
    assert a.last_selected==b.original_selection and b.original_decision.plan==ar.applied_plan
    eligible=[c for c in b.last_candidates if c['quality_feasible']] or b.last_candidates
    assert b.last_selected['awct']==min(c['awct'] for c in eligible)
    assert br.churn<=.1+1e-12
    audit_result(br,w,p,expected_failure=f,reference=ref)
    d=queue_disturbance(br.context,br.applied_plan)
    old=dict(br.context.old_assignment);new=br.applied_plan.assignment;expected=denom=0
    for node,q in enumerate(br.context.original_queues):
        kept=[v for v in q if v in br.context.Q-br.context.F and new[v]==old[v]];pos={v:i for i,v in enumerate(br.applied_plan.queues[node])}
        denom+=len(kept)*(len(kept)-1)//2;expected+=sum(pos[u]>pos[v] for u,v in itertools.combinations(kept,2))
    assert d['queue_inversions']==expected and d['comparable_pairs']==denom


@pytest.mark.parametrize('n',range(10))
def test_inversions_vs_exhaustive_pairs(n):
    rng=random.Random(83100+n)
    for i in range(30):
        values=list(range(n));rng.shuffle(values)
        assert inversion_count(values)==sum(a>b for a,b in itertools.combinations(values,2))


def test_duplicate_rank_rejected():
    with pytest.raises(ValueError):inversion_count([1,1])
