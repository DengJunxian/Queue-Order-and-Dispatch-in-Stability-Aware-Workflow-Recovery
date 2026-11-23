"""Protocol v1 common rank/EFT insertion kernel and the three scope baselines."""
from __future__ import annotations

import heapq
import math
from dataclasses import dataclass
from time import perf_counter

from .forecast import Forecast, forecast_plan
from .model import (FailureContext, ModelError, Plan, RepairDecision, Snapshot, TaskView,
                    topological, validate_plan, validate_repair)


@dataclass(frozen=True, slots=True)
class Slot:
    node: int
    position: int
    input_ready: float
    start: float
    finish: float


@dataclass(frozen=True, slots=True)
class Placement:
    task: str
    rank: float
    candidates: tuple[Slot, ...]
    chosen: Slot


@dataclass(frozen=True, slots=True)
class Schedule:
    kernel: str
    scope: frozenset[str]
    plan: Plan
    ranks: tuple[tuple[str,float], ...]
    placements: tuple[Placement, ...]
    forecast: Forecast


def initial_snapshot(workload,platform):
    order = workload.topological_order()
    seed_plan = Plan((order,)+tuple(() for _ in platform.speeds[1:]))
    views = tuple(TaskView(v,"PENDING",0,0,None,None,None,"WAIT",0,0.0,0.0,None) for v in sorted(order))
    return Snapshot(0.0,workload,platform,tuple(True for _ in platform.speeds),seed_plan,views)


def upward_ranks(workload,platform,alive):
    nodes = [j for j,live in enumerate(alive) if live]
    if not nodes:
        raise ModelError("rank needs a live node")
    successors = {t.id:[] for t in workload.tasks}
    sizes = {}
    files = workload.file_map
    for t in workload.tasks:
        for p in t.parents:
            successors[p].append(t.id)
            sizes[p,t.id] = sum(files[f].size for f in t.inputs if files[f].producer==p)
    rank = {}
    for v in reversed(workload.topological_order()):
        mean_compute = sum(workload.task_map[v].work/platform.speeds[j] for j in nodes)/len(nodes)
        rank[v] = mean_compute+max((sizes[v,c]/platform.bandwidth+rank[c] for c in successors[v]),default=0.0)
    return rank


def _input_ready(v,node,snapshot,views,assignment,finishes,tasks,files):
    view = views[v]
    if node==view.node:
        if view.input_status=="READY":
            return snapshot.time
        if view.input_status=="PREPARING":
            return snapshot.time+(view.input_bytes_total-view.input_bytes_received)/snapshot.platform.bandwidth
    dependency_ready = max([snapshot.time]+[finishes[p] for p in tasks[v].parents])
    remote = sum(files[f].size for f in tasks[v].inputs if files[f].producer is not None and
                 (assignment[files[f].producer]!=node or not snapshot.alive[assignment[files[f].producer]]))
    return dependency_ready+remote/snapshot.platform.bandwidth


def _first_slot(node,intervals,ready,work,speed):
    duration = work/speed
    left = ready
    for position in range(len(intervals)+1):
        if position:
            left = max(ready,intervals[position-1][2])
        end = left+duration
        if not math.isfinite(end) or end<=left:
            raise ModelError("unrepresentable predicted CPU duration")
        if position==len(intervals) or end<=intervals[position][1]:
            return Slot(node,position,ready,left,end)
    raise ModelError("no finite insertion slot")


