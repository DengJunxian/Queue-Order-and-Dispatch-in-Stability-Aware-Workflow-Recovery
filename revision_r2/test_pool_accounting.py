import pytest

from revision_r2.pool_analysis import choose
from revision_r2.wait_accounting import wait_components
from sail.model import Task, DataFile, Workload, Platform, Plan
from sail.simulator import Simulator, jsonable


def candidates():
    return [dict(name='fast',awct=10.,cdi=4.,churn=0.,workflow_completion={'a':5.,'b':15.}),
            dict(name='stable',awct=10.2,cdi=1.,churn=.1,workflow_completion={'a':9.,'b':11.}),
            dict(name='outside',awct=12.,cdi=0.,churn=0.,workflow_completion={'a':6.,'b':18.})]


def test_workflow_guard_keeps_pool_reference_when_stable_plan_harms_one_workflow():
    cs = candidates()
    assert choose(cs,10.)[0]['name'] == 'stable'
    selected, mean_ok, guard_ok = choose(cs,10.,workflow_reference=cs[0]['workflow_completion'])
    assert selected['name'] == 'fast' and mean_ok and guard_ok


def test_empty_quality_set_preserves_efficiency_fallback_and_flags_guard():
    cs = candidates()
    selected, mean_ok, guard_ok = choose(cs,8.,workflow_reference=cs[0]['workflow_completion'])
    assert selected['name'] == 'fast' and not mean_ok and not guard_ok


def test_tolerance_changes_membership_but_cap_pool_is_not_regenerated():
    cs = candidates()
    assert choose(cs,10.,epsilon=0.)[0]['name'] == 'fast'
    assert choose(cs,10.,epsilon=.05)[0]['name'] == 'stable'
    assert choose(cs,10.,epsilon=.25)[0]['name'] == 'outside'


def test_wait_accounting_separates_predecessor_staging_and_cpu_competition():
    w = Workload((Task('a','w',2.),Task('b','w',1.,('a',),('file',)),Task('c','w',7.)),
                 (DataFile('file',6.,'a'),))
    p = Platform((1.,1.),2.)
    run = Simulator(w,p,Plan((('a',),('c','b')))).run()
    assert dict(run.starts)['b'] == 7.
    part = wait_components(jsonable(run),w,0.,('b',))['b']
    assert part == pytest.approx({'predecessor':2.,'input_staging':3.,'competition':2.,'HOL':0.})


