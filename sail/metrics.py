"""Offline paired evaluation. Reference traces never enter a policy snapshot."""
from __future__ import annotations

from .model import ModelError


def paired_metrics(result, reference, workload, *, same_fault_b0=None):
    if result.case_key != reference.case_key or reference.context is not None:
        raise ModelError("requires matched no-fault case with identical initial plan and realized environment")
    P = result.context.P if result.context else frozenset()
    starts, base = dict(result.starts), dict(reference.starts)
    signed = None
    if same_fault_b0 is not None:
        if same_fault_b0.case_key != result.case_key or same_fault_b0.context != result.context:
            raise ModelError("B0 reference does not share the failure snapshot")
        if P:
            b0 = dict(same_fault_b0.starts)
            signed = sum(starts[v]-b0[v] for v in P)/len(P)/workload.pbar
    return {"awct":result.awct,"makespan":result.makespan,"churn":result.churn,
            "cdi":sum(max(0.0,starts[v]-base[v]) for v in P)/len(P)/workload.pbar if P else None,
            "protected_count":len(P),"pending_count":len(result.context.Q) if result.context else 0,
            "protected_fraction":len(P)/len(result.context.Q) if result.context and result.context.Q else None,
            "effective_failure":bool(result.context and result.context.F),
            "same_fault_signed_delay":signed,
            "workflow_slowdown":{w:t/dict(reference.workflow_finishes)[w] for w,t in result.workflow_finishes}}
