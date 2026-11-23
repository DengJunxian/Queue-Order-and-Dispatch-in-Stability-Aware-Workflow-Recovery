import json,hashlib,gzip
from pathlib import Path
from dataclasses import asdict,is_dataclass
import numpy as np
from sail.data import Corpus
from sail.model import Workload,Task,Platform,Failure,RepairDecision
from sail.scheduling import initial_heft,schedule_scope
from sail.policy import OnlineReference
from research_v2.policies import BudgetSelect
from revision_r4.common import METHODS,policy
from revision_r5.control import ProtectedSubsequence
from revision_r6.clock_executor import ClockExecutor,predict
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'revision_r6'
METHOD_NAMES=(*METHODS,'ProtectedSubsequence','DispatchMinAWCT','DispatchMatchedGuard')
def jsonable(x):
    if is_dataclass(x):return jsonable(asdict(x))
    if isinstance(x,dict):return {str(k):jsonable(v) for k,v in x.items()}
    if isinstance(x,(set,frozenset)):return [jsonable(v) for v in sorted(x)]
    if isinstance(x,(list,tuple)):return [jsonable(v) for v in x]
    return x
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def dump(p,d):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(jsonable(d),indent=2,allow_nan=False)+'\n')
def save(p,d):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(gzip.compress(json.dumps(jsonable(d),separators=(',',':'),allow_nan=False).encode(),mtime=0));return sha(p)
def read(p):
    p=Path(p);return json.loads(gzip.decompress(p.read_bytes()) if p.suffix=='.gz' else p.read_bytes())
class HoldoutCorpus(Corpus):
    def __init__(self):
        self.root=ROOT;self.manifest=read(OUT/'data/manifest.json');self.records={r['id']:r for r in self.manifest['records']}
    def workload(self,identity):
        old=Corpus(ROOT);parts=[self.load(identity,'w00'),old.load('montage-chameleon-2mass-005d-001','w01'),old.load('srasearch-chameleon-20a-001','w02')]
        return Workload(tuple(t for w in parts for t in w.tasks),tuple(f for w in parts for f in w.files))
def original_choices(snapshot,context,initial):
    choices={}
    for name in METHODS:choices[name]=policy(name,initial)(snapshot,context)
    choices['ProtectedSubsequence']=ProtectedSubsequence(choices['B0'].plan)(snapshot,context)
    pool=BudgetSelect(OnlineReference.from_initial(initial),.1);pool(snapshot,context)
    return choices,pool.last_candidates,schedule_scope(snapshot,context,context.Q).plan
def dispatch_choices(snapshot,context,initial,candidates,b2,rule,network='independent',eta=None):
    nf=ClockExecutor(snapshot.workload,snapshot.platform,initial.plan,rule=rule,network=network,switch_time=snapshot.time).run()
    starts0=dict(nf.starts);rows=[]
    for c in candidates:
        fc=predict(snapshot,c['plan'],rule,network);ss=dict(fc.starts)
        cdi=sum(max(0.,ss[v]-starts0[v]) for v in context.P)/len(context.P)/snapshot.workload.pbar if context.P else 0.
        rows.append({**c,'forecast':fc,'awct':fc.awct,'cdi':cdi})
    b2fc=predict(snapshot,b2,rule,network)
    quality=[c for c in rows if c['awct']<=1.05*b2fc.awct]
    admissible=quality or rows
    pm=min(admissible,key=lambda c:(c['awct'],c['churn'],c['name'],c['plan'].queues))
    reference=dict(pm['forecast'].workflow_finishes)
    def passes(c,gamma):return all(t<=gamma*reference[w]+1e-10 for w,t in c['forecast'].workflow_finishes)
    def key(c):return (c['cdi'],c['awct'],c['churn'],c['name'],c['plan'].queues)
    guarded=[c for c in admissible if passes(c,1.05)];assert guarded
    chosen=min(guarded,key=key)
    choices={'DispatchMinAWCT':RepairDecision(context.Q,pm['plan']),'DispatchMatchedGuard':RepairDecision(context.Q,chosen['plan'])}
    selected={'DispatchMinAWCT':pm,'DispatchMatchedGuard':chosen}
    metadata={'mean_quality_fallback':not bool(quality),'pool_size':len(rows),'reference_name':pm['name'],'guard_selected_name':chosen['name'],'nonreference_selected':chosen['plan']!=pm['plan']}
    if eta is not None:
        gamma=1.05*(1-eta)/(1+eta) if eta<1 else None
        feasible=[c for c in admissible if c['plan']!=pm['plan'] and passes(c,gamma)] if gamma is not None else []
        cg=min(feasible,key=key) if feasible else pm
        choices['CalibratedGuard']=RepairDecision(context.Q,cg['plan']);selected['CalibratedGuard']=cg
        metadata.update({'calibration_eta':eta,'tightened_gamma':gamma,'calibrated_reference_fallback':not bool(feasible),'calibrated_selected_name':cg['name']})
    return choices,selected,rows,metadata
def metrics(run,reference,w):
    ss,ss0=dict(run.starts),dict(reference.starts);P=run.context.P
    delta=[(ss[v]-ss0[v])/w.pbar for v in sorted(P)]
    return {'awct':run.awct,'cdi':float(np.mean(np.maximum(0,delta))) if delta else None,'signed':float(np.mean(delta)) if delta else None,'absolute':float(np.mean(np.abs(delta))) if delta else None,'max_positive':max([0.,*delta]) if delta else None,'late_fraction':float(np.mean(np.array(delta)>1e-8)) if delta else None,'churn':run.churn,'P':len(P),'F':len(run.context.F),'Q':len(run.context.Q),'workflow_completion':dict(run.workflow_finishes)}