def schedule_scope(snapshot: Snapshot,context: FailureContext | None,scope: frozenset[str]) -> Schedule:
    tasks,files = snapshot.workload.task_map,snapshot.workload.file_map
    Q = snapshot.pending
    if not isinstance(scope,frozenset) or not scope<=Q:
        raise ModelError("scope must be an immutable subset of pending tasks")
    if context is None:
        if snapshot.completed or snapshot.running or scope!=Q:
            raise ModelError("initial scheduling requires all-pending scope")
    elif context.Q!=Q or not context.F<=scope:
        raise ModelError("repair must use the frozen Q and include F")
    views = {v.id:v for v in snapshot.tasks}
    if set(views)!=set(tasks) or len(views)!=len(snapshot.tasks):
        raise ModelError("snapshot task coverage mismatch")
    alive = [j for j,a in enumerate(snapshot.alive) if a]
    if not alive:
        raise ModelError("no healthy execution node")
    ranks = upward_ranks(snapshot.workload,snapshot.platform,snapshot.alive)
    # Logical precedence is kept separate from zero-communication anchor order.
    predecessors = {v:set(tasks[v].parents)&set(Q) for v in Q}
    fixed = Q-scope
    for q in snapshot.plan.queues:
        anchors = [v for v in q if v in fixed]
        for a,b in zip(anchors,anchors[1:]): predecessors[b].add(a)
    topological(Q,((p,v) for v in Q for p in predecessors[v]))
    successors = {v:set() for v in Q}
    for v in Q:
        for p in predecessors[v]: successors[p].add(v)
    assignment,starts,finishes = {},{},{}
    intervals = [[] for _ in snapshot.platform.speeds]
    for v in sorted(snapshot.completed | snapshot.running):
        view = views[v]
        assignment[v],starts[v] = view.node,view.observed_start
        if view.status=="DONE":
            finishes[v] = view.observed_finish
        else:
            if not snapshot.alive[view.node] or view.estimated_remaining is None or view.estimated_remaining<=0:
                raise ModelError("invalid healthy running reservation")
            finishes[v] = snapshot.time+view.estimated_remaining
            intervals[view.node].append((v,snapshot.time,finishes[v]))
    ready = [(-ranks[v],tasks[v].workflow,v) for v in Q if not predecessors[v]]
    heapq.heapify(ready)
    placed,trace = set(),[]
    while ready:
        _,_,v = heapq.heappop(ready)
        choices = alive if v in scope else [views[v].node]
        slots = []
        for node in choices:
            if not snapshot.alive[node]:
                raise ModelError("frozen task was assigned to a failed node outside H")
            input_ready = _input_ready(v,node,snapshot,views,assignment,finishes,tasks,files)
            cpu_ready = max([snapshot.time,input_ready]+[finishes[p] for p in predecessors[v]])
            slot = _first_slot(node,intervals[node],cpu_ready,tasks[v].work,snapshot.platform.speeds[node])
            # Preserve physical input readiness in the trace, excluding queue-only constraints.
            slots.append(Slot(slot.node,slot.position,input_ready,slot.start,slot.finish))
        chosen = min(slots,key=lambda s:(s.finish,s.start,s.node,s.position))
        assignment[v],starts[v],finishes[v] = chosen.node,chosen.start,chosen.finish
        intervals[chosen.node].insert(chosen.position,(v,chosen.start,chosen.finish))
        trace.append(Placement(v,ranks[v],tuple(slots),chosen))
        placed.add(v)
        for child in sorted(successors[v]):
            if predecessors[child]<=placed:
                heapq.heappush(ready,(-ranks[child],tasks[child].workflow,child))
    if placed!=set(Q):
        raise ModelError("scheduling stopped before all pending tasks were placed")
    plan = Plan(tuple(tuple(v for v,_,_ in row) for row in intervals))
    if context is None:
        validate_plan(snapshot.workload,snapshot.platform,plan)
    else:
        validate_repair(snapshot,context,RepairDecision(scope,plan))
    forecast = forecast_plan(snapshot,plan)
    # The fixed interval construction must agree with the shared execution semantics.
    predicted_start,predicted_finish = dict(forecast.starts),dict(forecast.finishes)
    for v in Q:
        if not math.isclose(starts[v],predicted_start[v],rel_tol=1e-10,abs_tol=1e-9) or not math.isclose(finishes[v],predicted_finish[v],rel_tol=1e-10,abs_tol=1e-9):
            raise ModelError(f"placement/forecast disagreement for {v}")
    return Schedule("protocol_v1_HEFT_EFT",scope,plan,tuple(sorted(ranks.items())),tuple(trace),forecast)


def initial_heft(workload,platform):
    snapshot = initial_snapshot(workload,platform)
    return schedule_scope(snapshot,None,snapshot.pending)


def baseline_scope(name,workload,context):
    if name=="B0": return context.F
    if name=="B1": return context.F | (workload.descendants(context.F) & context.Q)
    if name=="B2": return context.Q
    raise ModelError("baseline must be B0, B1 or B2")


class Baseline:
    """All three policies differ only in the set passed to schedule_scope."""

    def __init__(self,name):
        if name not in {"B0","B1","B2"}: raise ModelError("unknown baseline")
        self.name = name
        self.last_snapshot = self.last_context = self.last_schedule = None
        self.wall_seconds = None

    def __call__(self,snapshot,context):
        begin = perf_counter()
        self.last_schedule = schedule_scope(snapshot,context,baseline_scope(self.name,snapshot.workload,context))
        self.wall_seconds = perf_counter()-begin
        self.last_snapshot,self.last_context = snapshot,context
        return RepairDecision(self.last_schedule.scope,self.last_schedule.plan)
