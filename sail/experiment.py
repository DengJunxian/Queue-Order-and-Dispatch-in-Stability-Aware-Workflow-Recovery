"""Evaluator-owned experiment orchestration; policies receive predicted references only."""
from __future__ import annotations

from pathlib import Path
from time import perf_counter

from .audit import audit_result
from .development import dump
from .metrics import paired_metrics
from .model import DataFile,Platform,Task,Workload
from .policy import FixedScopePolicy,OnlineReference,SAILPolicy
from .scheduling import Baseline
from .simulator import Simulator,content_hash

METHODS=("B0","B1","B2","SAIL","NoStability","NoChurn","Fixed_H1","Fixed_H2")


def method_aliases(lambda_value,mu_value):
    aliases={"Fixed_H0":"B0"}
    if lambda_value==0:aliases["NoStability"]="SAIL"
    if mu_value==0:aliases["NoChurn"]="SAIL"
    return aliases


def make_policy(name,online_reference,lambda_value,mu_value):
    if name in {"B0","B1","B2"}:return Baseline(name)
    if name in {"SAIL","NoStability","NoChurn"}:return SAILPolicy(online_reference,lambda_value,mu_value,name)
    if name in {"Fixed_H0","Fixed_H1","Fixed_H2"}:return FixedScopePolicy(int(name[-1]))
    raise ValueError("unknown research method")


def workload_from_json(doc):
    return Workload(tuple(Task(t["id"],t["workflow"],t["work"],tuple(t["parents"]),tuple(t["inputs"])) for t in doc["tasks"]),
                    tuple(DataFile(f["id"],f["size"],f["producer"]) for f in doc["files"]))


def run_methods(workload,platform,initial,reference,truth,fault,lambda_value,mu_value,*,methods=METHODS,output=None,reuse_aliases=False):
    online=OnlineReference.from_initial(initial)
    aliases=method_aliases(lambda_value,mu_value)
    rows,runs={},{}
    for method in methods:
        if reuse_aliases and method in aliases and aliases[method] in runs:
            source=aliases[method]
            runs[method]=runs[source]
            rows[method]={**rows[source],"method":method,"execution_alias_of":source,"policy_seconds":0.0,"total_seconds":0.0,"event_file":rows[source]["event_file"]}
            continue
        start=perf_counter()
        policy=make_policy(method,online,lambda_value,mu_value)
        run=Simulator(workload,platform,initial.plan,realized_work=truth,failure=fault,repair=policy).run()
        independent=audit_result(run,workload,platform,realized_work=truth,expected_failure=fault,reference=reference)
        values=paired_metrics(run,reference,workload,same_fault_b0=runs.get("B0"))
        if values["cdi"] is not None and abs(values["cdi"]-independent["cdi"])>1e-9:raise ValueError("CDI replay mismatch")
        if runs and run.context!=next(iter(runs.values())).context:raise ValueError("methods did not share a failure context")
        event_file=None
        if output is not None:
            path=Path(output)/f"{method}.json";dump(path,run);event_file=str(path)
        diagnostic={}
        if isinstance(policy,SAILPolicy):
            diagnostic={"selected_hop":policy.last_selection.candidate.hop,"unique_plans":policy.last_candidates.unique_plans,
                        "unique_scopes":policy.last_candidates.unique_scopes,"selection_score":policy.last_selection.score}
        rows[method]={"method":method,**values,"trace_sha256":run.trace_hash,"context_sha256":content_hash(run.context),
                      "events_checked":independent["events_checked"],"policy_seconds":policy.wall_seconds,
                      "total_seconds":perf_counter()-start,"event_file":event_file,"execution_alias_of":None,**diagnostic}
        runs[method]=run
    return rows,runs
