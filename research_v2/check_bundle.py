"""Verify unchanged v1 evidence, all exploratory outputs and independent arithmetic."""
import hashlib
import json
import math
import sys
from collections import Counter
from functools import lru_cache
from pathlib import Path

import numpy as np

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from sail.development import dump
from sail.frozen import verify_freeze


def main():
    folder=ROOT/'research_v2';old=ROOT/'results/g2_v1_20261025'
    _,mf=verify_freeze(ROOT,ROOT/'freeze/g2_v1_20261025')
    old_delivery=json.loads((ROOT/'reports/p4/delivery_manifest.json').read_text())
    for e in old_delivery['files']:assert hashlib.sha256((ROOT/e['path']).read_bytes()).hexdigest()==e['sha256'],e['path']
    legacy=[json.loads(x) for x in (old/'metrics.jsonl').read_text().splitlines()];old_by_id={r['job_id']:r for r in legacy}
    for directory in ('pilot','order_pilot'):
        marker=json.loads((folder/directory/'RUN_MANIFEST.json').read_text())
        for path,h in marker['source_sha256'].items():assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==h
    rows=[];events=0
    @lru_cache(maxsize=12)
    def old_doc(job_id):return json.loads((old/old_by_id[job_id]['event_file']).read_text())
    @lru_cache(maxsize=8)
    def pbar(root,mix):
        tasks=json.loads((ROOT/f'freeze/g2_v1_20261025/public/workloads/{root}-{mix}.json').read_text())['tasks']
        return sum(t['work'] for t in tasks)/len(tasks)
    for directory in ('pilot','order_pilot'):
        group=[json.loads(x) for x in (folder/directory/'metrics.jsonl').read_text().splitlines()]
        for r in group:
            path=folder/directory/r['event_file'];assert hashlib.sha256(path.read_bytes()).hexdigest()==r['event_sha256']
            d=json.loads(path.read_text());b0=old_doc('run-'+r['scenario_id']+'-B0');ref=old_doc('ref-'+r['base_id'])
            assert d['context']==b0['context'];context=d['context'];P=context['P'];Q=set(context['Q']);F=set(context['F'])
            old_assignment=dict(context['old_assignment']);new={v:j for j,q in enumerate(d['applied_plan']['queues']) for v in q}
            moves=sum(new[v]!=old_assignment[v] for v in Q-F)
            theta=0 if r['method'] in {'QueueRepair0','B0AssignmentReorder'} else .1
            assert moves<=math.floor(theta*max(1,len(Q))) and abs(r['churn']-moves/max(1,len(Q)))<1e-12
            if r['method']=='B0AssignmentReorder':
                assert new=={v:j for j,q in enumerate(b0['applied_plan']['queues']) for v in q}
            starts=dict(d['starts']);base=dict(ref['starts'])
            cdi=sum(max(0,starts[v]-base[v]) for v in P)/len(P)/pbar(r['root_seed'],r['mix'])
            assert math.isclose(cdi,r['cdi'],rel_tol=1e-10,abs_tol=1e-9)
            assert r['awct']==d['awct'] and r['makespan']==d['makespan']
            events+=len(d['events']);rows.append(r)
    assert len(rows)==3600 and len({(r['scenario_id'],r['method']) for r in rows})==3600
    assert Counter(r['method'] for r in rows)=={'QueueRepair0':900,'BudgetHEFT10':900,'BudgetSelect10':900,'B0AssignmentReorder':900}
    expected={s['id'] for s in mf['scenarios']}
    assert all({r['scenario_id'] for r in rows if r['method']==m}==expected for m in {r['method'] for r in rows})
    allrows=rows+[{**r,'method':'LegacySAIL' if r['method']=='SAIL' else r['method']} for r in legacy if r['kind']=='failure']
    stats=json.loads((folder/'reports/pilot_statistics.json').read_text())['effects'];checks=0
    def independent(method,comparator,variant,result):
        nonlocal checks
        grid={}
        for r in allrows:
            if r['variant']==variant and r['method'] in (method,comparator):grid.setdefault((r['root_seed'],r['mix'],r['nodes'],r['ccr'],r['failure_fraction']),{})[r['method']]=r
        roots={}
        for key,p in grid.items():
            a,b=p[method],p[comparator];assert a['protected_count']==b['protected_count']>0
            roots.setdefault(key[0],[]).append((a['cdi']-b['cdi'],a['awct']/b['awct']-1))
        assert len({len(x) for x in roots.values()})==1
        means=np.array([np.mean(roots[k],axis=0) for k in sorted(roots)])
        rng=np.random.Generator(np.random.PCG64(73000));sample=means[rng.integers(0,len(means),size=(5000,len(means)))].mean(axis=1)
        for j,metric in enumerate(('cdi','relative_awct')):
            e=result[metric];assert abs(means[:,j].mean()-e['point'])<1e-11
            assert np.max(np.abs(np.quantile(sample[:,j],[.025,.975])-e['ci95']))<1e-11
            assert abs(np.quantile(sample[:,j],.95)-e['upper95'])<1e-11;checks+=1
    for variant,g in stats.items():
        for method in ('QueueRepair0','BudgetHEFT10','BudgetSelect10','B0AssignmentReorder'):
            for comparator in ('B2','LegacySAIL'):independent(method,comparator,variant,g[method][comparator])
        for contrast,(method,comparator) in {'QueueRepair0_vs_B0':('QueueRepair0','B0'),'B0AssignmentReorder_vs_B0':('B0AssignmentReorder','B0'),
                                             'BudgetSelect10_vs_BudgetHEFT10':('BudgetSelect10','BudgetHEFT10')}.items():
            independent(method,comparator,variant,g['mechanisms'][contrast])
    assert checks==88
    delivery=folder/'delivery_manifest.json'
    if delivery.exists():
        for e in json.loads(delivery.read_text())['files']:assert hashlib.sha256((ROOT/e['path']).read_bytes()).hexdigest()==e['sha256'],e['path']
    result={'status':'PASS','G2_verified':True,'v1_delivery_files_unchanged':len(old_delivery['files']),'v1_formal_labels_unchanged':6960,
            'exploratory_physical_runs':3600,'event_files_rehashed':3600,'stored_event_records_checked':events,'independent_statistical_metrics_checked':checks,
            'hard_optional_assignment_budget_violations':0,'locked_control_B0_assignment_mismatches':0,
            'new_independent_test_sets':0,'original_G3_status':'NOT_SUPPORTED'}
    dump(folder/'reports/bundle_check.json',result);print(json.dumps(result))


if __name__=='__main__':main()
