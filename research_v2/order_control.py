"""Post-pilot control: lock every B0 assignment, vary only node queue order."""
import heapq
from dataclasses import dataclass

from sail.forecast import forecast_plan
from sail.model import Plan,RepairDecision,validate_repair
from sail.scheduling import _first_slot,_input_ready,upward_ranks,schedule_scope


def reorder_fixed_assignment(snapshot,context,assignment):
    tasks=snapshot.workload.task_map;files=snapshot.workload.file_map;views={t.id:t for t in snapshot.tasks};Q=context.Q
    assert set(assignment)==set(tasks)-set(snapshot.completed)
    rank=upward_ranks(snapshot.workload,snapshot.platform,snapshot.alive)
    pred={v:set(tasks[v].parents)&set(Q) for v in Q};succ={v:set() for v in Q}
    for v in Q:
        for u in pred[v]:succ[u].add(v)
    assigned={};finishes={};intervals=[[] for _ in snapshot.alive]
    for v in sorted(snapshot.completed|snapshot.running):
        view=views[v];assigned[v]=view.node
        if view.status=='DONE':finishes[v]=view.observed_finish
        else:
            assert assignment[v]==view.node
            finishes[v]=snapshot.time+view.estimated_remaining;intervals[view.node].append((v,snapshot.time,finishes[v]))
    ready=[(-rank[v],tasks[v].workflow,v) for v in Q if not pred[v]];heapq.heapify(ready);done=set()
    while ready:
        _,_,v=heapq.heappop(ready);node=assignment[v];assert snapshot.alive[node]
        data=_input_ready(v,node,snapshot,views,assigned,finishes,tasks,files)
        slot=_first_slot(node,intervals[node],max([snapshot.time,data]+[finishes[p] for p in pred[v]]),tasks[v].work,snapshot.platform.speeds[node])
        assigned[v]=node;finishes[v]=slot.finish;intervals[node].insert(slot.position,(v,slot.start,slot.finish));done.add(v)
        for child in sorted(succ[v]):
            if pred[child]<=done:heapq.heappush(ready,(-rank[child],tasks[child].workflow,child))
    assert done==set(Q)
    plan=Plan(tuple(tuple(v for v,_,_ in q) for q in intervals));assert plan.assignment==assignment
    validate_repair(snapshot,context,RepairDecision(Q,plan));forecast_plan(snapshot,plan)
    return plan


class B0AssignmentReorder:
    def __call__(self,snapshot,context):
        b0=schedule_scope(snapshot,context,context.F)
        return RepairDecision(context.Q,reorder_fixed_assignment(snapshot,context,b0.plan.assignment))
