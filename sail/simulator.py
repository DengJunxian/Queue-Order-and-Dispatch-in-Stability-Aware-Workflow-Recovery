"""Deterministic event execution with an immutable, observation-only policy API."""
from __future__ import annotations

import hashlib
import heapq
import json
import math
from dataclasses import asdict, dataclass, is_dataclass
from typing import Callable

from .model import (Failure, FailureContext, ModelError, Plan, Platform, RepairDecision,
                    Snapshot, TaskView, Workload, churn, positive, validate_plan, validate_repair)


class SimulationError(RuntimeError):
    pass


def jsonable(value):
    if is_dataclass(value):
        return jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k,v in value.items()}
    if isinstance(value, (set, frozenset)):
        return [jsonable(v) for v in sorted(value)]
    if isinstance(value, (tuple, list)):
        return [jsonable(v) for v in value]
    return value


def content_hash(value):
    return hashlib.sha256(json.dumps(jsonable(value),sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class RunResult:
    case_key: str
    events: tuple[dict, ...]
    starts: tuple[tuple[str,float], ...]
    finishes: tuple[tuple[str,float], ...]
    workflow_finishes: tuple[tuple[str,float], ...]
    makespan: float
    awct: float
    cpu_seconds: float
    wasted_cpu_seconds: float
    wasted_work: float
    transfer_bytes: float
    attempts: tuple[tuple[str,int], ...]
    context: FailureContext | None
    applied_plan: Plan | None
    churn: float

    @property
    def trace_hash(self):
        return content_hash(self.events)


@dataclass
class _State:
    node: int
    status: str = "PENDING"
    attempt: int = 0
    start: float | None = None
    finish: float | None = None
    input_status: str = "WAIT"
    input_token: int = 0
    input_start: float | None = None
    input_total: float = 0.0
    remote_files: tuple[str, ...] = ()


Policy = Callable[[Snapshot,FailureContext],RepairDecision]


class Simulator:
    """One-shot executor. Realized work and future events remain private to executor.

    Policies receive only Snapshot and FailureContext, never this object or a result.
    This is an API information boundary, not a sandbox for hostile Python plugins.
    """

    def __init__(self, workload: Workload, platform: Platform, initial_plan: Plan, *,
                 realized_work=None, failure: Failure | None=None, repair: Policy | None=None):
        validate_plan(workload,platform,initial_plan)
        self.workload, self.platform = workload, platform
        self._tasks, self._files = workload.task_map, workload.file_map
        self._realized = dict(realized_work) if realized_work is not None else {t.id:t.work for t in workload.tasks}
        if set(self._realized) != set(self._tasks):
            raise ModelError("realized work must cover exactly the task IDs")
        for work in self._realized.values():
            positive(work,"realized work")
        if failure is not None and (failure.node >= len(platform.speeds) or repair is None):
            raise ModelError("failure needs an existing node and an explicit repair policy")
        self._failure, self._repair = failure, repair
        self._case_key = content_hash((workload,platform,initial_plan,self._realized))
        self._queues = [list(q) for q in initial_plan.queues]
        self._state = {v:_State(j) for v,j in initial_plan.assignment.items()}
        self._alive = [True] * len(platform.speeds)
        self._busy = [None] * len(platform.speeds)
        self._events, self._log = [], []
        self._sequence = 0
        self._now = 0.0
        self._paused = False
        self._context = None
        self._applied = None
        self._cpu = self._wasted_cpu = self._wasted_work = self._bytes = 0.0
        self._used = False
        self._push(0.0,4,"","WAKE",None)
        if failure:
            self._push(float(failure.time),2,str(failure.node),"FAILURE",failure.node)

    def _push(self,time,priority,key,kind,payload):
        if not math.isfinite(time) or time < self._now:
            raise SimulationError("nonfinite or backward event time")
        self._sequence += 1
        heapq.heappush(self._events,(time,priority,key,self._sequence,kind,payload))

    def _emit(self,kind,task=None,node=None,**details):
        self._log.append({"seq":len(self._log),"time":self._now,"kind":kind,"task":task,"node":node,"details":jsonable(details)})

    def _received(self,state):
        if state.input_status == "PREPARING":
            return min(state.input_total,max(0.0,(self._now-state.input_start)*self.platform.bandwidth))
        if state.input_status in {"READY","CONSUMED"}:
            return state.input_total
        return 0.0

    def snapshot(self):
        views = []
        for v in sorted(self._state):
            s = self._state[v]
            remaining = None
            if s.status == "RUNNING":
                remaining = max(1e-9*self.workload.pbar, self._tasks[v].work/self.platform.speeds[s.node]-(self._now-s.start))
            views.append(TaskView(v,s.status,s.node,s.attempt,s.start,s.finish,remaining,
                                  s.input_status,s.input_token,s.input_total,self._received(s),s.input_start))
        return Snapshot(self._now,self.workload,self.platform,tuple(self._alive),
                        Plan(tuple(tuple(q) for q in self._queues)),tuple(views))

    def _invalidate_inputs(self,v,reason):
        s = self._state[v]
        if s.input_status == "PREPARING":
            amount = self._received(s)
            self._bytes += amount
            self._emit("INPUT_CANCEL",v,s.node,token=s.input_token,bytes=amount,reason=reason)
        elif s.input_status in {"READY","CONSUMED"}:
            self._emit("INPUT_DISCARD",v,s.node,token=s.input_token,reason=reason)
        s.input_status = "WAIT"
        s.input_token += 1
        s.input_start, s.input_total, s.remote_files = None,0.0,()

    def _prepare(self,v):
        s, task = self._state[v], self._tasks[v]
        if s.status != "PENDING" or s.input_status != "WAIT" or not self._alive[s.node]:
            return
        if any(self._state[p].status != "DONE" for p in task.parents):
            return
        remote = []
        for fid in sorted(task.inputs):
            f = self._files[fid]
            if f.producer is None:
                continue
            source = self._state[f.producer].node
            if source != s.node or not self._alive[source]:
                remote.append(fid)
        s.remote_files = tuple(remote)
        s.input_total = sum(self._files[f].size for f in remote)
        s.input_start = self._now
        s.input_status = "PREPARING"
        s.input_token += 1
        self._emit("INPUT_START",v,s.node,token=s.input_token,remote_files=remote,bytes_total=s.input_total)
        if s.input_total == 0:
            self._input_done(v,s.input_token)
        else:
            end = self._now+s.input_total/self.platform.bandwidth
            if end <= self._now:
                raise SimulationError("transfer duration below floating-point time resolution")
            self._push(end,1,v,"INPUT_DONE",(v,s.input_token))

    def _input_done(self,v,token):
        s = self._state[v]
        if s.input_token != token or s.input_status != "PREPARING" or not self._alive[s.node]:
            self._emit("STALE_EVENT",v,event="INPUT_DONE",token=token)
            return
        s.input_status = "READY"
        self._bytes += s.input_total
        self._emit("INPUT_READY",v,s.node,token=token,bytes=s.input_total)

    def _settle(self):
        # Input staging is independent of CPU availability and CPU-only control pause.
        for v in sorted(self._state):
            self._prepare(v)
        if self._paused:
            return
        for j,q in enumerate(self._queues):
            if not self._alive[j] or self._busy[j] is not None or not q:
                continue
            v = q[0]
            s = self._state[v]
            if s.input_status != "READY" or s.status != "PENDING":
                continue
            s.status, s.input_status = "RUNNING","CONSUMED"
            s.start = self._now
            s.attempt += 1
            self._busy[j] = v
            self._emit("CPU_START",v,j,attempt=s.attempt)
            end = self._now+self._realized[v]/self.platform.speeds[j]
            if end <= self._now:
                raise SimulationError("CPU duration below floating-point time resolution")
            self._push(end,0,v,"CPU_DONE",(v,s.attempt))

    def _cpu_done(self,v,attempt):
        s = self._state[v]
        if s.attempt != attempt or s.status != "RUNNING" or not self._alive[s.node]:
            self._emit("STALE_EVENT",v,event="CPU_DONE",attempt=attempt)
            return
        if self._busy[s.node] != v or self._queues[s.node][0] != v:
            raise SimulationError("CPU/queue inconsistency")
        self._cpu += self._now-s.start
        s.status,s.finish = "DONE",self._now
        self._busy[s.node] = None
        self._queues[s.node].pop(0)
        self._emit("CPU_DONE",v,s.node,attempt=attempt)

    def _fail(self,j):
        self._alive[j] = False
        interrupted = self._busy[j]
        if interrupted is not None:
            self._state[interrupted].status = "PENDING"
        Q = frozenset(v for v,s in self._state.items() if s.status == "PENDING")
        F = frozenset(v for v in Q if self._state[v].node == j)
        P = frozenset(v for v in Q-F-self.workload.descendants(F) if self._alive[self._state[v].node])
        old_plan = Plan(tuple(tuple(q) for q in self._queues))
        self._context = FailureContext(self._now,j,Q,F,P,tuple(sorted(old_plan.assignment.items())),old_plan.queues)
        self._paused = True
        self._emit("FAILURE",node=j,context=self._context,control_delay=self._failure.control_delay)
        if interrupted is not None:
            s = self._state[interrupted]
            elapsed = self._now-s.start
            self._cpu += elapsed
            self._wasted_cpu += elapsed
            self._wasted_work += elapsed*self.platform.speeds[j]
            self._emit("CPU_ABORT",interrupted,j,attempt=s.attempt,elapsed=elapsed)
            self._busy[j] = None
        for v in sorted(F):
            self._invalidate_inputs(v,"node_failure")
        self._push(self._now+self._failure.control_delay,3,"repair","APPLY",None)

    def _apply(self):
        snapshot = self.snapshot()
        decision = self._repair(snapshot,self._context)
        if not isinstance(decision,RepairDecision):
            raise ModelError("policy must return RepairDecision")
        validate_repair(snapshot,self._context,decision)
        self._emit("PLAN_APPLIED",scope=decision.scope,queues=decision.plan.queues,
                   churn=churn(self._context,decision.plan))
        for v,j in sorted(decision.plan.assignment.items()):
            s = self._state[v]
            if s.node != j:
                self._invalidate_inputs(v,"reassignment")
                s.node = j
        self._queues = [list(q) for q in decision.plan.queues]
        self._applied = decision.plan
        self._paused = False

    def run(self):
        if self._used:
            raise SimulationError("executor is one-shot")
        self._used = True
        self._emit("RUN_START",queues=self._queues,case_key=self._case_key)
        while self._events:
            self._now = self._events[0][0]
            while self._events and self._events[0][0] == self._now:
                _,_,_,_,kind,payload = heapq.heappop(self._events)
                if kind == "CPU_DONE": self._cpu_done(*payload)
                elif kind == "INPUT_DONE": self._input_done(*payload)
                elif kind == "FAILURE": self._fail(payload)
                elif kind == "APPLY": self._apply()
            self._settle()
        remaining = [v for v,s in self._state.items() if s.status != "DONE"]
        if remaining:
            raise SimulationError(f"deadlock/incomplete run: {remaining}")
        workflow_finishes = {}
        for v,s in self._state.items():
            w = self._tasks[v].workflow
            workflow_finishes[w] = max(workflow_finishes.get(w,0.0),s.finish)
        return RunResult(self._case_key,tuple(self._log),tuple(sorted((v,s.start) for v,s in self._state.items())),
                         tuple(sorted((v,s.finish) for v,s in self._state.items())),tuple(sorted(workflow_finishes.items())),
                         max(workflow_finishes.values()),sum(workflow_finishes.values())/len(workflow_finishes),
                         self._cpu,self._wasted_cpu,self._wasted_work,self._bytes,
                         tuple(sorted((v,s.attempt) for v,s in self._state.items())),self._context,self._applied,
                         churn(self._context,self._applied) if self._context else 0.0)
