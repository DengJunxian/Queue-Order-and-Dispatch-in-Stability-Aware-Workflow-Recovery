"""Reconstruct persisted formal logs and validate complete frozen job coverage."""
import csv
import hashlib
import json
import math
import sys
from collections import Counter
from functools import lru_cache
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from sail.audit import audit_result
from sail.development import dump
from sail.experiment import workload_from_json
from sail.frozen import result_from_json,verify_freeze
from sail.metrics import paired_metrics
from sail.model import Failure,Platform
from sail.policy import bounded_scopes
from sail.scheduling import initial_heft
from sail.simulator import content_hash


def same(a,b):
    if a is None or b is None:return a is b
    return math.isclose(a,b,rel_tol=1e-9,abs_tol=1e-9)


def main():
    freeze=ROOT/"freeze/g2_v1_20261025";out=ROOT/"results/g2_v1_20261025";folder=ROOT/"reports/p4"
    config,manifest=verify_freeze(ROOT,freeze)
    summary=json.loads((out/"execution_summary.json").read_text())
    rows=[json.loads(x) for x in (out/"metrics.jsonl").read_text().splitlines()]
    by_id={r["job_id"]:r for r in rows}
    assert summary["all_complete"] and len(rows)==len(by_id)==len(manifest["jobs"])
    assert set(by_id)=={j["id"] for j in manifest["jobs"]}
    assert not list((out/"failures").glob("*.json")) if (out/"failures").exists() else True
    marker=json.loads((out/"RUN_MANIFEST.json").read_text())
    assert marker["freeze_id"]==hashlib.sha256((freeze/"inputs_manifest.json").read_bytes()).hexdigest()
    unique={r["event_file"]:r["event_sha256"] for r in rows}
    for path,expected in unique.items():assert hashlib.sha256((out/path).read_bytes()).hexdigest()==expected,path
    bases={b["id"]:b for b in manifest["bases"]};scenarios={s["id"]:s for s in manifest["scenarios"]}
    @lru_cache(maxsize=8)
    def inputs(base_id):
        b=bases[base_id];w=workload_from_json(json.loads((freeze/b["workload_file"]).read_text()))
        p=Platform(tuple(b["speeds"]),b["bandwidth"]);truth=json.loads((freeze/b["truth_file"]).read_text())
        initial=initial_heft(w,p)
        ref=result_from_json(json.loads((out/by_id["ref-"+base_id]["event_file"]).read_text()))
        assert [list(q) for q in initial.plan.queues]==ref.events[0]["details"]["queues"]
        return w,p,truth,ref
    @lru_cache(maxsize=12)
    def run(job_id):return result_from_json(json.loads((out/by_id[job_id]["event_file"]).read_text()))
    processed=[];references=[];events=0;physical=0
    context_hashes={}
    for i,row in enumerate(rows):
        w,p,truth,ref=inputs(row["base_id"])
        if row["kind"]=="reference":
            a=audit_result(run(row["job_id"]),w,p,realized_work=truth)
            assert same(row["makespan"],a["makespan"])
            references.append({**bases[row["base_id"]],"makespan":a["makespan"],"awct":a["awct"],"tasks":len(w.tasks)})
            events+=a["events_checked"];physical+=1
        else:
            s=scenarios[row["scenario_id"]]
            for field in ("root_seed","mix","nodes","ccr","failure_fraction","variant"):assert row[field]==s[field]
            if row["status"]=="ALIAS":
                source=by_id[row["execution_alias_of"]]
                assert row["method"]=="NoChurn" and source["method"]=="SAIL" and source["scenario_id"]==row["scenario_id"]
                assert row["event_file"]==source["event_file"] and row["event_sha256"]==source["event_sha256"]
                for field in ("awct","makespan","cdi","churn","protected_count"):assert same(row[field],source[field])
            actual=run(row["job_id"])
            f=Failure(ref.makespan*s["failure_fraction"],s["failed_node"],s["control_delay_pbar_units"]*w.pbar)
            if row["status"]!="ALIAS":
                a=audit_result(actual,w,p,realized_work=truth,expected_failure=f,reference=ref)
                events+=a["events_checked"];physical+=1
                for field in ("awct","makespan","cdi","churn"):assert same(row[field],a[field]),(row["job_id"],field)
            assert actual.context.time==f.time and actual.context.failed_node==f.node
            assert [e for e in actual.events if e["time"]<f.time]==[e for e in ref.events if e["time"]<f.time]
            b0=run(f"run-{s['id']}-B0")
            assert actual.context==b0.context
            values=paired_metrics(actual,ref,w,same_fault_b0=b0)
            if row["method"]!="B0":assert same(values["same_fault_signed_delay"],row["same_fault_signed_delay"])
            old=dict(actual.context.old_assignment);new=actual.applied_plan.assignment
            optional_changes=sum(old[v]!=new[v] for v in actual.context.Q-actual.context.F)
            assert same(row["churn"],optional_changes/max(1,len(actual.context.Q)))
            context_hashes.setdefault(s["id"],set()).add(content_hash(actual.context))
            applied=next(e for e in actual.events if e["kind"]=="PLAN_APPLIED")
            selected_hop=None
            if row["method"] in {"SAIL","NoStability","NoChurn","Fixed_H1","Fixed_H2"}:
                choices=bounded_scopes(w,actual.context)
                matching=[hop for hop,H in enumerate(choices) if set(H)==set(applied["details"]["scope"])]
                assert matching
                selected_hop=min(matching)
            processed.append({**{k:row[k] for k in ("job_id","scenario_id","base_id","method","root_seed","mix","nodes","ccr","failure_fraction","variant","status")},
                              **{k:values[k] for k in ("awct","makespan","cdi","churn","protected_count","pending_count","protected_fraction","effective_failure")},
                              "same_fault_signed_delay":values["same_fault_signed_delay"],"F_count":len(actual.context.F),"scope_size":len(applied["details"]["scope"]),
                              "selected_hop":selected_hop,"optional_node_changes":optional_changes,"tasks":len(w.tasks),"transfer_bytes":actual.transfer_bytes,
                              "cpu_seconds":actual.cpu_seconds,"wasted_cpu_seconds":actual.wasted_cpu_seconds,"wasted_work":actual.wasted_work,
                              "policy_callback_seconds":row["policy_seconds"] if row["status"]=="COMPLETE" else None,
                              "execution_alias_of":row.get("execution_alias_of"),"context_sha256":content_hash(actual.context)})
        if (i+1)%250==0:print(f"persisted audit {i+1}/{len(rows)}",flush=True)
    assert all(len(v)==1 for v in context_hashes.values()) and len(context_hashes)==900
    assert physical==6240 and Counter(r["status"] for r in rows)=={"COMPLETE":6240,"ALIAS":720}
    path=folder/"data/run_metrics.csv";path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("w",newline="") as f:
        writer=csv.DictWriter(f,fieldnames=list(processed[0]));writer.writeheader();writer.writerows(processed)
    dump(folder/"data/run_metrics.json",processed)
    dump(folder/"data/reference_metrics.json",references)
    coverage={}
    for variant in sorted({r["variant"] for r in processed}):
        group=[r for r in processed if r["method"]=="B0" and r["variant"]==variant]
        coverage[variant]={"scenarios":len(group),"F_empty":sum(r["F_count"]==0 for r in group),"P_empty":sum(r["protected_count"]==0 for r in group)}
    result={"status":"PASS","nominal_labels":len(rows),"physical_executions":physical,"alias_records":720,"unique_event_files":len(unique),
            "persisted_event_records_recomputed":events,"scenario_contexts_shared":len(context_hashes),"reference_jobs":len(references),
            "coverage":coverage,"freeze_id":marker["freeze_id"],"raw_metrics_sha256":hashlib.sha256((out/"metrics.jsonl").read_bytes()).hexdigest(),
            "note":"B0 signed delay is derived as zero on nonempty P; stored raw B0 self-reference is NA and remains untouched"}
    dump(folder/"audit_summary.json",result);print(json.dumps(result,ensure_ascii=False))


if __name__=="__main__":main()
