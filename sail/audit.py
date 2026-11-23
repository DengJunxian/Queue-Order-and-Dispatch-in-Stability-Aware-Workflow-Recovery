"""Independent replay checker: reconstruct state from event records and input data.

Does not import simulator transition functions, plan validators, or stored run metrics.
"""
from __future__ import annotations

import math
import networkx as nx


class AuditError(ValueError):
    pass


def require(condition,message):
    if not condition:
        raise AuditError(message)


def close(a,b):
    return math.isclose(a,b,rel_tol=1e-9,abs_tol=1e-9)


def audit_events(workload,platform,events,*,realized_work=None,expected_failure=None):
    tasks, files = workload.task_map, workload.file_map
    actual = dict(realized_work) if realized_work is not None else {v:t.work for v,t in tasks.items()}
    require(set(actual)==set(tasks),"audit realized-work ID mismatch")
    require(all(math.isfinite(v) and v>0 for v in actual.values()),"audit invalid realized work")
    m = len(platform.speeds)
    status = dict.fromkeys(tasks,"PENDING")
    attempts = dict.fromkeys(tasks,0)
    assignment, starts, finishes, running, prep = {},{},{},{},{}
    queues = [[] for _ in range(m)]
    alive = [True]*m
    last_input_token = dict.fromkeys(tasks,0)
    cpu_issued, input_issued, consumed_cpu, consumed_input = {},{},set(),set()
    context, applied_assignment, initial_queues = None,None,None
    paused, due, last_time = False,None,0.0
    cpu = wasted_cpu = wasted_work = transferred = 0.0

    def check_queues(qs):
        require(len(qs)==m,"queue count mismatch")
        flat = [v for q in qs for v in q]
        unfinished = {v for v in tasks if status[v]!="DONE"}
        require(len(flat)==len(set(flat)) and set(flat)==unfinished,"queue membership mismatch")
        for j,q in enumerate(qs):
            require(alive[j] or not q,"assignment to failed node")
            if j in running:
                require(bool(q) and q[0]==running[j],"healthy CPU task moved or overtaken")
        graph = nx.DiGraph()
        graph.add_nodes_from(unfinished)
        graph.add_edges_from((p,v) for v in unfinished for p in tasks[v].parents if p in unfinished)
        graph.add_edges_from((a,b) for q in qs for a,b in zip(q,q[1:]))
        require(nx.is_directed_acyclic_graph(graph),"cyclic resource/logic order")

    def descendants(roots):
        reached, frontier = set(roots),list(roots)
        while frontier:
            u = frontier.pop()
            for v,t in tasks.items():
                if u in t.parents and v not in reached:
                    reached.add(v); frontier.append(v)
        return reached-set(roots)

    for seq,e in enumerate(events):
        require(e["seq"]==seq,"event sequence mismatch")
        time,kind,v,j,d = e["time"],e["kind"],e["task"],e["node"],e["details"]
        require(math.isfinite(time) and time>=last_time,"time decreased or nonfinite")
        last_time = time
        require(v is None or v in tasks,"unknown task in log")
        require(j is None or isinstance(j,int) and 0<=j<m,"unknown node in log")
        if seq==0:
            require(kind=="RUN_START" and time==0,"missing initial event")
        if kind=="RUN_START":
            require(seq==0,"duplicate run start")
            queues = [list(q) for q in d["queues"]]
            check_queues(queues)
            initial_queues = [list(q) for q in queues]
            assignment = {v:j for j,q in enumerate(queues) for v in q}
        elif kind=="INPUT_START":
            require(status[v]=="PENDING" and alive[j] and assignment[v]==j,"illegal input start")
            require(v not in prep,"input preparation/cache overwritten without cancellation")
            require(all(status[p]=="DONE" for p in tasks[v].parents),"input prefetched before all parents completed")
            remote = sorted(f for f in tasks[v].inputs if files[f].producer is not None and
                            (assignment[files[f].producer]!=j or not alive[assignment[files[f].producer]]))
            amount = sum(files[f].size for f in remote)
            require(d["remote_files"]==remote and close(d["bytes_total"],amount),"incorrect locality or file-byte sum")
            token = d["token"]
            require(token>last_input_token[v],"input token reused")
            last_input_token[v] = token
            prep[v] = {"node":j,"token":token,"start":time,"total":amount,"ready":False}
            input_issued[v,token] = time+amount/platform.bandwidth
        elif kind=="INPUT_READY":
            p = prep.get(v)
            require(p is not None and not p["ready"] and p["token"]==d["token"] and p["node"]==j and alive[j],"unissued input completion")
            require(close(time,input_issued[v,d["token"]]) and close(d["bytes"],p["total"]),"input completed at wrong time or byte count")
            require((v,d["token"]) not in consumed_input,"duplicate input completion")
            consumed_input.add((v,d["token"]))
            p["ready"] = True
            transferred += p["total"]
        elif kind=="INPUT_CANCEL":
            p = prep.get(v)
            require(p is not None and not p["ready"] and p["token"]==d["token"] and p["node"]==j,"invalid input cancellation")
            require(not alive[j] or assignment[v]!=j,"input cancelled without node failure or reassignment")
            require(time<input_issued[v,d["token"]],"completed transfer was cancelled instead of completed")
            amount = min(p["total"],max(0.0,(time-p["start"])*platform.bandwidth))
            require(close(d["bytes"],amount),"cancelled transfer byte accounting mismatch")
            transferred += amount
            del prep[v]
        elif kind=="INPUT_DISCARD":
            p = prep.get(v)
            require(p is not None and p["ready"] and p["token"]==d["token"] and p["node"]==j,"invalid input cache discard")
            require(not alive[j] or assignment[v]!=j,"prepared input discarded without failure or reassignment")
            del prep[v]
        elif kind=="CPU_START":
            require(not paused and alive[j] and j not in running,"CPU started while paused, failed or busy")
            require(status[v]=="PENDING" and assignment[v]==j and queues[j] and queues[j][0]==v,"CPU queue/task state violation")
            require(all(status[p]=="DONE" for p in tasks[v].parents),"CPU dependency violation")
            p = prep.get(v)
            require(p is not None and p["ready"] and p["node"]==j,"CPU started without input on destination")
            require(d["attempt"]==attempts[v]+1,"CPU attempt counter mismatch")
            attempts[v] += 1
            starts[v] = time
            status[v] = "RUNNING"
            running[j] = v
            cpu_issued[v,attempts[v]] = time+actual[v]/platform.speeds[j]
        elif kind=="CPU_DONE":
            key = (v,d["attempt"])
            require(status[v]=="RUNNING" and running.get(j)==v and alive[j] and d["attempt"]==attempts[v],"ghost CPU completion")
            require(key not in consumed_cpu and close(time,cpu_issued[key]),"CPU completed early/late or twice")
            consumed_cpu.add(key)
            cpu += time-starts[v]
            finishes[v] = time
            status[v] = "DONE"
            require(queues[j].pop(0)==v,"completed task was not queue head")
            del running[j]
        elif kind=="FAILURE":
            require(expected_failure is not None and context is None,"unexpected or repeated fault")
            require(j==expected_failure.node and close(time,expected_failure.time) and close(d["control_delay"],expected_failure.control_delay),"fault differs from injection specification")
            require(all(cpu_issued[t,attempts[t]]>time for t in running.values()),"completion/failure tie priority violated")
            require(all(p["ready"] or input_issued[t,p["token"]]>time for t,p in prep.items()),"input completion/failure tie priority violated")
            Q = {v for v in tasks if status[v]=="PENDING" or status[v]=="RUNNING" and assignment[v]==j}
            F = {v for v in Q if assignment[v]==j}
            P = Q-F-descendants(F)
            P = {v for v in P if assignment[v]!=j and alive[assignment[v]]}
            old = {v:assignment[v] for q in queues for v in q}
            context = {"time":time,"failed_node":j,"Q":sorted(Q),"F":sorted(F),"P":sorted(P),
                       "old_assignment":[list(p) for p in sorted(old.items())],"original_queues":[list(q) for q in queues]}
            require(d["context"]==context,"logged F/Q/P differs from independent state/descendants")
            alive[j] = False
            paused,due = True,time+d["control_delay"]
        elif kind=="CPU_ABORT":
            require(context is not None and j==context["failed_node"] and not alive[j],"healthy CPU aborted")
            require(running.get(j)==v and status[v]=="RUNNING" and attempts[v]==d["attempt"],"wrong attempt aborted")
            require(time==context["time"] and time<cpu_issued[v,attempts[v]],"abort at wrong time")
            elapsed = time-starts[v]
            require(close(d["elapsed"],elapsed),"lost computation mismatch")
            cpu += elapsed; wasted_cpu += elapsed; wasted_work += elapsed*platform.speeds[j]
            status[v] = "PENDING"
            del running[j]
        elif kind=="PLAN_APPLIED":
            require(context is not None and paused and applied_assignment is None and close(time,due),"repair application timing/duplication violation")
            scope = set(d["scope"])
            require(set(context["F"])<=scope<=set(context["Q"]),"invalid repair scope")
            proposed = [list(q) for q in d["queues"]]
            check_queues(proposed)
            new = {v:j for j,q in enumerate(proposed) for v in q}
            old = dict(context["old_assignment"])
            fixed = set(context["Q"])-scope
            require(all(new[v]==old[v] for v in fixed),"H-external assignment changed")
            for before,after in zip(context["original_queues"],proposed):
                require([v for v in before if v in fixed]==[v for v in after if v in fixed],"H-external relative order changed")
            rr = sum(new[v]!=old[v] for v in set(context["Q"])-set(context["F"]))/max(1,len(context["Q"]))
            require(close(rr,d["churn"]),"migration ratio mismatch")
            # Keep completed producer locations for durable/local input accounting.
            assignment.update(new)
            queues,applied_assignment,paused = proposed,new,False
        elif kind=="STALE_EVENT":
            if d["event"]=="CPU_DONE":
                key = (v,d["attempt"])
                require(key in cpu_issued and key not in consumed_cpu and close(time,cpu_issued[key]),"unissued/duplicate stale CPU event")
                require(not(status[v]=="RUNNING" and attempts[v]==d["attempt"]),"live CPU event incorrectly ignored")
                consumed_cpu.add(key)
            elif d["event"]=="INPUT_DONE":
                key = (v,d["token"])
                require(key in input_issued and key not in consumed_input and close(time,input_issued[key]),"unissued/duplicate stale input event")
                require(v not in prep or prep[v]["token"]!=d["token"],"live input event incorrectly ignored")
                consumed_input.add(key)
            else:
                raise AuditError("unknown stale event")
        else:
            raise AuditError(f"unknown event kind {kind}")
    require(initial_queues is not None and set(finishes)==set(tasks),"missing task commits")
    require(not running and not paused,"unfinished CPU or pending repair")
    require((context is not None)==(expected_failure is not None),"missing fault")
    require(context is None or applied_assignment is not None,"missing applied repair")
    require(set(cpu_issued)==consumed_cpu and set(input_issued)==consumed_input,"truncated event queue")
    workflow_finishes = {}
    for v,t in tasks.items():
        workflow_finishes[t.workflow] = max(workflow_finishes.get(t.workflow,0.0),finishes[v])
    rr = 0.0 if context is None else sum(applied_assignment[v]!=dict(context["old_assignment"])[v] for v in set(context["Q"])-set(context["F"]))/max(1,len(context["Q"]))
    return {"starts":starts,"finishes":finishes,"workflow_finishes":workflow_finishes,
            "makespan":max(workflow_finishes.values()),"awct":sum(workflow_finishes.values())/len(workflow_finishes),
            "cpu_seconds":cpu,"wasted_cpu_seconds":wasted_cpu,"wasted_work":wasted_work,
            "transfer_bytes":transferred,"attempts":attempts,"churn":rr,"context":context,
            "initial_queues":initial_queues,"events_checked":len(events)}


