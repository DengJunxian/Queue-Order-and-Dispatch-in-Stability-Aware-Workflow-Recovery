"""SAIL bounded scopes, candidate reuse, and observation-only selection."""
from __future__ import annotations

import math
from dataclasses import dataclass,replace
from time import perf_counter

from .model import ModelError,RepairDecision,churn
from .scheduling import Schedule,schedule_scope


@dataclass(frozen=True,slots=True)
class OnlineReference:
    mode: str
    awct: float
    starts: tuple[tuple[str,float],...]

    @classmethod
    def from_initial(cls,initial):
        if not isinstance(initial,Schedule) or initial.forecast.mode!="PREDICTED_CONTINUATION":
            raise ModelError("online reference must come from the predicted initial schedule")
        return cls("PREDICTED_NO_FAULT",initial.forecast.awct,initial.forecast.starts)


@dataclass(frozen=True,slots=True)
class Candidate:
    hop: int
    aliases: tuple[int,...]
    schedule: Schedule
    awct_ratio: float
    predicted_cdi: float | None
    churn: float

    @property
    def scope(self): return self.schedule.scope


@dataclass(frozen=True,slots=True)
class CandidateSet:
    candidates: tuple[Candidate,...]
    requested_hops: int
    unique_scopes: int
    unique_plans: int
    protected_count: int


@dataclass(frozen=True,slots=True)
class Selection:
    candidate: Candidate
    score: float
    lambda_value: float
    mu_value: float
    scores: tuple[tuple[int,float],...]


def bounded_scopes(workload,context):
    distance={v:0 for v in context.F}
    successors={v:[] for v in workload.task_map}
    for u,v in workload.edges: successors[u].append(v)
    frontier=set(context.F)
    for depth in (1,2):
        upcoming=set()
        for u in sorted(frontier):
            for v in successors[u]:
                if v not in distance:distance[v]=depth;upcoming.add(v)
        frontier=upcoming
    return tuple(frozenset(v for v,d in distance.items() if d<=hop and v in context.Q) for hop in range(3))


def predicted_cdi(schedule,context,reference,pbar):
    if reference.mode!="PREDICTED_NO_FAULT" or not math.isfinite(reference.awct) or reference.awct<=0:
        raise ModelError("invalid online reference")
    starts,base=dict(schedule.forecast.starts),dict(reference.starts)
    if set(starts)!=set(base):raise ModelError("online reference task IDs differ")
    if not context.P:return None
    return sum(max(0,starts[v]-base[v]) for v in context.P)/len(context.P)/pbar


def generate_candidates(snapshot,context,reference):
    if reference.mode!="PREDICTED_NO_FAULT" or not math.isfinite(reference.awct) or reference.awct<=0:
        raise ModelError("invalid online reference")
    scopes=bounded_scopes(snapshot.workload,context)
    by_scope,by_plan={},{}
    unique=[]
    for hop,scope in enumerate(scopes):
        if scope in by_scope:
            index=by_scope[scope]
            unique[index]=replace(unique[index],aliases=unique[index].aliases+(hop,))
            continue
        schedule=schedule_scope(snapshot,context,scope)
        key=schedule.plan.queues
        if key in by_plan:
            index=by_plan[key]
            if schedule.forecast!=unique[index].schedule.forecast:
                raise ModelError("identical plans produced different forecasts")
            unique[index]=replace(unique[index],aliases=unique[index].aliases+(hop,))
        else:
            index=len(unique);by_plan[key]=index
            unique.append(Candidate(hop,(hop,),schedule,schedule.forecast.awct/reference.awct,
                                    predicted_cdi(schedule,context,reference,snapshot.workload.pbar),churn(context,schedule.plan)))
        by_scope[scope]=index
    return CandidateSet(tuple(unique),3,len(set(scopes)),len(unique),len(context.P))


def select_candidate(candidates,lambda_value,mu_value):
    for weight in (lambda_value,mu_value):
        if isinstance(weight,bool) or not isinstance(weight,(int,float)) or not math.isfinite(weight) or weight<0:
            raise ModelError("weights must be finite and nonnegative")
    if not candidates:raise ModelError("no candidates")
    scored=[(c,c.awct_ratio+lambda_value*(c.predicted_cdi if c.predicted_cdi is not None else 0)+mu_value*c.churn) for c in candidates]
    if any(not math.isfinite(s) for _,s in scored):raise ModelError("nonfinite candidate score")
    minimum=min(s for _,s in scored)
    tied=[(c,s) for c,s in scored if abs(s-minimum)<=1e-12]
    candidate,score=min(tied,key=lambda cs:(cs[0].churn,len(cs[0].scope),cs[0].hop,cs[0].schedule.plan.queues))
    return Selection(candidate,score,lambda_value,mu_value,tuple((c.hop,s) for c,s in scored))


class SAILPolicy:
    def __init__(self,reference,lambda_value,mu_value,variant="SAIL"):
        if variant not in {"SAIL","NoStability","NoChurn"}:raise ModelError("unknown SAIL variant")
        self.reference=reference
        self.lambda_value=0 if variant=="NoStability" else lambda_value
        self.mu_value=0 if variant=="NoChurn" else mu_value
        # Validate even when generation later has a single candidate.
        for w in (self.lambda_value,self.mu_value):
            if isinstance(w,bool) or not isinstance(w,(int,float)) or not math.isfinite(w) or w<0:raise ModelError("invalid weight")
        self.variant=variant
        self.last_candidates=self.last_selection=self.last_snapshot=self.last_context=None
        self.wall_seconds=None

    def __call__(self,snapshot,context):
        start=perf_counter()
        self.last_candidates=generate_candidates(snapshot,context,self.reference)
        self.last_selection=select_candidate(self.last_candidates.candidates,self.lambda_value,self.mu_value)
        self.last_snapshot,self.last_context=snapshot,context
        self.wall_seconds=perf_counter()-start
        c=self.last_selection.candidate
        return RepairDecision(c.scope,c.schedule.plan)


class FixedScopePolicy:
    def __init__(self,hop):
        if hop not in (0,1,2):raise ModelError("fixed hop must be 0, 1 or 2")
        self.hop=hop;self.last_schedule=None;self.wall_seconds=None

    def __call__(self,snapshot,context):
        start=perf_counter()
        self.last_schedule=schedule_scope(snapshot,context,bounded_scopes(snapshot.workload,context)[self.hop])
        self.wall_seconds=perf_counter()-start
        return RepairDecision(self.last_schedule.scope,self.last_schedule.plan)
