from dataclasses import replace
import pytest

from sail.development import LAMBDAS,MUS,choose_cached,evaluate_parameters,rank_parameters
from sail.experiment import method_aliases,run_methods,workload_from_json
from sail.model import Failure,Platform
from sail.policy import SAILPolicy,OnlineReference,select_candidate
from sail.scheduling import initial_heft
from sail.simulator import Simulator,jsonable
from sail.statistics import paired_bootstrap
from .helpers import graph
from .test_p3_policy import manual_case


def test_cached_selector_matches_live_candidates_for_all_declared_weights():
    w,p,plan,ref=manual_case()
    policy=SAILPolicy(ref,1,0.1)
    Simulator(w,p,plan,failure=Failure(1,0),repair=policy).run()
    candidates=policy.last_candidates.candidates
    cached=[{"hop":c.hop,"scope":sorted(c.scope),"queues":jsonable(c.schedule.plan.queues),"awct_ratio":c.awct_ratio,
             "predicted_cdi":c.predicted_cdi,"churn":c.churn} for c in candidates]
    for l in LAMBDAS:
        for m in MUS:assert choose_cached(cached,l,m)["hop"]==select_candidate(candidates,l,m).candidate.hop


def parameter_case(base,actual,cdi=1):
    return {"B2":{"awct":base},"candidates":[{"hop":0,"scope":["a"],"queues":[["a"]],"awct_ratio":1,
             "predicted_cdi":cdi,"churn":0,"actual":{"awct":actual,"cdi":cdi,"churn":0}}]}


def test_parameter_budget_is_mean_of_paired_ratios_not_ratio_of_means():
    row=evaluate_parameters([parameter_case(1,1.08),parameter_case(100,100)],[(0,0)])[0]
    assert row["relative_awct_vs_B2"]==pytest.approx(0.04) and row["feasible"]
    assert not evaluate_parameters([parameter_case(1,1.12),parameter_case(100,100)],[(0,0)])[0]["feasible"]
    assert not evaluate_parameters([parameter_case(1,1,None)],[(0,0)])[0]["feasible"]


def test_parameter_order_and_shortlist_are_predeclared():
    base={"feasible":True,"cdi":1,"awct":2,"churn":0,"lambda":0,"mu":0}
    rows=[{**base,"lambda":3},{**base,"lambda":1},{**base,"cdi":0.9,"lambda":3},base,{**base,"feasible":False,"cdi":0}]
    ranked=rank_parameters(rows)
    assert [(r["cdi"],r["lambda"]) for r in ranked[:3]]==[(0.9,3),(1,0),(1,1)]


def test_mu_zero_alias_is_reused_and_not_claimed_as_new_execution():
    w=graph({"a":4,"b":1,"c":2})
    p=Platform((1,1),1);initial=initial_heft(w,p)
    ref=Simulator(w,p,initial.plan).run();fault=Failure(0.3*ref.makespan,0)
    rows,runs=run_methods(w,p,initial,ref,None,fault,3,0,methods=("B0","SAIL","NoChurn"),reuse_aliases=True)
    assert method_aliases(3,0)=={"Fixed_H0":"B0","NoChurn":"SAIL"}
    assert rows["NoChurn"]["execution_alias_of"]=="SAIL" and rows["NoChurn"]["total_seconds"]==0
    assert runs["NoChurn"] is runs["SAIL"]
    assert workload_from_json(jsonable(w))==w


def stats_rows(n=3):
    return [{"root_seed":i,"mix":mix,"nodes":4,"ccr":0.5,"failure_fraction":0.3,"method":method,"protected_count":1,
             "cdi":2 if method=="B2" else 1,"awct":10 if method=="B2" else 11}
            for i in range(n) for mix in ("A","B") for method in ("B2","SAIL")]


def test_cluster_bootstrap_constant_effect_and_fixed_seed():
    rows=stats_rows()
    a=paired_bootstrap(rows,repetitions=5000)
    assert a["cluster_count"]==3 and a["cdi"]["point"]==-1 and a["cdi"]["ci95"]==[-1,-1]
    assert a["relative_awct"]["point"]==pytest.approx(0.1)
    assert a["relative_awct"]["upper95"]==pytest.approx(0.1)
    assert a==paired_bootstrap(rows,repetitions=5000)


def test_duplicate_axes_do_not_create_more_independent_roots_or_narrow_CI():
    rows=stats_rows(5)
    for r in rows:
        if r["method"]=="SAIL":r["cdi"]=0.5+r["root_seed"]
    extra=[{**r,"nodes":8} for r in rows]
    a=paired_bootstrap(rows,repetitions=200)
    b=paired_bootstrap(rows+extra,repetitions=200)
    assert a["cluster_count"]==b["cluster_count"]==5
    assert a["cdi"]["ci95"]==b["cdi"]["ci95"]


def test_CDI_NA_is_preserved_and_undefined_draws_do_not_get_a_fake_CI():
    rows=stats_rows(2)
    for r in rows:
        if r["root_seed"]==0:r["protected_count"]=0;r["cdi"]=None
    a=paired_bootstrap(rows,repetitions=100)
    assert a["cdi"]["undefined_pairs"]==2
    assert 0<a["cdi"]["defined_bootstrap_draws"]<100 and a["cdi"]["ci95"] is None
    for r in rows:r["protected_count"]=0;r["cdi"]=None
    a=paired_bootstrap(rows,repetitions=100)
    assert a["cdi"]["point"] is None and a["cdi"]["defined_bootstrap_draws"]==0


@pytest.mark.parametrize("change",["missing","duplicate","population","failed"])
def test_statistics_reject_incomplete_or_inconsistent_comparisons(change):
    rows=stats_rows()
    if change=="missing":rows.pop()
    elif change=="duplicate":rows.append(rows[0])
    elif change=="population":rows[0]["protected_count"]=2
    elif change=="failed":rows[0]["status"]="FAILED"
    with pytest.raises(ValueError):paired_bootstrap(rows,repetitions=20)