def audit_result(result,workload,platform,*,realized_work=None,expected_failure=None,reference=None):
    a = audit_events(workload,platform,result.events,realized_work=realized_work,expected_failure=expected_failure)
    for key in ("awct","makespan","cpu_seconds","wasted_cpu_seconds","wasted_work","transfer_bytes","churn"):
        require(close(getattr(result,key),a[key]),f"stored {key} differs from log replay")
    for key in ("starts","finishes","workflow_finishes"):
        observed = dict(getattr(result,key))
        require(set(observed)==set(a[key]) and all(close(observed[v],a[key][v]) for v in observed),f"stored {key} differs from events")
    require(dict(result.attempts)==a["attempts"],"stored attempts mismatch")
    if result.context:
        for key in ("Q","F","P"):
            require(set(getattr(result.context,key))==set(a["context"][key]),f"stored context {key} differs")
    else:
        require(a["context"] is None,"missing stored context")
    a["cdi"] = None
    if reference is not None:
        require(result.case_key==reference.case_key,"unmatched reference")
        b = audit_events(workload,platform,reference.events,realized_work=realized_work)
        require(a["initial_queues"]==b["initial_queues"],"reference initial plan differs")
        P = a["context"]["P"] if a["context"] else []
        if P:
            pbar = sum(t.work for t in workload.tasks)/len(workload.tasks)
            a["cdi"] = sum(max(0,a["starts"][v]-b["starts"][v]) for v in P)/len(P)/pbar
    return a
