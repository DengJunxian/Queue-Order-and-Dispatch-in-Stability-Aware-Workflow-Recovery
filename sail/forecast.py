"""Predicted continuation using the P1 event engine and only public observations."""
from __future__ import annotations

from dataclasses import dataclass

from .model import ModelError, Plan, Snapshot, positive, validate_plan
from .simulator import Simulator, _State, content_hash


@dataclass(frozen=True, slots=True)
class Forecast:
    mode: str
    starts: tuple[tuple[str,float], ...]
    finishes: tuple[tuple[str,float], ...]
    workflow_finishes: tuple[tuple[str,float], ...]
    makespan: float
    awct: float


class _PredictedExecutor(Simulator):
    """Seed the shared transition engine; never copy an actual executor instance.

    Partial logs/accounting are internal. Only predicted starts/finishes are exposed.
    """

    def __init__(self,snapshot: Snapshot,plan: Plan):
        views = {v.id:v for v in snapshot.tasks}
        if set(views)!=set(snapshot.workload.task_map) or len(views)!=len(snapshot.tasks):
            raise ModelError("snapshot must cover every task exactly once")
        running = {v.node:v.id for v in snapshot.tasks if v.status=="RUNNING"}
        validate_plan(snapshot.workload,snapshot.platform,plan,completed=snapshot.completed,
                      alive=snapshot.alive,running=running)
        self.workload,self.platform = snapshot.workload,snapshot.platform
        self._tasks,self._files = self.workload.task_map,self.workload.file_map
        self._realized = {v:t.work for v,t in self._tasks.items()}
        self._failure,self._repair = None,None
        self._case_key = content_hash(("predicted_continuation",snapshot,plan))
        self._queues = [list(q) for q in plan.queues]
        self._state = {}
        self._alive = list(snapshot.alive)
        self._busy = [None]*len(self.platform.speeds)
        self._events,self._log = [],[]
        self._sequence = 0
        self._now = snapshot.time
        self._paused,self._context,self._applied,self._used = False,None,None,False
        self._cpu = self._wasted_cpu = self._wasted_work = self._bytes = 0.0
        self._push(snapshot.time,4,"","WAKE",None)
        for v,t in views.items():
            node = t.node if t.status=="DONE" else plan.assignment[v]
            s = _State(node,status=t.status,attempt=t.attempt,start=t.observed_start,finish=t.observed_finish)
            self._state[v] = s
            if t.status=="DONE":
                if t.observed_finish is None or t.observed_start is None or t.observed_finish>snapshot.time:
                    raise ModelError("completed snapshot task lacks observed history")
            elif t.status=="RUNNING":
                positive(t.estimated_remaining,"estimated remaining")
                if t.observed_start is None or t.observed_start>snapshot.time:
                    raise ModelError("running task lacks observed start")
                self._busy[node] = v
                self._push(snapshot.time+t.estimated_remaining,0,v,"CPU_DONE",(v,t.attempt))
            elif t.status=="PENDING":
                if node==t.node and t.input_status in {"PREPARING","READY"}:
                    if not 0<=t.input_bytes_received<=t.input_bytes_total:
                        raise ModelError("invalid observed input progress")
                    s.input_status,s.input_token = t.input_status,t.input_token
                    s.input_total = t.input_bytes_total
                    s.input_start = snapshot.time-t.input_bytes_received/self.platform.bandwidth
                    if t.input_status=="PREPARING":
                        end = snapshot.time+(t.input_bytes_total-t.input_bytes_received)/self.platform.bandwidth
                        self._push(end,1,v,"INPUT_DONE",(v,t.input_token))
            else:
                raise ModelError("unknown snapshot task state")


def forecast_plan(snapshot: Snapshot,plan: Plan) -> Forecast:
    result = _PredictedExecutor(snapshot,plan).run()
    return Forecast("PREDICTED_CONTINUATION",result.starts,result.finishes,result.workflow_finishes,result.makespan,result.awct)
