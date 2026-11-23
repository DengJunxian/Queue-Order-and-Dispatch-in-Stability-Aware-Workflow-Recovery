import copy
import pytest
from revision_r6.common import *
from revision_r6.run_holdout import evaluate_case,snapshot_at,audit_saved
from revision_r6.audit_clock import audit
from sail.simulator import Simulator
from v2_preparation.experiment import synthetic_v2

def test_full_dispatch_guard_and_shared_link_pipeline():
    w=synthetic_v2(72001,'A');p=Platform((.7,1.1,1.2),5.);initial=initial_heft(w,p);truth={t.id:t.work for t in w.tasks}
    ref=Simulator(w,p,initial.plan).run();fault=Failure(.6*ref.makespan,1)
    snapshot,context=snapshot_at(w,p,truth,initial,fault);old,pool,b2=original_choices(snapshot,context,initial)
    d=evaluate_case(w,p,truth,initial,fault,old,pool,b2,snapshot,context,['independent','shared'],eta={'strict':1.1,'skip-unready':1.1},strict_reference=ref)
    rows,checks=audit_saved(d,w,p,truth,fault)
    assert len(rows)==44 and checks['repair_executions']==44
    for network in ['independent','shared']:
        for rule in ['strict','skip-unready']:
            key=network+'/'+rule
            a=dict(d['runs'][key+'/DispatchMatchedGuard']['clock']['workflow_finishes']);b=dict(d['runs'][key+'/DispatchMinAWCT']['clock']['workflow_finishes'])
            assert all(a[k]<=1.05*b[k]+1e-8 for k in a)
            assert d['runs'][key+'/CalibratedGuard']['clock']['applied_plan']==d['runs'][key+'/DispatchMinAWCT']['clock']['applied_plan']
            assert d['metadata'][key]['calibrated_reference_fallback']
    bad=copy.deepcopy(d['runs']['shared/strict/B0']['clock']);next(e for e in bad['events'] if e['kind']=='cpu_done')['time']+=1
    with pytest.raises(AssertionError):audit(bad,w,p,truth,'shared',fault.time)
