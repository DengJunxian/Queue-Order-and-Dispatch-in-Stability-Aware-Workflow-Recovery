"""Stable protected-subsequence ordering from an observation-only snapshot."""
from sail.model import ModelError, Plan, RepairDecision, validate_repair
from sail.scheduling import schedule_scope


def protected_subsequence(snapshot, context, baseline):
    """Keep B0 placement, running heads, and each within-group subsequence.

    The baseline must preserve original optional assignments and protected queue
    subsequences. No predicted or realized starts enter this transformation.
    """
    if snapshot.pending != context.Q:
        raise ModelError('pending set differs from original failure context')
    validate_repair(snapshot, context, RepairDecision(context.F, baseline))
    tasks = snapshot.workload.task_map
    if any(p in context.Q and p not in context.P for v in context.P for p in tasks[v].parents):
        raise ModelError('protected set is not predecessor closed within pending work')
    running = snapshot.running
    queues = []
    for old, b0 in zip(context.original_queues, baseline.queues):
        ps = tuple(v for v in b0 if v in context.P)
        if ps != tuple(v for v in old if v in context.P):
            raise ModelError('baseline changed the original protected subsequence')
        queues.append(tuple(v for v in b0 if v in running) + ps
                      + tuple(v for v in b0 if v in context.Q - context.P))
    plan = Plan(tuple(queues))
    if plan.assignment != baseline.assignment:
        raise ModelError('subsequence ordering changed the baseline assignment')
    decision = RepairDecision(context.Q, plan)
    validate_repair(snapshot, context, decision)
    return decision


class ProtectedSubsequence:
    """Optional frozen B0 plan supports a strictly matched order intervention."""
    def __init__(self, baseline=None):
        self.baseline = baseline

    def __call__(self, snapshot, context):
        baseline = self.baseline or schedule_scope(snapshot, context, context.F).plan
        return protected_subsequence(snapshot, context, baseline)
