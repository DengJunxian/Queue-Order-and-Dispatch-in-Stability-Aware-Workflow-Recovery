"""Correctness-only workload/queue fixtures; no HEFT or research baselines."""
from sail.model import DataFile, Plan, RepairDecision, Task, Workload


def graph(work,edges=(),workflows=None):
    workflows = workflows or {v:"w" for v in work}
    parents, inputs, files = {v:[] for v in work},{v:[] for v in work},[]
    for u,v,size in edges:
        fid = f"{u}>{v}"
        parents[v].append(u); inputs[v].append(fid)
        files.append(DataFile(fid,size,u))
    return Workload(tuple(Task(v,workflows[v],float(w),tuple(sorted(parents[v])),tuple(sorted(inputs[v]))) for v,w in sorted(work.items())),tuple(files))


def fixed_repair(queues,scope=None):
    def repair(snapshot,context):
        return RepairDecision(context.F if scope is None else frozenset(scope),Plan(tuple(tuple(q) for q in queues)))
    return repair


def keep_plan(snapshot,context):
    return RepairDecision(context.F,snapshot.plan)


def serial_repair(snapshot,context):
    """Feasibility fixture: keep running heads, put all Q on first live node."""
    queues = [[] for _ in snapshot.alive]
    for t in snapshot.tasks:
        if t.status=="RUNNING": queues[t.node].append(t.id)
    node = next(j for j,alive in enumerate(snapshot.alive) if alive)
    queues[node].extend(v for v in snapshot.workload.topological_order() if v in snapshot.pending)
    return RepairDecision(context.Q,Plan(tuple(tuple(q) for q in queues)))


def ordered_round_robin(workload,nodes):
    queues = [[] for _ in range(nodes)]
    for i,v in enumerate(workload.topological_order()):
        queues[i%nodes].append(v)
    return Plan(tuple(tuple(q) for q in queues))


def recurrence_oracle(workload,platform,plan,realized=None):
    """No-fault analytical recurrence over logical + queue dependencies.

    Deliberately independent of the event executor and its topological helper.
    """
    work = realized or {t.id:t.work for t in workload.tasks}
    tasks, files, assignment = workload.task_map,workload.file_map,plan.assignment
    queue_prev = {b:a for q in plan.queues for a,b in zip(q,q[1:])}
    waiting, starts, finishes = set(tasks),{},{}
    while waiting:
        candidates = sorted(v for v in waiting if all(p in finishes for p in tasks[v].parents)
                            and (v not in queue_prev or queue_prev[v] in finishes))
        if not candidates: raise ValueError("oracle cycle")
        for v in candidates:
            task = tasks[v]
            remote = sum(files[f].size for f in task.inputs if files[f].producer is not None and assignment[files[f].producer]!=assignment[v])
            ready = max((finishes[p] for p in task.parents),default=0)+remote/platform.bandwidth
            starts[v] = max(ready,finishes[queue_prev[v]] if v in queue_prev else 0)
            finishes[v] = starts[v]+work[v]/platform.speeds[assignment[v]]
            waiting.remove(v)
    return starts,finishes
