"""Exploratory controls separating queue order from optional assignment changes.

The rank/EFT traversal is a small, explicit fork of sail.scheduling.schedule_scope.
It removes outside-scope queue anchors and enforces an integer assignment budget.
The original implementation is never modified.
"""
import heapq
import math
from dataclasses import dataclass
from types import SimpleNamespace

from sail.forecast import forecast_plan
from sail.model import ModelError,Plan,RepairDecision,churn,validate_repair
from sail.policy import generate_candidates,predicted_cdi
from sail.scheduling import _first_slot,_input_ready,upward_ranks,schedule_scope


@dataclass(frozen=True)
class BudgetSchedule:
    plan: Plan
    forecast: object
    optional_moves: int
    cap: int | None


def budget_schedule(snapshot,context,theta):
    if theta is not None and (isinstance(theta,bool) or not isinstance(theta,(int,float)) or not math.isfinite(theta) or not 0<=theta<=1):
        raise ModelError('theta must be in [0,1] or None for an uncapped control')
    if snapshot.pending!=context.Q:raise ModelError('pending population differs from original Q')
    cap=None if theta is None else math.floor(theta*max(1,len(context.Q)))
    tasks=snapshot.workload.task_map;files=snapshot.workload.file_map;views={t.id:t for t in snapshot.tasks}
    alive=[j for j,a in enumerate(snapshot.alive) if a];Q=context.Q
    if not alive:raise ModelError('no healthy node')
    ranks=upward_ranks(snapshot.workload,snapshot.platform,snapshot.alive)
    predecessors={v:set(tasks[v].parents)&set(Q) for v in Q}
    successors={v:set() for v in Q}
    for v in Q:
        for p in predecessors[v]:successors[p].add(v)
    assignment={};starts={};finishes={};intervals=[[] for _ in snapshot.platform.speeds]
    for v in sorted(snapshot.completed|snapshot.running):
        view=views[v];assignment[v]=view.node;starts[v]=view.observed_start
        if view.status=='DONE':finishes[v]=view.observed_finish
        else:
            if not snapshot.alive[view.node] or view.estimated_remaining is None or view.estimated_remaining<=0:raise ModelError('invalid running reservation')
            finishes[v]=snapshot.time+view.estimated_remaining;intervals[view.node].append((v,snapshot.time,finishes[v]))
    ready=[(-ranks[v],tasks[v].workflow,v) for v in Q if not predecessors[v]];heapq.heapify(ready)
    placed=set();moves=0
    while ready:
        _,_,v=heapq.heappop(ready);old=views[v].node
        choices=alive if v in context.F or cap is None or moves<cap else [old]
        slots=[]
        for node in choices:
            if not snapshot.alive[node]:raise ModelError('healthy assignment required')
            data_ready=_input_ready(v,node,snapshot,views,assignment,finishes,tasks,files)
            cpu_ready=max([snapshot.time,data_ready]+[finishes[p] for p in predecessors[v]])
            slots.append(_first_slot(node,intervals[node],cpu_ready,tasks[v].work,snapshot.platform.speeds[node]))
        slot=min(slots,key=lambda s:(s.finish,s.start,s.node,s.position))
        if v not in context.F and slot.node!=old:moves+=1
        assignment[v]=slot.node;starts[v]=slot.start;finishes[v]=slot.finish
        intervals[slot.node].insert(slot.position,(v,slot.start,slot.finish));placed.add(v)
        for child in sorted(successors[v]):
            if predecessors[child]<=placed:heapq.heappush(ready,(-ranks[child],tasks[child].workflow,child))
    if placed!=set(Q):raise ModelError('incomplete budget schedule')
    plan=Plan(tuple(tuple(v for v,_,_ in q) for q in intervals))
    validate_repair(snapshot,context,RepairDecision(Q,plan))
    actual_moves=sum(plan.assignment[v]!=dict(context.old_assignment)[v] for v in Q-context.F)
    if actual_moves!=moves or (cap is not None and moves>cap):raise ModelError('budget accounting mismatch')
    forecast=forecast_plan(snapshot,plan)
    for v in Q:
        if not math.isclose(starts[v],dict(forecast.starts)[v],abs_tol=1e-9,rel_tol=1e-10):raise ModelError('placement/forecast mismatch')
    return BudgetSchedule(plan,forecast,moves,cap)


class BudgetPolicy:
    def __init__(self,theta):self.theta=theta;self.last_schedule=None
    def __call__(self,snapshot,context):
        self.last_schedule=budget_schedule(snapshot,context,self.theta)
        return RepairDecision(context.Q,self.last_schedule.plan)


class BudgetSelect:
    def __init__(self,reference,theta=.1):
        self.reference=reference;self.theta=theta;self.last_candidates=None;self.last_selected=None;self.last_quality_feasible=None
    def __call__(self,snapshot,context):
        cap=math.floor(self.theta*max(1,len(context.Q)))
        generation=generate_candidates(snapshot,context,self.reference)
        plans=[(f'v1_H{c.hop}',c.schedule.plan,c.schedule.forecast) for c in generation.candidates]
        for name,theta in (('QueueRepair0',0),('BudgetHEFT10',self.theta)):
            s=budget_schedule(snapshot,context,theta);plans.append((name,s.plan,s.forecast))
        b2=schedule_scope(snapshot,context,context.Q);plans.append(('B2',b2.plan,b2.forecast))
        candidates=[];seen=set()
        for name,plan,forecast in plans:
            if plan.queues in seen:continue
            seen.add(plan.queues)
            moves=sum(plan.assignment[v]!=dict(context.old_assignment)[v] for v in context.Q-context.F)
            if moves>cap:continue
            cdi=predicted_cdi(SimpleNamespace(forecast=forecast),context,self.reference,snapshot.workload.pbar)
            candidates.append({'name':name,'plan':plan,'awct':forecast.awct,'cdi':cdi,'churn':churn(context,plan),
                               'quality_feasible':forecast.awct<=1.05*b2.forecast.awct})
        if not candidates:raise ModelError('no budget-feasible plan including mandatory-only candidate')
        feasible=[c for c in candidates if c['quality_feasible']]
        key=(lambda c:(c['cdi'] if c['cdi'] is not None else 0,c['awct'],c['churn'],c['name'],c['plan'].queues)) if feasible else (
             lambda c:(c['awct'],c['cdi'] if c['cdi'] is not None else 0,c['churn'],c['name'],c['plan'].queues))
        chosen=min(feasible or candidates,key=key)
        self.last_candidates=candidates;self.last_selected=chosen;self.last_quality_feasible=bool(feasible)
        return RepairDecision(context.Q,chosen['plan'])
