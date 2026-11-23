import math
import pytest
from sail.model import Task,DataFile,Workload,Platform,Plan,Failure,RepairDecision
from sail.simulator import Simulator
from sail.scheduling import initial_heft,Baseline
from sail.forecast import forecast_plan
from revision_r2.dispatch import SkipUnready
from revision_r6.clock_executor import ClockExecutor,predict
from v2_preparation.experiment import synthetic_v2

def compare(a,b):
    for attr in ['starts','finishes','workflow_finishes']:
        x,y=dict(getattr(a,attr)),dict(getattr(b,attr));assert x.keys()==y.keys()
        assert all(math.isclose(x[v],y[v],abs_tol=1e-8,rel_tol=1e-10) for v in x)

@pytest.mark.parametrize('rule',['strict','skip-unready'])
@pytest.mark.parametrize('cv',[0.,.3])
def test_independent_full_fault_and_forecast(rule,cv):
    from sail.data import actual_work
    w=synthetic_v2(72000,'A');p=Platform((.7,1.1,1.2),5.);initial=initial_heft(w,p)
    truth=actual_work(w,72000,'A',cv);ref=Simulator(w,p,initial.plan,realized_work=truth).run();fault=Failure(.6*ref.makespan,1)
    captured={}
    def policy(s,c):
        captured.update(snapshot=s,context=c);return Baseline('B0')(s,c)
    cls=Simulator if rule=='strict' else SkipUnready
    a=cls(w,p,initial.plan,realized_work=truth,failure=fault,repair=policy,**({'switch_time':fault.time} if rule!='strict' else {})).run()
    b=ClockExecutor(w,p,initial.plan,truth=truth,rule=rule,switch_time=fault.time,failure=fault,repair=lambda *_:RepairDecision(a.context.F,a.applied_plan)).run()
    compare(a,b);assert a.context==b.context
    if rule=='strict':compare(forecast_plan(captured['snapshot'],a.applied_plan),predict(captured['snapshot'],a.applied_plan))

def test_shared_bandwidth_conservation_and_transfer_completion():
    w=Workload((Task('a','a',1),Task('b','b',1),Task('c','a',1,('a',),('x',)),Task('d','b',1,('b',),('y',))),(DataFile('x',10,'a'),DataFile('y',10,'b')))
    p=Platform((1.,1.,1.,1.),1.);plan=Plan((('a',),('b',),('c',),('d',)))
    independent=ClockExecutor(w,p,plan).run();shared=ClockExecutor(w,p,plan,network='shared',switch_time=0.).run()
    assert dict(independent.starts)['c']==11 and dict(shared.starts)['c']==21
    assert dict(shared.starts)['d']==21
    assert shared.network_checks['max_shared_rate_fraction']==1
    assert shared.network_checks['max_relative_byte_residual']<1e-12

def test_shared_inflight_switch_keeps_transferred_bytes():
    w=Workload((Task('a','a',1),Task('b','b',1),Task('c','a',1,('a',),('x',)),Task('d','b',1,('b',),('y',))),(DataFile('x',10,'a'),DataFile('y',10,'b')))
    p=Platform((1.,1.,1.,1.),1.);plan=Plan((('a',),('b',),('c',),('d',)))
    out=ClockExecutor(w,p,plan,network='shared',switch_time=6.).run()
    assert dict(out.starts)['c']==16 and dict(out.starts)['d']==16
