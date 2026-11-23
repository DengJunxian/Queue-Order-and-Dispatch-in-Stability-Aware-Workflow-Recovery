"""Reconstruct clocks/bytes/CPU occupancy from the persisted second-engine log."""
import math
import networkx as nx

def close(a,b):return math.isclose(a,b,abs_tol=1e-8,rel_tol=1e-10)
def audit(doc,w,p,truth,network,switch):
    tasks=w.task_map;files=w.file_map;status={v:'PENDING' for v in tasks}
    assigned={v:j for j,q in enumerate(doc['events'][0]['queues']) for v in q}
    running={};starts={};finishes={};ready=set();transfers={};last=0.;alive=[True]*len(p.speeds)
    logical=nx.DiGraph();logical.add_nodes_from(tasks);logical.add_edges_from(w.edges)
    intervals=0;link_bytes=0.;context=None;max_byte_residual=0.;max_rounding_budget=0.
    def byte_close(rec,value):
        nonlocal max_byte_residual,max_rounding_budget
        residual=abs(rec['received']-value);budget=rec['rounding_budget']
        max_byte_residual=max(max_byte_residual,residual);max_rounding_budget=max(max_rounding_budget,budget)
        return residual<=max(1e-8,1e-10*abs(value))+budget
    for e in doc['events']:
        now=e['time'];assert now>=last
        if now>last and transfers:
            points=[last]+([switch] if last<switch<now else [])+[now]
            for a,b in zip(points,points[1:]):
                speed=p.bandwidth/(len(transfers) if network=='shared' and a>=switch else 1)
                for v,rec in transfers.items():
                    # Integrating bytes from rounded absolute clock endpoints can
                    # amplify ulps by a large bandwidth. Track that accumulation
                    # explicitly instead of treating it as physical byte loss.
                    increment=speed*(b-a)
                    rec['rounding_budget']+=4*speed*(math.ulp(a)+math.ulp(b))+4*math.ulp(increment)+4*math.ulp(rec['received'])
                    rec['received']+=increment
                if network=='shared' and a>=switch:link_bytes+=speed*len(transfers)*(b-a);assert close(speed*len(transfers),p.bandwidth)
                intervals+=1
        last=now;kind=e['kind'];v=e.get('task');j=e.get('node')
        if kind in ('begin','link_interval'):continue
        if kind=='input_start':
            assert status[v]=='PENDING' and all(status[u]=='DONE' for u in tasks[v].parents)
            expected=sum(files[f].size for f in sorted(tasks[v].inputs) if files[f].producer is not None and (assigned[files[f].producer]!=j or not alive[assigned[files[f].producer]]))
            assert close(expected,e['total'])
            transfers[v]={'received':0.,'total':expected,'rounding_budget':0.}
        elif kind=='input_ready':
            rec=transfers.pop(v);assert byte_close(rec,rec['total']),(v,rec)
            ready.add(v)
        elif kind=='input_reset':
            rec=transfers.pop(v,None)
            if rec:assert byte_close(rec,e['discarded']),(v,rec,e['discarded'])
            ready.discard(v)
        elif kind=='cpu_start':
            assert alive[j] and j not in running and status[v]=='PENDING' and v in ready
            assert all(status[u]=='DONE' for u in tasks[v].parents)
            status[v]='RUNNING';running[j]=(v,now);starts[v]=now;ready.remove(v)
        elif kind=='cpu_done':
            assert running[j][0]==v and close(now-running[j][1],truth[v]/p.speeds[j])
            del running[j];finishes[v]=now;status[v]='DONE'
        elif kind=='cpu_abort':
            assert running[j][0]==v;del running[j];status[v]='PENDING'
        elif kind=='failure':
            alive[j]=False;Q={v for v in tasks if status[v]=='PENDING'};F={v for v in Q if assigned[v]==j}
            descendants=set().union(*(nx.descendants(logical,v) for v in F)) if F else set();P=Q-F-descendants
            assert Q==set(e['Q']) and F==set(e['F']) and P==set(e['P']);context={'Q':Q,'F':F,'P':P}
        elif kind=='plan_applied':
            new={v:j for j,q in enumerate(e['queues']) for v in q}
            assert set(new)=={v for v in tasks if status[v]!='DONE'}
            assert all(alive[j] for j in new.values());assigned.update(new)
        else:raise AssertionError(kind)
    assert len(finishes)==len(tasks) and not running and not transfers
    assert all(close(starts[v],dict(doc['starts'])[v]) and close(finishes[v],dict(doc['finishes'])[v]) for v in tasks)
    workflows={g:max(finishes[t.id] for t in w.tasks if t.workflow==g) for g in {t.workflow for t in w.tasks}}
    assert all(close(t,dict(doc['workflow_finishes'])[g]) for g,t in workflows.items())
    return {'status':'PASS','events':len(doc['events']),'task_start_finish_checks':2*len(tasks),'transfer_intervals':intervals,'shared_link_bytes':link_bytes,'max_byte_rounding_residual':max_byte_residual,'max_accumulated_byte_rounding_budget':max_rounding_budget,'starts':starts,'finishes':finishes,'workflow_completion':workflows,'context':{k:sorted(v) for k,v in context.items()} if context else None}
