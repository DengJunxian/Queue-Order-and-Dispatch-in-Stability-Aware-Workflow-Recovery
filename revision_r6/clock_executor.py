"""Second implementation: explicit clocks and fluid bytes, no original event engine.

Shares immutable task/plan contracts only. Transfers use independent task links or
one equal-share bottleneck. The implementation records its own transition ledger.
"""
from dataclasses import dataclass,field
import math
from copy import deepcopy
from statistics import mean
from sail.model import Plan,Snapshot,TaskView,FailureContext,RepairDecision,validate_plan,validate_repair,churn

@dataclass
class State:
    node:int
    status:str='PENDING'
    attempt:int=0
    start:float|None=None
    finish:float|None=None
    end:float|None=None
    input_state:str='WAIT'
    total:float=0.
    received:float=0.
    input_start:float|None=None
    token:int=0
    input_end:float|None=None

@dataclass
class ClockResult:
    starts:tuple
    finishes:tuple
    workflow_finishes:tuple
    awct:float
    makespan:float
    context:object
    applied_plan:object
    churn:float
    events:list
    network_checks:dict

class ClockExecutor:
    def __init__(self,workload,platform,plan,*,truth=None,rule='strict',network='independent',switch_time=math.inf,failure=None,repair=None,snapshot=None):
        assert rule in ('strict','skip-unready') and network in ('independent','shared')
        assert failure is None or failure.control_delay==0
        self.w,self.p=workload,platform;self.tasks=workload.task_map;self.files=workload.file_map
        self.rule,self.network,self.switch=rule,network,switch_time
        self.truth=truth if truth is not None else {t.id:t.work for t in workload.tasks}
        assert set(self.truth)==set(self.tasks) and all(math.isfinite(v) and v>0 for v in self.truth.values())
        self.q=[list(q) for q in plan.queues];self.alive=[True]*len(platform.speeds)
        self.s={v:State(j) for v,j in plan.assignment.items()};self.now=0.;self.fault=failure;self.repair=repair
        self.failed=False;self.context=None;self.applied=None;self.events=[];self.intervals=0;self.max_rate=0.;self.byte_error=0.
        if snapshot is None:validate_plan(workload,platform,plan)
        else:
            self.now=snapshot.time;self.alive=list(snapshot.alive);self.switch=snapshot.time
            self.s={}
            running={v.node:v.id for v in snapshot.tasks if v.status=='RUNNING'}
            validate_plan(workload,platform,plan,completed=snapshot.completed,alive=snapshot.alive,running=running)
            for v in snapshot.tasks:
                node=v.node if v.status=='DONE' else plan.assignment[v.id]
                s=State(node,v.status,v.attempt,v.observed_start,v.observed_finish)
                if v.status=='RUNNING':
                    s.end=self.now+v.estimated_remaining;s.input_state='CONSUMED'
                elif v.status=='PENDING' and node==v.node and v.input_status in ('PREPARING','READY'):
                    s.input_state=v.input_status;s.total=v.input_bytes_total;s.received=v.input_bytes_received;s.input_start=v.input_started;s.token=v.input_token
                    if v.input_status=='PREPARING':s.input_end=self.now+(s.total-s.received)/self.p.bandwidth
                self.s[v.id]=s

    def emit(self,kind,**kw):self.events.append({'time':self.now,'kind':kind,**deepcopy(kw)})
    def snapshot(self):
        views=[]
        for v,s in sorted(self.s.items()):
            remaining=max(1e-9*self.w.pbar,self.tasks[v].work/self.p.speeds[s.node]-(self.now-s.start)) if s.status=='RUNNING' else None
            views.append(TaskView(v,s.status,s.node,s.attempt,s.start,s.finish,remaining,s.input_state,s.token,s.total,s.received,s.input_start))
        return Snapshot(self.now,self.w,self.p,tuple(self.alive),Plan(tuple(tuple(q) for q in self.q)),tuple(views))

    def reset_input(self,v):
        s=self.s[v];self.emit('input_reset',task=v,node=s.node,discarded=s.received)
        s.input_state='WAIT';s.total=s.received=0.;s.input_start=None;s.input_end=None;s.token+=1

    def fail_and_repair(self):
        j=self.fault.node;self.failed=True;self.alive[j]=False
        for v,s in self.s.items():
            if s.node==j and s.status=='RUNNING':
                self.emit('cpu_abort',task=v,node=j,start=s.start);s.status='PENDING';s.end=None
        pending=frozenset(v for v,s in self.s.items() if s.status=='PENDING')
        mandatory=frozenset(v for v in pending if self.s[v].node==j)
        # Separate reachability implementation; no use of Workload.descendants.
        reached=set(mandatory)
        while True:
            nxt=reached|{v for v,t in self.tasks.items() if any(p in reached for p in t.parents)}
            if nxt==reached:break
            reached=nxt
        protected=frozenset(pending-reached)
        old=Plan(tuple(tuple(q) for q in self.q))
        self.context=FailureContext(self.now,j,pending,mandatory,protected,tuple(sorted(old.assignment.items())),old.queues)
        self.emit('failure',node=j,Q=sorted(pending),F=sorted(mandatory),P=sorted(protected))
        for v in sorted(mandatory):self.reset_input(v)
        snapshot=self.snapshot();decision=self.repair(snapshot,self.context)
        validate_repair(snapshot,self.context,decision)
        for v,j in decision.plan.assignment.items():
            if self.s[v].node!=j:self.reset_input(v);self.s[v].node=j
        self.q=[list(q) for q in decision.plan.queues];self.applied=decision.plan
        self.emit('plan_applied',queues=self.q)

    def settle(self):
        for v,s in sorted(self.s.items()):
            if s.status!='PENDING' or s.input_state!='WAIT' or not self.alive[s.node]:continue
            t=self.tasks[v]
            if any(self.s[p].status!='DONE' for p in t.parents):continue
            total=0.
            for fid in sorted(t.inputs):
                f=self.files[fid]
                if f.producer is not None:
                    source=self.s[f.producer].node
                    if source!=s.node or not self.alive[source]:total+=f.size
            s.total=total;s.received=0.;s.input_start=self.now;s.token+=1
            s.input_end=self.now+total/self.p.bandwidth
            s.input_state='PREPARING' if total>0 else 'READY'
            self.emit('input_start',task=v,node=s.node,total=total)
            if total==0:self.emit('input_ready',task=v,node=s.node)
        busy={s.node for s in self.s.values() if s.status=='RUNNING'}
        for j,q in enumerate(self.q):
            if j in busy or not self.alive[j] or not q:continue
            skip=self.rule=='skip-unready' and self.now>=self.switch
            v=next((v for v in q if self.s[v].status=='PENDING' and self.s[v].input_state=='READY'),None) if skip else q[0]
            if v is None:continue
            s=self.s[v]
            if s.status!='PENDING' or s.input_state!='READY':continue
            if skip and q[0]!=v:q.remove(v);q.insert(0,v)
            s.status='RUNNING';s.input_state='CONSUMED';s.start=self.now;s.attempt+=1
            s.end=self.now+self.truth[v]/self.p.speeds[j]
            assert s.end>self.now
            self.emit('cpu_start',task=v,node=j,attempt=s.attempt)

    def run(self):
        self.emit('begin',queues=self.q)
        # Timed completions are batched before fault and before dispatch, matching
        # the public tie contract, but using no priority heap or original handlers.
        while True:
            if self.fault and not self.failed and self.now==self.fault.time:self.fail_and_repair()
            self.settle()
            if all(s.status=='DONE' for s in self.s.values()) and (not self.fault or self.failed):break
            active=[v for v,s in self.s.items() if s.input_state=='PREPARING']
            shared=self.network=='shared' and self.now>=self.switch
            rate=self.p.bandwidth/(len(active) if shared and active else 1)
            deadlines=[s.end for s in self.s.values() if s.status=='RUNNING']
            transfer_end={v:(self.now+max(0.,self.s[v].total-self.s[v].received)/rate if shared else self.s[v].input_end) for v in active}
            deadlines+=list(transfer_end.values())
            if self.fault and not self.failed:deadlines.append(self.fault.time)
            if self.now<self.switch<math.inf:deadlines.append(self.switch)
            if not deadlines:raise RuntimeError('Clock executor deadlock')
            end=min(deadlines);assert end>=self.now
            dt=end-self.now
            before=sum(self.s[v].received for v in active)
            for v in active:self.s[v].received=min(self.s[v].total,self.s[v].received+dt*rate)
            transferred=sum(self.s[v].received for v in active)-before
            expected=dt*rate*len(active)
            self.byte_error=max(self.byte_error,abs(transferred-expected)/max(1.,expected))
            if shared and active:self.max_rate=max(self.max_rate,rate*len(active)/self.p.bandwidth)
            self.intervals+=1
            if shared and active:self.emit('link_interval',until=end,active=len(active),bytes=transferred,capacity=self.p.bandwidth)
            self.now=end
            for v,s in sorted(self.s.items()):
                if s.status=='RUNNING' and s.end==end:
                    assert self.q[s.node][0]==v
                    s.status='DONE';s.finish=end;s.end=None;self.q[s.node].pop(0)
                    self.emit('cpu_done',task=v,node=s.node,attempt=s.attempt)
            for v,done in transfer_end.items():
                if done==end:
                    s=self.s[v];s.received=s.total;s.input_state='READY';self.emit('input_ready',task=v,node=s.node)
        finish={}
        for v,s in self.s.items():finish[self.tasks[v].workflow]=max(finish.get(self.tasks[v].workflow,0),s.finish)
        return ClockResult(tuple(sorted((v,s.start) for v,s in self.s.items())),tuple(sorted((v,s.finish) for v,s in self.s.items())),tuple(sorted(finish.items())),mean(finish.values()),max(finish.values()),self.context,self.applied,churn(self.context,self.applied) if self.context else 0.,self.events,{'intervals':self.intervals,'max_shared_rate_fraction':self.max_rate,'max_relative_byte_residual':self.byte_error})

def predict(snapshot,plan,rule='strict',network='independent'):
    return ClockExecutor(snapshot.workload,snapshot.platform,plan,snapshot=snapshot,rule=rule,network=network,switch_time=snapshot.time).run()
