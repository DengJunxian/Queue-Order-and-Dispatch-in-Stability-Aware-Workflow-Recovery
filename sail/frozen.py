"""Checksum-guarded frozen execution. This module does not run on import."""
from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path

from .audit import audit_result
from .development import dump
from .experiment import make_policy,workload_from_json
from .metrics import paired_metrics
from .model import Failure,FailureContext,Plan,Platform
from .policy import OnlineReference
from .scheduling import initial_heft
from .simulator import RunResult,Simulator,content_hash,jsonable


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_freeze(workspace,freeze):
    workspace,freeze=Path(workspace),Path(freeze)
    config=json.loads((freeze/"freeze.json").read_text())
    if config["status"]!="FROZEN_G2":raise ValueError("G2 is not frozen")
    manifest=json.loads((freeze/"inputs_manifest.json").read_text())
    for r in manifest["files"]:
        if digest(freeze/r["path"])!=r["sha256"]:raise ValueError("frozen input hash mismatch: "+r["path"])
    for r in config["code_files"]:
        if digest(workspace/r["path"])!=r["sha256"]:raise ValueError("code changed after G2: "+r["path"])
    return config,json.loads((freeze/"scenario_manifest.json").read_text())


def result_from_json(doc):
    values=dict(doc)
    for field in ("starts","finishes","workflow_finishes","attempts"):
        values[field]=tuple(tuple(p) for p in values[field])
    values["events"]=tuple(values["events"])
    if values["context"] is not None:
        c=values["context"]
        values["context"]=FailureContext(c["time"],c["failed_node"],frozenset(c["Q"]),frozenset(c["F"]),frozenset(c["P"]),
                                          tuple(tuple(p) for p in c["old_assignment"]),tuple(tuple(q) for q in c["original_queues"]))
    if values["applied_plan"] is not None:values["applied_plan"]=Plan(tuple(tuple(q) for q in values["applied_plan"]["queues"]))
    return RunResult(**values)


