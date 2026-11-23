"""Audited synthetic candidate cache and the predeclared two-stage weight rule."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
from collections import Counter
from pathlib import Path

from .audit import audit_result
from .data import bandwidth_for_ccr,failure_node,speed_vector,synthetic_workload
from .metrics import paired_metrics
from .model import Failure,Platform,RepairDecision
from .policy import OnlineReference,generate_candidates
from .scheduling import Baseline,initial_heft
from .simulator import Simulator,content_hash,jsonable

LAMBDAS=(0,0.1,0.3,1,3)
MUS=(0,0.01,0.1)


def dump(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    text=json.dumps(jsonable(data),ensure_ascii=False,indent=2,allow_nan=False)+"\n"
    temporary=path.with_suffix(path.suffix+".tmp")
    temporary.write_text(text);temporary.replace(path)


def source_fingerprint(root):
    names=["model","data","simulator","forecast","scheduling","policy","metrics","audit","development"]
    files=[Path(root)/f"sail/{name}.py" for name in names]+[Path(root)/"configs/p3_execution_spec.json",Path(root)/"docs/protocol_v1.md"]
    versions={n:importlib.metadata.version(n) for n in ["numpy","networkx","pytest"]}
    hashes={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    return {"sha256":content_hash((hashes,versions)),"files":hashes,"dependencies":versions}


def choose_cached(candidates,lambda_value,mu_value):
    values=[(c,c["awct_ratio"]+lambda_value*(c["predicted_cdi"] if c["predicted_cdi"] is not None else 0)+mu_value*c["churn"]) for c in candidates]
    best=min(s for _,s in values)
    ties=[(c,s) for c,s in values if abs(s-best)<=1e-12]
    return min(ties,key=lambda cs:(cs[0]["churn"],len(cs[0]["scope"]),cs[0]["hop"],tuple(tuple(q) for q in cs[0]["queues"])))[0]


def evaluate_parameters(records,pairs):
    output=[]
    for lambda_value,mu_value in pairs:
        chosen=[choose_cached(r["candidates"],lambda_value,mu_value) for r in records]
        actual=[c["actual"] for c in chosen]
        cdi=[a["cdi"] for a in actual if a["cdi"] is not None]
        relative=sum(a["awct"]/r["B2"]["awct"]-1 for a,r in zip(actual,records))/len(records)
        output.append({"lambda":lambda_value,"mu":mu_value,"scenario_count":len(records),"cdi_defined_scenarios":len(cdi),
                       "cdi":sum(cdi)/len(cdi) if cdi else None,"awct":sum(a["awct"] for a in actual)/len(actual),
                       "churn":sum(a["churn"] for a in actual)/len(actual),"relative_awct_vs_B2":relative,
                       "feasible":relative<=0.05 and bool(cdi),"selected_hops":dict(Counter(c["hop"] for c in chosen))})
    return output


def rank_parameters(rows):
    return sorted((r for r in rows if r["feasible"]),key=lambda r:(r["cdi"],r["awct"],r["churn"],r["lambda"],r["mu"]))


def cache_split(root,split,seeds,fingerprint):
    root=Path(root);folder=root/f"reports/p3/{split}"
    records=[]
    for seed in seeds:
        for mix in ("A","B","C"):
            workload=synthetic_workload(seed,mix)
            for nodes in (4,8):
                for ccr in (0.5,2):
                    base_id=f"{seed}-{mix}-{nodes}-{ccr}"
                    platform=Platform(speed_vector(seed,mix,nodes),bandwidth_for_ccr(workload,ccr))
                    paths=[folder/f"cases/{base_id}-{fraction}.json" for fraction in (0.3,0.6)]
                    if all(p.exists() for p in paths):
                        loaded=[json.loads(p.read_text()) for p in paths]
                        if any(r["source_fingerprint"]!=fingerprint["sha256"] or not r["complete"] for r in loaded):
                            raise ValueError("cache belongs to a different implementation; preserve it and use a new run version")
                        records.extend(loaded);continue
                    initial=initial_heft(workload,platform)
                    online=OnlineReference.from_initial(initial)
                    reference=Simulator(workload,platform,initial.plan).run()
                    audit_result(reference,workload,platform)
                    dump(folder/f"bases/{base_id}.json",{"source_fingerprint":fingerprint["sha256"],"workload":workload,"platform":platform,
                         "initial_plan":initial.plan,"online_reference":online,"actual_no_fault":{"starts":reference.starts,"finishes":reference.finishes,"awct":reference.awct,"makespan":reference.makespan,"trace_sha256":reference.trace_hash}})
                    for fraction,path in zip((0.3,0.6),paths):
                        if path.exists():
                            record=json.loads(path.read_text())
                            if record["source_fingerprint"]!=fingerprint["sha256"]:raise ValueError("mixed cache version")
                            records.append(record);continue
                        fault=Failure(reference.makespan*fraction,failure_node(seed,mix,nodes))
                        b2=Baseline("B2")
                        b2run=Simulator(workload,platform,initial.plan,failure=fault,repair=b2).run()
                        audit_result(b2run,workload,platform,expected_failure=fault,reference=reference)
                        snapshot,context=b2.last_snapshot,b2.last_context
                        generation=generate_candidates(snapshot,context,online)
                        snapshot_key,context_key=content_hash(snapshot),content_hash(context)
                        candidates=[]
                        for c in generation.candidates:
                            def replay(observed,ctx,c=c):
                                if content_hash(observed)!=snapshot_key or content_hash(ctx)!=context_key:raise ValueError("candidate prefix changed")
                                return RepairDecision(c.scope,c.schedule.plan)
                            run=Simulator(workload,platform,initial.plan,failure=fault,repair=replay).run()
                            independent=audit_result(run,workload,platform,expected_failure=fault,reference=reference)
                            actual=paired_metrics(run,reference,workload)
                            if actual["cdi"] is not None and abs(actual["cdi"]-independent["cdi"])>1e-9:raise ValueError("CDI mismatch")
                            candidates.append({"hop":c.hop,"aliases":c.aliases,"scope":c.scope,"queues":c.schedule.plan.queues,
                                               "awct_ratio":c.awct_ratio,"predicted_awct":c.schedule.forecast.awct,"predicted_cdi":c.predicted_cdi,"churn":c.churn,
                                               "actual":actual,"trace_sha256":run.trace_hash,"events_checked":independent["events_checked"]})
                        record={"complete":True,"source_fingerprint":fingerprint["sha256"],"id":f"{base_id}-{fraction}","base_id":base_id,
                                "seed":seed,"mix":mix,"nodes":nodes,"ccr":ccr,"failure_fraction":fraction,"failure_node":fault.node,"failure_time":fault.time,
                                "snapshot_sha256":snapshot_key,"context":context,"protected_count":len(context.P),"Q_count":len(context.Q),"F_count":len(context.F),
                                "unique_scopes":generation.unique_scopes,"unique_plans":generation.unique_plans,"candidates":candidates,
                                "B2":paired_metrics(b2run,reference,workload),"B2_trace_sha256":b2run.trace_hash}
                        dump(path,record);records.append(jsonable(record))
        print(f"{split}: seed {seed} complete, scenarios {len(records)}",flush=True)
    return records


def coverage(records):
    out={}
    for mix in ("A","B","C"):
        rows=[r for r in records if r["mix"]==mix]
        out[mix]={"scenarios":len(rows),"F_nonempty":sum(r["F_count"]>0 for r in rows),"P_nonempty":sum(r["protected_count"]>0 for r in rows),
                  "nondegenerate_plans":sum(r["unique_plans"]>1 for r in rows),
                  "effective_protected_nondegenerate":sum(r["F_count"]>0 and r["protected_count"]>0 and r["unique_plans"]>1 for r in rows)}
    out["single_plan_fraction"]=sum(r["unique_plans"]==1 for r in records)/len(records)
    return out


def run_selection(root):
    root=Path(root);fingerprint=source_fingerprint(root)
    dump(root/"reports/p3/selection_source_manifest.json",fingerprint)
    dev=cache_split(root,"development",range(10000,10020),fingerprint)
    assert len(dev)==480
    table=evaluate_parameters(dev,[(l,m) for l in LAMBDAS for m in MUS])
    shortlist=rank_parameters(table)[:3]
    dump(root/"reports/p3/development_parameter_table.json",table)
    dump(root/"reports/p3/development_shortlist.json",shortlist)
    selected=None;validation_table=[];val=[]
    if shortlist:
        val=cache_split(root,"validation",range(20000,20010),fingerprint)
        assert len(val)==240
        validation_table=evaluate_parameters(val,[(r["lambda"],r["mu"]) for r in shortlist])
        ranking=rank_parameters(validation_table)
        selected=ranking[0] if ranking else None
    if source_fingerprint(root)["sha256"]!=fingerprint["sha256"]:raise ValueError("selection implementation changed during execution")
    result={"status":"SELECTED" if selected else "NO_FEASIBLE_PARAMETER","source_fingerprint":fingerprint,
            "development_scenarios":len(dev),"validation_scenarios":len(val),"shortlist":shortlist,"validation_table":validation_table,"selected":selected,
            "development_coverage":coverage(dev),"validation_coverage":coverage(val) if val else None,
            "formal_test_outcomes_used":False,"rule":"development top three feasible, then independent validation CDI/AWCT/Churn/lambda/mu order"}
    dump(root/"reports/p3/parameter_selection.json",result)
    return result
