import itertools
import networkx as nx
import pytest

from sail.data import actual_work,bandwidth_for_ccr,failure_node,speed_vector,synthetic_workload
from sail.experiment import METHODS,run_methods
from sail.model import Failure,Platform
from sail.policy import OnlineReference,SAILPolicy
from sail.scheduling import initial_heft
from sail.simulator import Simulator


@pytest.mark.parametrize("seed,mix,nodes",itertools.product((10000,10001),("A","B","C"),(4,8)))
def test_eight_method_scope_scoring_and_common_prefix(seed,mix,nodes,record_case):
    i=seed-10000;w=synthetic_workload(seed,mix)
    p=Platform(speed_vector(seed,mix,nodes),bandwidth_for_ccr(w,(0.5,2)[i]))
    truth=actual_work(w,seed,mix,(0,0.3)[i]);initial=initial_heft(w,p)
    ref=Simulator(w,p,initial.plan,realized_work=truth).run()
    f=Failure(ref.makespan*(0.3,0.6)[i],failure_node(seed,mix,nodes),0.1*w.pbar if i else 0)
    rows,runs=run_methods(w,p,initial,ref,truth,f,1,0.1)
    assert tuple(rows)==METHODS
    graph=nx.DiGraph();graph.add_nodes_from(w.task_map);graph.add_edges_from(w.edges)
    for name,run in runs.items():
        assert [e for e in run.events if e["time"]<f.time]==[e for e in ref.events if e["time"]<f.time]
        if name in {"SAIL","NoStability","NoChurn","Fixed_H1","Fixed_H2"}:
            hop=rows[name]["selected_hop"] if name in {"SAIL","NoStability","NoChurn"} else int(name[-1])
            reach=set(run.context.F)
            for root in run.context.F:reach.update(nx.single_source_shortest_path_length(graph,root,cutoff=hop))
            expected=reach & set(run.context.Q)
            applied=next(e for e in run.events if e["kind"]=="PLAN_APPLIED")
            assert set(applied["details"]["scope"])==expected
    policy=SAILPolicy(OnlineReference.from_initial(initial),1,0.1)
    again=Simulator(w,p,initial.plan,realized_work=truth,failure=f,repair=policy).run()
    assert again.trace_hash==runs["SAIL"].trace_hash
    scores=[]
    for c in policy.last_candidates.candidates:
        score=c.schedule.forecast.awct/initial.forecast.awct+(c.predicted_cdi or 0)+0.1*c.churn
        scores.append((c,score))
    best=min(s for _,s in scores)
    expected=min((c for c,s in scores if abs(s-best)<=1e-12),key=lambda c:(c.churn,len(c.scope),c.hop,c.schedule.plan.queues))
    assert policy.last_selection.candidate==expected
    record_case({"kind":"p3_eight_method_correctness","id":f"{seed}-{mix}-{nodes}","methods":8,
                 "events_checked":sum(r["events_checked"] for r in rows.values()),"unique_plans":policy.last_candidates.unique_plans,
                 "selected_hop":policy.last_selection.candidate.hop,"P_empty":not again.context.P,"F_empty":not again.context.F,
                 "determinism_verified":True,"trace_sha256":{n:r.trace_hash for n,r in runs.items()}})
