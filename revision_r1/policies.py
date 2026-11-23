"""Untuned post-freeze protected-priority control; original policies untouched."""
import heapq

from sail.model import Plan, RepairDecision, validate_repair
from sail.scheduling import schedule_scope, upward_ranks


class ProtectedFirst:
    """Lock B0 placement and append a protected-first topological queue order.

    Ready means predecessor-placed in the list construction, not a new online
    dispatch semantic. Strict queues may wait for an unready protected head.
    """
    def __call__(self, snapshot, context):
        baseline = schedule_scope(snapshot, context, context.F)
        assignment = baseline.plan.assignment
        tasks = snapshot.workload.task_map
        pending = context.Q
        parents = {v: set(tasks[v].parents) & set(pending) for v in pending}
        successors = {v: set() for v in pending}
        for v, pp in parents.items():
            for p in pp:
                successors[p].add(v)
        ranks = upward_ranks(snapshot.workload, snapshot.platform, snapshot.alive)
        def key(v):
            return (0 if v in context.P else 1, -ranks[v], tasks[v].workflow, v)
        ready = [key(v) for v in pending if not parents[v]]
        heapq.heapify(ready)
        queues = [[] for _ in snapshot.alive]
        for task in snapshot.tasks:
            if task.status == 'RUNNING':
                queues[task.node].append(task.id)
        done = set()
        while ready:
            *_, v = heapq.heappop(ready)
            queues[assignment[v]].append(v)
            done.add(v)
            for child in sorted(successors[v]):
                if parents[child] <= done:
                    heapq.heappush(ready, key(child))
        assert done == set(pending)
        plan = Plan(tuple(tuple(q) for q in queues))
        assert plan.assignment == assignment
        for queue in plan.queues:
            positions = {v: i for i, v in enumerate(queue)}
            assert all(positions[p] < positions[f] for p in context.P & positions.keys()
                       for f in context.F & positions.keys())
        decision = RepairDecision(context.Q, plan)
        validate_repair(snapshot, context, decision)
        return decision
