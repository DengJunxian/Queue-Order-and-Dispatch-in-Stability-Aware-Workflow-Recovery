"""Immutable public model and plan contracts; no latent execution outcomes."""
from __future__ import annotations

import heapq
import math
from dataclasses import dataclass


class ModelError(ValueError):
    pass


def positive(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ModelError(f"{label} must be finite and positive")


def topological(ids, edges):
    ids = set(ids)
    successors = {v: set() for v in ids}
    degree = dict.fromkeys(ids, 0)
    for u, v in edges:
        if u not in ids or v not in ids:
            raise ModelError(f"unknown dependency: {u}->{v}")
        if v not in successors[u]:
            successors[u].add(v)
            degree[v] += 1
    ready = [v for v in ids if degree[v] == 0]
    heapq.heapify(ready)
    order = []
    while ready:
        v = heapq.heappop(ready)
        order.append(v)
        for child in sorted(successors[v]):
            degree[child] -= 1
            if degree[child] == 0:
                heapq.heappush(ready, child)
    if len(order) != len(ids):
        raise ModelError("logical dependencies plus resource queues contain a cycle")
    return tuple(order)


@dataclass(frozen=True, slots=True)
class Task:
    id: str
    workflow: str
    work: float
    parents: tuple[str, ...] = ()
    inputs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DataFile:
    id: str
    size: float
    producer: str | None


@dataclass(frozen=True, slots=True)
class Workload:
    tasks: tuple[Task, ...]
    files: tuple[DataFile, ...] = ()

    def __post_init__(self):
        if not isinstance(self.tasks, tuple) or not isinstance(self.files, tuple) or not self.tasks:
            raise ModelError("workload requires nonempty immutable task tuple and file tuple")
        tasks, files = self.task_map, self.file_map
        if len(tasks) != len(self.tasks) or len(files) != len(self.files):
            raise ModelError("duplicate task/file ID")
        for t in self.tasks:
            if not isinstance(t.id, str) or not t.id or not isinstance(t.workflow, str) or not t.workflow:
                raise ModelError("task and workflow IDs must be nonempty strings")
            positive(t.work, "work")
            if not isinstance(t.parents, tuple) or not isinstance(t.inputs, tuple):
                raise ModelError("task relationships must be tuples")
            if len(set(t.parents)) != len(t.parents) or len(set(t.inputs)) != len(t.inputs):
                raise ModelError("duplicate dependency/input")
            if any(p not in tasks for p in t.parents) or any(f not in files for f in t.inputs):
                raise ModelError("missing dependency/input")
            if any(tasks[p].workflow != t.workflow for p in t.parents):
                raise ModelError("protocol v1 workflows must be logically independent")
        self.topological_order()
        for f in self.files:
            if not isinstance(f.id, str) or not f.id or isinstance(f.size, bool) or not isinstance(f.size, (float, int)) or not math.isfinite(f.size) or f.size < 0:
                raise ModelError("invalid file ID/size")
            if f.producer is not None and f.producer not in tasks:
                raise ModelError("unknown file producer")
        for t in self.tasks:
            for fid in t.inputs:
                producer = files[fid].producer
                if producer is not None and producer not in t.parents:
                    raise ModelError("internal file requires an explicit producer dependency")

    @property
    def task_map(self):
        return {t.id: t for t in self.tasks}

    @property
    def file_map(self):
        return {f.id: f for f in self.files}

    @property
    def pbar(self):
        return sum(t.work for t in self.tasks) / len(self.tasks)

    @property
    def edges(self):
        return tuple((p, t.id) for t in self.tasks for p in t.parents)

    def topological_order(self):
        return topological(self.task_map, self.edges)

    def descendants(self, roots):
        reached = set(roots)
        changed = True
        while changed:
            changed = False
            for u, v in self.edges:
                if u in reached and v not in reached:
                    reached.add(v)
                    changed = True
        return frozenset(reached - set(roots))


@dataclass(frozen=True, slots=True)
class Platform:
    speeds: tuple[float, ...]
    bandwidth: float

    def __post_init__(self):
        if not isinstance(self.speeds, tuple) or not self.speeds:
            raise ModelError("nonempty immutable speeds required")
        for speed in self.speeds:
            positive(speed, "speed")
        positive(self.bandwidth, "bandwidth")


@dataclass(frozen=True, slots=True)
class Plan:
    queues: tuple[tuple[str, ...], ...]

    def __post_init__(self):
        if not isinstance(self.queues, tuple) or any(not isinstance(q, tuple) for q in self.queues):
            raise ModelError("plan queues must be tuples")

    @property
    def assignment(self):
        return {v: j for j, q in enumerate(self.queues) for v in q}


@dataclass(frozen=True, slots=True)
class Failure:
    time: float
    node: int
    control_delay: float = 0.0

    def __post_init__(self):
        for value in [self.time, self.control_delay]:
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value < 0:
                raise ModelError("failure time/delay must be finite nonnegative values")
        if isinstance(self.node, bool) or not isinstance(self.node, int) or self.node < 0:
            raise ModelError("invalid failed node")


@dataclass(frozen=True, slots=True)
class TaskView:
    id: str
    status: str
    node: int
    attempt: int
    observed_start: float | None
    observed_finish: float | None
    estimated_remaining: float | None
    input_status: str
    input_token: int
    input_bytes_total: float
    input_bytes_received: float
    input_started: float | None


@dataclass(frozen=True, slots=True)
class Snapshot:
    time: float
    workload: Workload
    platform: Platform
    alive: tuple[bool, ...]
    plan: Plan
    tasks: tuple[TaskView, ...]

    @property
    def completed(self):
        return frozenset(t.id for t in self.tasks if t.status == "DONE")

    @property
    def running(self):
        return frozenset(t.id for t in self.tasks if t.status == "RUNNING")

    @property
    def pending(self):
        return frozenset(t.id for t in self.tasks if t.status == "PENDING")


@dataclass(frozen=True, slots=True)
class FailureContext:
    time: float
    failed_node: int
    Q: frozenset[str]
    F: frozenset[str]
    P: frozenset[str]
    old_assignment: tuple[tuple[str, int], ...]
    original_queues: tuple[tuple[str, ...], ...]


@dataclass(frozen=True, slots=True)
class RepairDecision:
    scope: frozenset[str]
    plan: Plan


def validate_plan(workload, platform, plan, *, completed=frozenset(), alive=None, running=None):
    if len(plan.queues) != len(platform.speeds):
        raise ModelError("wrong number of node queues")
    alive = alive if alive is not None else tuple(True for _ in platform.speeds)
    running = running or {}
    flat = [v for q in plan.queues for v in q]
    expected = set(workload.task_map) - set(completed)
    if len(flat) != len(set(flat)) or set(flat) != expected:
        raise ModelError("plan must contain every unfinished task exactly once")
    for j, q in enumerate(plan.queues):
        if not alive[j] and q:
            raise ModelError("failed node has planned tasks")
        if j in running and (not q or q[0] != running[j]):
            raise ModelError("healthy running task must remain at queue head on the same node")
    edges = [(u, v) for u, v in workload.edges if u in expected and v in expected]
    edges.extend((u, v) for q in plan.queues for u, v in zip(q, q[1:]))
    topological(expected, edges)


def validate_repair(snapshot, context, decision):
    if not isinstance(decision.scope, frozenset) or not context.F <= decision.scope <= context.Q:
        raise ModelError("repair scope must be immutable, contain F, and be contained in Q")
    running = {t.node: t.id for t in snapshot.tasks if t.status == "RUNNING"}
    validate_plan(snapshot.workload, snapshot.platform, decision.plan,
                  completed=snapshot.completed, alive=snapshot.alive, running=running)
    new, old = decision.plan.assignment, dict(context.old_assignment)
    fixed = context.Q - decision.scope
    if any(new[v] != old[v] for v in fixed):
        raise ModelError("assignment outside H changed")
    for qold, qnew in zip(context.original_queues, decision.plan.queues):
        if tuple(v for v in qold if v in fixed) != tuple(v for v in qnew if v in fixed):
            raise ModelError("relative queue order outside H changed")


def churn(context, plan):
    old, new = dict(context.old_assignment), plan.assignment
    return sum(new[v] != old[v] for v in context.Q - context.F) / max(1, len(context.Q))
