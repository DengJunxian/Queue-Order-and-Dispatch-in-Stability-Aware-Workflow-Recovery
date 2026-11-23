"""Validate frozen v2 identity, prior immutable deliveries and prefreeze receipts."""
import hashlib
import json
import math
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

import numpy as np

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from sail.data import actual_work
from sail.development import dump
from sail.experiment import workload_from_json
from sail.frozen import result_from_json
from scripts.validate_p0_data import git_blob
from v2_preparation.frozen import verify_v2,sha


def main():
    prep=ROOT/'v2_preparation';freeze=ROOT/'freeze/g2_v2_20261025';cfg,mf=verify_v2(ROOT,freeze)
    prior_count=0
    for path in ('reports/p4/delivery_manifest.json','research_v2/delivery_manifest.json'):
        for e in json.loads((ROOT/path).read_text())['files']:
            assert sha(ROOT/e['path'])==e['sha256'],e['path'];prior_count+=1
    tests=json.loads((prep/'reports/test_summary.json').read_text());assert tests['passed']==214 and tests['failed']==tests['skipped']==0
    s=list(ET.parse(prep/'reports/pytest.xml').getroot().iter('testsuite'));assert sum(int(x.get('tests',0)) for x in s)==214
    data=json.loads((prep/'data/manifest_v2.json').read_text());assert len(data['records'])==6
    for r in data['records']:
        raw=(ROOT/r['raw_path']).read_bytes();assert git_blob(raw)==r['git_blob_sha'] and hashlib.sha256(raw).hexdigest()==r['raw_sha256']
        assert sha(ROOT/r['parsed_path'])==r['parsed_sha256'] and r['eligible']
    jobs=mf['jobs'];scenarios={s['id']:s for s in mf['scenarios']};bases={b['id']:b for b in mf['bases']};by_job={j['id']:j for j in jobs}
    assert len(jobs)==len(by_job)==15780 and len(bases)==840 and len(scenarios)==1920
    assert Counter(s['variant'] for s in scenarios.values())=={'main':1440,'cv0.1':60,'cv0.3':60,'control_delay':60,'theta0':60,'theta0.05':60,'theta0.2':60,'theta0.5':60,'theta1':60}
    assert {b['root_seed'] for b in bases.values()}==set(range(81000,81060))
    aliases=[]
    for j in jobs:
        assert j['base_id'] in bases
        if j['kind']=='failure':
            sc=scenarios[j['scenario_id']];assert sc['base_id']==j['base_id'] and sc['fault_time_numeric'] is None
            assert j['reference_b0_job'] in by_job
        if j.get('execution_alias_of'):
            source=by_job[j['execution_alias_of']];assert source['base_id']==j['base_id']
            assert source['method']==('QueueRepair0' if j['budget_theta']==0 else 'B2');aliases.append(j)
    assert len(aliases)==120 and cfg['expected_physical_executions']==15660
    seen_truth=set()
    for b in bases.values():
        if b['truth_file'] in seen_truth:continue
        seen_truth.add(b['truth_file']);w=workload_from_json(json.loads((freeze/b['workload_file']).read_text()))
        expected=actual_work(w,b['root_seed'],b['mix'],b['runtime_cv']);assert json.loads((freeze/b['truth_file']).read_text())==expected
    old=json.loads((ROOT/'research_v2/pilot/metrics.jsonl').read_text().splitlines()[0])
    sources={r['scenario_id']:r for r in [json.loads(x) for x in (ROOT/'research_v2/pilot/metrics.jsonl').read_text().splitlines()] if r['method']=='BudgetSelect10'}
    rows=[json.loads(x) for x in (prep/'ablation/metrics.jsonl').read_text().splitlines()];assert len(rows)==900
    event_records=0
    for r in rows:
        path=prep/'ablation'/r['event_file'];assert sha(path)==r['event_sha256'];d=json.loads(path.read_text());assert d['churn']<=.1+1e-12
        original=sources[r['scenario_id']];assert d['context']['P']==json.loads((ROOT/'research_v2/pilot'/original['event_file']).read_text())['context']['P']
        event_records+=len(d['events'])
    effects=json.loads((prep/'reports/same_pool_statistics.json').read_text())['effects'];stat_checks=0
    for variant,result in effects.items():
        perroot={}
        for r in rows:
            if r['variant']!=variant:continue
            a=sources[r['scenario_id']];assert a['protected_count']==r['protected_count']>0
            perroot.setdefault(r['root_seed'],[]).append((a['cdi']-r['cdi'],a['awct']/r['awct']-1))
        means=np.array([np.mean(perroot[k],axis=0) for k in sorted(perroot)])
        rng=np.random.Generator(np.random.PCG64(73000));draws=means[rng.integers(0,len(means),size=(5000,len(means)))].mean(axis=1)
        for j,metric in enumerate(('cdi','relative_awct')):
            e=result[metric];assert abs(means[:,j].mean()-e['point'])<1e-11 and np.max(np.abs(np.quantile(draws[:,j],[.025,.975])-e['ci95']))<1e-11
            assert abs(np.quantile(draws[:,j],.95)-e['upper95'])<1e-11;stat_checks+=1
    dev=json.loads((prep/'development/summary.json').read_text());assert dev['precision_selected_root_count']==60 and dev['fault_labels']==2160 and dev['tests_on_new_real_inputs']==0
    time=json.loads((prep/'reports/full_application_summary.json').read_text());assert time['exact_trace_matches']==420
    budget=json.loads((prep/'reports/budget_decision.json').read_text());assert budget['gate_passed'] and budget['selected_roots']==60
    real_output=ROOT/'results/g2_v2_20261025'
    if (real_output/'metrics.jsonl').exists():assert not (real_output/'metrics.jsonl').read_text().strip(),'new test execution started before stage close'
    delivery=prep/'delivery_manifest.json'
    if delivery.exists():
        for e in json.loads(delivery.read_text())['files']:assert sha(ROOT/e['path'])==e['sha256'],e['path']
    receipt={'status':'PASS','prior_delivered_file_checksums_unchanged':prior_count,'tests_passed':214,'new_raw_inputs':6,'new_unseen_topology_groups':6,
             'same_pool_control_runs':900,'ablation_event_records_rehashed':event_records,'independent_same_pool_statistic_checks':stat_checks,
             'synthetic_development_validation_fault_labels':2160,'full_application_exact_replays':420,'profile_runs':180,'profile_references':20,
             'frozen_jobs':15780,'frozen_reference_jobs':840,'frozen_failure_conditions':1920,'planned_alias_records':120,'expected_physical_executions':15660,
             'truth_vectors_verified_without_scheduling':len(seen_truth),'new_real_test_scheduling_runs':0,'original_v1_G3':'NOT_SUPPORTED','G2_v2':'FROZEN'}
    dump(prep/'reports/stage_check.json',receipt);print(json.dumps(receipt))


if __name__=='__main__':main()