def execute_frozen(workspace,freeze,output,*,job_limit=None):
    workspace,freeze,output=Path(workspace),Path(freeze),Path(output)
    config,manifest=verify_freeze(workspace,freeze)
    output.mkdir(parents=True,exist_ok=True)
    freeze_id=digest(freeze/"inputs_manifest.json")
    marker=output/"RUN_MANIFEST.json"
    if marker.exists():
        if json.loads(marker.read_text())["freeze_id"]!=freeze_id:raise ValueError("output belongs to another freeze")
    else:dump(marker,{"freeze_id":freeze_id,"purpose":config["purpose"],"nominal_jobs":len(manifest["jobs"])})
    journal=output/"metrics.jsonl"
    records={}
    if journal.exists():
        for line in journal.read_text().splitlines():
            row=json.loads(line)
            if row["job_id"] in records:raise ValueError("duplicate checkpoint row")
            if row["status"] not in {"COMPLETE","ALIAS"}:raise ValueError("failed job retained; repair and version the experiment")
            if digest(output/row["event_file"])!=row["event_sha256"]:raise ValueError("checkpoint event file changed")
            records[row["job_id"]]=row
    bases={b["id"]:b for b in manifest["bases"]};scenarios={s["id"]:s for s in manifest["scenarios"]}
    @lru_cache(maxsize=8)
    def inputs(base_id):
        b=bases[base_id]
        w=workload_from_json(json.loads((freeze/b["workload_file"]).read_text()))
        p=Platform(tuple(b["speeds"]),b["bandwidth"])
        truth=json.loads((freeze/b["truth_file"]).read_text())
        initial=initial_heft(w,p)
        return w,p,truth,initial
    def load_run(job_id):return result_from_json(json.loads((output/records[job_id]["event_file"]).read_text()))
    executed=0
    with journal.open("a") as log:
        for job in manifest["jobs"]:
            jid=job["id"]
            if jid in records:continue
            if job_limit is not None and executed>=job_limit:break
            base_id=job["base_id"];b=bases[base_id]
            try:
                if job["kind"]=="reference":
                    w,p,truth,initial=inputs(base_id)
                    run=Simulator(w,p,initial.plan,realized_work=truth).run()
                    audit_result(run,w,p,realized_work=truth)
                    path=f"events/{jid}.json";dump(output/path,run)
                    row={"job_id":jid,"kind":"reference","base_id":base_id,"status":"COMPLETE","event_file":path,"event_sha256":digest(output/path),"makespan":run.makespan}
                else:
                    s=scenarios[job["scenario_id"]];method=job["method"]
                    row={"job_id":jid,"kind":"failure","scenario_id":s["id"],"base_id":base_id,"method":method,
                         "root_seed":s["root_seed"],"mix":s["mix"],"nodes":s["nodes"],"ccr":s["ccr"],"failure_fraction":s["failure_fraction"],"variant":s["variant"]}
                    alias=config["method_aliases"].get(method)
                    source_id=f"run-{s['id']}-{alias}" if alias else None
                    if source_id in records:
                        source=records[source_id]
                        row={**source,**row,"status":"ALIAS","execution_alias_of":source_id}
                    else:
                        w,p,truth,initial=inputs(base_id)
                        reference=load_run(f"ref-{base_id}")
                        f=Failure(reference.makespan*s["failure_fraction"],s["failed_node"],s["control_delay_pbar_units"]*w.pbar)
                        policy=make_policy(method,OnlineReference.from_initial(initial),config["selected_lambda"],config["selected_mu"])
                        run=Simulator(w,p,initial.plan,realized_work=truth,failure=f,repair=policy).run()
                        independent=audit_result(run,w,p,realized_work=truth,expected_failure=f,reference=reference)
                        b0id=f"run-{s['id']}-B0"
                        b0=load_run(b0id) if b0id in records else None
                        if b0 is not None and b0.context!=run.context:raise ValueError("baseline contexts differ")
                        metrics=paired_metrics(run,reference,w,same_fault_b0=b0)
                        path=f"events/{jid}.json";dump(output/path,run)
                        row.update({"status":"COMPLETE","execution_alias_of":None,"event_file":path,"event_sha256":digest(output/path),
                                    **metrics,"events_checked":independent["events_checked"],"context_sha256":content_hash(run.context),"policy_seconds":policy.wall_seconds})
                log.write(json.dumps(jsonable(row),ensure_ascii=False,allow_nan=False)+"\n");log.flush()
                records[jid]=row;executed+=1
            except Exception as exc:
                dump(output/f"failures/{jid}.json",{"job":job,"status":"FAILED","error":repr(exc)})
                raise
            if config["purpose"]=="FORMAL_MAIN" and (executed%25==0 or len(records)==len(manifest["jobs"])):
                state=json.loads((workspace/"project_state.json").read_text())
                state.update({"current_stage":"P4_RUNS_COMPLETE" if len(records)==len(manifest["jobs"]) else "P4_RUNNING",
                              "formal_runs_completed":len(records),"formal_actual_executions":sum(r["status"]=="COMPLETE" for r in records.values()),
                              "formal_alias_records":sum(r["status"]=="ALIAS" for r in records.values())})
                dump(workspace/"project_state.json",state)
            if executed%25==0:print(f"frozen execution {len(records)}/{len(manifest['jobs'])}",flush=True)
    summary={"purpose":config["purpose"],"completed_labels":len(records),"nominal_jobs":len(manifest["jobs"]),
             "actual_executions":sum(r["status"]=="COMPLETE" for r in records.values()),"alias_records":sum(r["status"]=="ALIAS" for r in records.values()),
             "all_complete":len(records)==len(manifest["jobs"]),"freeze_id":freeze_id}
    dump(output/"execution_summary.json",summary)
    return summary
