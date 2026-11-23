import hashlib
import itertools
import json
import math
from pathlib import Path

import pytest

from sail.development import dump
from sail.model import Failure,ModelError,Platform
from sail.scheduling import initial_heft
from sail.simulator import Simulator
from tests.helpers import graph
from v2_preparation.adapters import CorpusV2
from v2_preparation.experiment import METHODS,make_method,synthetic_v2
from v2_preparation.frozen import execute_v2,verify_v2

ROOT=Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('mask,theta',itertools.product(range(12),(0,.05,.1,.2,.5,1)))
def test_budget_grid_and_endpoint_aliases(mask,theta):
    edges=[(u,v,1) for i,(u,v) in enumerate(itertools.combinations('abcd',2)) if mask&(1<<i)]
    w=graph({'a':1,'b':2,'c':.5,'d':3,'e':2},edges,{'a':'x','b':'x','c':'x','d':'x','e':'y'})
    p=Platform((1,1.5,.8),2.75);initial=initial_heft(w,p);ref=Simulator(w,p,initial.plan).run();f=Failure(.3*ref.makespan,mask%3)
    runs={m:Simulator(w,p,initial.plan,failure=f,repair=make_method(m,initial,theta)).run() for m in ('BudgetHEFT10','BudgetSelect10','PoolMinAWCT10')}
    assert all(r.churn<=theta+1e-12 for r in runs.values())
    if theta in (0,1):
        equivalent=Simulator(w,p,initial.plan,failure=f,repair=make_method('QueueRepair0' if theta==0 else 'B2',initial)).run()
        assert equivalent==runs['BudgetHEFT10']


def test_unseen_adapter_cartesian_mix_and_namespace():
    c=CorpusV2(ROOT)
    assert len({c.mix_ids('A',s) for s in range(81000,81008)})==8
    for mix in 'ABC':
        for s in range(81000,81008):
            w=c.load_mix(mix,s);assert len(w.tasks)==sum(c.records[x]['tasks'] for x in c.mix_ids(mix,s))
    with pytest.raises(ModelError):c.mix_ids('A',60000)


def test_synthetic_namespace_is_disjoint():
    from sail.data import synthetic_workload
    assert synthetic_v2(71000,'A')!=synthetic_workload(10000,'A')
    assert synthetic_v2(71000,'A')==synthetic_v2(71000,'A')
    with pytest.raises(ModelError):synthetic_v2(81000,'A')


def fixture_freeze(folder):
    w=graph({'a':1,'b':2,'c':.5,'d':3},[('a','b',1)],{'a':'x','b':'x','c':'y','d':'z'})
    dump(folder/'workload.json',w);dump(folder/'truth.json',{t.id:t.work for t in w.tasks})
    base={'id':'fixture','workload_file':'workload.json','truth_file':'truth.json','speeds':[1,1.5,.8],'bandwidth':2.75}
    s={'id':'s','base_id':'fixture','root_seed':0,'mix':'A','nodes':3,'ccr':.5,'failure_fraction':.3,'variant':'main','failed_node':0,'control_delay_pbar_units':0}
    jobs=[{'id':'ref-fixture','kind':'reference','base_id':'fixture'}]
    jobs += [{'id':'run-s-'+m,'kind':'failure','base_id':'fixture','scenario_id':'s','method':m,'reference_b0_job':'run-s-B0'} for m in METHODS]
    jobs.append({'id':'alias','kind':'failure','base_id':'fixture','scenario_id':'s','method':'BudgetHEFT_theta0','budget_theta':0,'execution_alias_of':'run-s-QueueRepair0'})
    dump(folder/'scenario_manifest.json',{'bases':[base],'scenarios':[s],'jobs':jobs})
    dump(folder/'freeze.json',{'status':'FROZEN_G2_V2','purpose':'CORRECTNESS_FIXTURE','code_files':[]})
    dump(folder/'inputs_manifest.json',{'files':[{'path':p.name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(folder.iterdir()) if p.name!='inputs_manifest.json']})


def test_checkpoint_alias_coverage_and_tamper_rejection(tmp_path):
    freeze=tmp_path/'fixture';freeze.mkdir();fixture_freeze(freeze);out=tmp_path/'output'
    assert not execute_v2(ROOT,freeze,out,5)['all_complete']
    r=execute_v2(ROOT,freeze,out);assert r['all_complete'] and r['completed_labels']==11 and r['physical_executions']==10 and r['alias_records']==1
    rows=[json.loads(x) for x in (out/'metrics.jsonl').read_text().splitlines()]
    alias=rows[-1];source=next(x for x in rows if x['job_id']=='run-s-QueueRepair0')
    assert alias['event_file']==source['event_file'] and alias['churn']==0 and alias['full_application_seconds'] is None
    path=freeze/'workload.json';original=path.read_bytes();path.write_bytes(original+b' ')
    with pytest.raises(ValueError,match='checksum'):verify_v2(ROOT,freeze)
    path.write_bytes(original)
    event=out/source['event_file'];event.write_bytes(event.read_bytes()+b' ')
    with pytest.raises(ValueError,match='checkpoint'):execute_v2(ROOT,freeze,out)
