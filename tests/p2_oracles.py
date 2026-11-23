"""Independent arithmetic and all-node/all-gap checks for the common kernel."""
import math
import networkx as nx


def continuation_oracle(snapshot,plan):
    tasks,files = snapshot.workload.task_map,snapshot.workload.file_map
    views = {v.id:v for v in snapshot.tasks}
    assigned = {v.id:v.node for v in snapshot.tasks if v.status=="DONE"}
    assigned.update(plan.assignment)
    starts,finishes = {},{}
    for t in snapshot.tasks:
        if t.status=="DONE": starts[t.id],finishes[t.id] = t.observed_start,t.observed_finish
        elif t.status=="RUNNING": starts[t.id],finishes[t.id] = t.observed_start,snapshot.time+t.estimated_remaining
    previous = {b:a for row in plan.queues for a,b in zip(row,row[1:])}
    pending = set(tasks)-set(finishes)
    while pending:
        ready = sorted(v for v in pending if all(p in finishes for p in tasks[v].parents) and
                       (v not in previous or previous[v] in finishes))
        assert ready,"oracle queue/logic cycle"
        for v in ready:
            view,node = views[v],assigned[v]
            if view.node==node and view.input_status=="READY": input_ready=snapshot.time
            elif view.node==node and view.input_status=="PREPARING":
                input_ready=snapshot.time+(view.input_bytes_total-view.input_bytes_received)/snapshot.platform.bandwidth
            else:
                remote = sum(files[f].size for f in tasks[v].inputs if files[f].producer is not None and
                             (assigned[files[f].producer]!=node or not snapshot.alive[assigned[files[f].producer]]))
                input_ready=max([snapshot.time]+[finishes[p] for p in tasks[v].parents])+remote/snapshot.platform.bandwidth
            starts[v]=max(snapshot.time,input_ready,finishes[previous[v]] if v in previous else snapshot.time)
            finishes[v]=starts[v]+tasks[v].work/snapshot.platform.speeds[node]
            pending.remove(v)
    return starts,finishes


def check_all_gap_choices(snapshot,scope,schedule):
    """Enumerate starts at every release/interval boundary, not first-gap scanning."""
    tasks,files = snapshot.workload.task_map,snapshot.workload.file_map
    nodes = [j for j,a in enumerate(snapshot.alive) if a]
    graph = nx.DiGraph()
    graph.add_nodes_from(tasks)
    graph.add_edges_from(snapshot.workload.edges)
    rank={}
    for v in reversed(list(nx.lexicographical_topological_sort(graph))):
        rank[v]=sum(tasks[v].work/snapshot.platform.speeds[j] for j in nodes)/len(nodes)+max(
            (sum(files[f].size for f in tasks[c].inputs if files[f].producer==v)/snapshot.platform.bandwidth+rank[c] for c in graph.successors(v)),default=0)
    views={t.id:t for t in snapshot.tasks}
    pending=set(snapshot.pending)
    order=nx.DiGraph(graph.subgraph(pending))
    fixed=pending-set(scope)
    for row in snapshot.plan.queues:
        anchors=[v for v in row if v in fixed]
        order.add_edges_from(zip(anchors,anchors[1:]))
    assigned,finish,intervals={},{},[[] for _ in snapshot.alive]
    for t in snapshot.tasks:
        if t.status=="DONE": assigned[t.id],finish[t.id]=t.node,t.observed_finish
        elif t.status=="RUNNING":
            assigned[t.id],finish[t.id]=t.node,snapshot.time+t.estimated_remaining
            intervals[t.node].append((t.id,snapshot.time,finish[t.id]))
    placed=set()
    for trace in schedule.placements:
        eligible=[v for v in pending-placed if set(order.predecessors(v))<=placed]
        expected=min(eligible,key=lambda v:(-rank[v],tasks[v].workflow,v))
        assert trace.task==expected,("rank/ready order",trace.task,expected)
        v=expected
        all_choices=[]
        for j in (nodes if v in scope else [views[v].node]):
            view=views[v]
            if view.node==j and view.input_status=="READY": data_ready=snapshot.time
            elif view.node==j and view.input_status=="PREPARING":
                data_ready=snapshot.time+(view.input_bytes_total-view.input_bytes_received)/snapshot.platform.bandwidth
            else:
                remote=sum(files[f].size for f in tasks[v].inputs if files[f].producer is not None and
                           (assigned[files[f].producer]!=j or not snapshot.alive[assigned[files[f].producer]]))
                data_ready=max([snapshot.time]+[finish[p] for p in tasks[v].parents])+remote/snapshot.platform.bandwidth
            release=max([snapshot.time,data_ready]+[finish[p] for p in order.predecessors(v)])
            duration=tasks[v].work/snapshot.platform.speeds[j]
            # Feasible earliest starts lie at the release or an occupied interval end.
            options=[]
            for begin in sorted({release}|{end for _,_,end in intervals[j] if end>=release}):
                end=begin+duration
                if all(end<=a or begin>=b for _,a,b in intervals[j]):
                    position=sum(b<=begin for _,_,b in intervals[j])
                    options.append((end,begin,j,position))
            assert options
            all_choices.append(min(options))
        best=min(all_choices)
        got=trace.chosen
        assert (got.node,got.position)==(best[2],best[3]),("EFT node/gap",v,got,best)
        assert math.isclose(got.start,best[1],rel_tol=1e-10,abs_tol=1e-9)
        assert math.isclose(got.finish,best[0],rel_tol=1e-10,abs_tol=1e-9)
        assert len(trace.candidates)==len(all_choices)
        assigned[v],finish[v]=got.node,got.finish
        intervals[got.node].insert(got.position,(v,got.start,got.finish))
        placed.add(v)
    assert placed==pending
