from types import SimpleNamespace as NS
from sail.model import Plan
from revision_r7.common import fit_envelope,paired_choices,observed_workload


def rows():
    ref={'name':'H0','plan':Plan((('a','b'),())), 'awct':10.,'cdi':2.,'churn':0.,'forecast':NS(workflow_finishes=(('w00',10.),('w01',10.)))}
    alt={'name':'H1','plan':Plan((('a',),('b',))), 'awct':10.05,'cdi':1.,'churn':0.,'forecast':NS(workflow_finishes=(('w00',10.2),('w01',9.9)))}
    return ref,alt


def common_samples():
    ref,alt=rows()
    return [{'candidate':c['name'],'workflow':g,'root':root,'predicted':t,'realized':2*t,'reference_predicted':10.,'reference_realized':20.} for root in range(3) for c in [ref,alt] for g,t in c['forecast'].workflow_finishes]


def test_common_error_cancels_and_candidate_admission_is_nontrivial():
    e=fit_envelope(common_samples());assert e['eta']==.5 and e['global_delta']==0.
    ref,alt=rows();d,s,meta=paired_choices(NS(Q=frozenset({'a','b'})),[ref,alt],ref,11.,e)
    assert all(c['plan']==alt['plan'] for c in s.values())
    assert all(not m['reference_fallback'] for m in meta.values())


def test_uncovered_and_large_error_groups_return_reference():
    e=fit_envelope(common_samples());e['global_delta']=.2;e['conditional']['H1|w00']['distinct_roots']=2
    ref,alt=rows();d,s,meta=paired_choices(NS(Q=frozenset({'a','b'})),[ref,alt],ref,11.,e)
    assert all(c['plan']==ref['plan'] for c in s.values())
    assert all(m['reference_fallback'] for m in meta.values())


def test_prediction_and_file_model_do_not_depend_on_realized_repeat():
    for mix,count in [('BLAST_new',449),('BWA_SRA_new',230),('SRA_seen',190)]:
        a,t3,p=observed_workload(mix,3);b,t4,_=observed_workload(mix,4);c,t5,_=observed_workload(mix,5)
        assert a==b==c and t3!=t4 and t4!=t5 and len(a.tasks)==count
        assert abs(a.pbar-1)<1e-12
