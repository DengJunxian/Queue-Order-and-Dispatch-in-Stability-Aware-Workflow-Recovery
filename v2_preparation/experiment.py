"""New development namespace and shared v2 method factory."""
from sail.data import random_stream
from sail.model import DataFile,ModelError,Task,Workload
from sail.policy import OnlineReference,SAILPolicy
from sail.scheduling import Baseline
from research_v2.policies import BudgetPolicy,BudgetSelect
from research_v2.order_control import B0AssignmentReorder
from v2_preparation.policies import PoolMinAWCT

METHODS=('B0','B1','B2','LegacySAIL','QueueRepair0','BudgetHEFT10','BudgetSelect10','PoolMinAWCT10','B0AssignmentReorder')


def make_method(name,initial,theta=.1):
    if name in ('B0','B1','B2'):return Baseline(name)
    if name=='LegacySAIL':return SAILPolicy(OnlineReference.from_initial(initial),3,0)
    if name=='QueueRepair0':return BudgetPolicy(0)
    if name=='BudgetHEFT10':return BudgetPolicy(theta)
    if name=='BudgetSelect10':return BudgetSelect(OnlineReference.from_initial(initial),theta)
    if name=='PoolMinAWCT10':return PoolMinAWCT(OnlineReference.from_initial(initial),theta)
    if name=='B0AssignmentReorder':return B0AssignmentReorder()
    raise ModelError('unknown v2 method')


def synthetic_v2(root_seed,mix):
    if root_seed in range(71000,71020):i=root_seed-71000
    elif root_seed in range(72000,72010):i=root_seed-72000
    else:raise ModelError('v2 synthetic development/validation only')
    kinds={'A':'LRF','B':'LLR','C':'RFF'}[mix];tasks=[];files=[]
    for q,kind in enumerate(kinds):
        n,wid=(48,64,80)[(i+q)%3],f'w{q:02d}';rng=random_stream(root_seed,mix,'synthetic',wid)
        if kind=='L':edges={(j,j+1) for j in range(n-1)}
        elif kind=='F':edges={(0,j) for j in range(1,n-1)}|{(j,n-1) for j in range(1,n-1)}
        else:
            layers=[list(range(layer,n,8)) for layer in range(8)]
            edges={(u,v) for a,b in zip(layers,layers[1:]) for u in a for v in b if rng.random()<.25}
            for v in range(n):
                layer=v%8
                if layer>0 and not any(b==v for a,b in edges):edges.add((int(rng.choice(layers[layer-1])),v))
                if layer<7 and not any(a==v for a,b in edges):edges.add((v,int(rng.choice(layers[layer+1]))))
        work=rng.lognormal(0,.8,n);work/=work.mean();parents={j:[] for j in range(n)};inputs={j:[] for j in range(n)}
        ids=[f'{wid}::t{j:04d}' for j in range(n)]
        for u,v in sorted(edges):
            fid=f'{wid}::f{u:04d}_{v:04d}';files.append(DataFile(fid,float(rng.lognormal(0,1)),ids[u]));parents[v].append(ids[u]);inputs[v].append(fid)
        tasks.extend(Task(ids[j],wid,float(work[j]),tuple(sorted(parents[j])),tuple(sorted(inputs[j]))) for j in range(n))
    return Workload(tuple(tasks),tuple(files))
