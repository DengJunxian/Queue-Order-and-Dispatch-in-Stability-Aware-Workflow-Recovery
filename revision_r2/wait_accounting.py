"""Exact additive time accounting, distinct from a causal attribution model."""
from bisect import bisect_right
from collections import defaultdict


CATEGORIES = ('predecessor', 'input_staging', 'competition', 'HOL')


def wait_components(document, workload, tau, population):
    starts, finishes = dict(document['starts']), dict(document['finishes'])
    input_ready, locations, active = {}, {}, {}
    intervals = defaultdict(list)
    for event in document['events']:
        v, j, t, k = event['task'], event['node'], event['time'], event['kind']
        if k == 'INPUT_READY': input_ready[v] = t
        elif k == 'CPU_START':
            active[v] = (j, t); locations[v] = j
        elif k in ('CPU_DONE', 'CPU_ABORT'):
            node, begin = active.pop(v)
            assert node == j
            intervals[j].append((begin, t))
    assert not active
    timelines = {}
    for j, spans in intervals.items():
        spans.sort(); ss, ee, prefix = [], [], [0.]
        for begin, end in spans:
            assert not ee or begin >= ee[-1] - 1e-8
            ss.append(begin); ee.append(end); prefix.append(prefix[-1] + end - begin)
        timelines[j] = ss, ee, prefix
    def busy_until(j, time):
        ss, ee, prefix = timelines[j]
        i = bisect_right(ee, time)
        return prefix[i] + (max(0., time - ss[i]) if i < len(ss) else 0.)
    tasks = workload.task_map
    values = {}
    for v in population:
        start = starts[v]
        assert start >= tau - 1e-8, (v, start, tau)
        parent_ready = max((finishes[p] for p in tasks[v].parents), default=0.)
        dep = max(0., parent_ready - tau)
        ready = max(tau, input_ready[v])
        own_input = max(0., ready - max(tau, parent_ready))
        j = locations[v]
        competition = busy_until(j, start) - busy_until(j, ready)
        hol = start - ready - competition
        assert hol >= -1e-7, (v, hol)
        if abs(hol) < 1e-10: hol = 0.
        vector = {'predecessor': dep, 'input_staging': own_input, 'competition': competition, 'HOL': hol}
        assert abs(sum(vector.values()) - (start - tau)) < 1e-7
        values[v] = vector
    return values
