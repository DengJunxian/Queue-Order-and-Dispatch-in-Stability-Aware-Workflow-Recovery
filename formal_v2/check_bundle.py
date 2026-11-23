"""Final evidence-chain checks, without re-running any scientific experiment."""
import argparse
import csv
import json
import math
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

from PIL import Image
from pypdf import PdfReader

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from sail.development import dump
from v2_preparation.frozen import verify_v2,sha


def main(rehash_events=False):
    folder=ROOT/'formal_v2/reports';out=ROOT/'results/g2_v2_20261025';cfg,mf=verify_v2(ROOT,ROOT/'freeze/g2_v2_20261025')
    audit=json.loads((folder/'audit_summary.json').read_text());stats=json.loads((out/'statistics.json').read_text());reporting=json.loads((folder/'reporting_statistics.json').read_text())
    clock=json.loads((folder/'execution_wall_clock.json').read_text());assert clock['exit_code']==0
    post=json.loads((folder/'postprocess_summary.json').read_text())
    assert [s['stage'] for s in post['steps']]==['INDEPENDENT_LOG_AUDIT','FROZEN_STATISTICS','INDEPENDENT_STATISTICS_AND_TABLES','RESULT_FIGURES']
    assert all(s['exit_code']==0 for s in post['steps'])
    tests=list(ET.parse(folder/'reporting_pytest.xml').getroot().iter('testsuite'))
    assert sum(int(s.attrib['tests']) for s in tests)==4
    assert all(int(s.attrib.get(k,0))==0 for s in tests for k in ('errors','failures','skipped'))
    assert audit['status']=='PASS' and audit['nominal_labels']==15780 and audit['physical_executions']==15660 and audit['alias_records']==120
    assert sha(out/'metrics.jsonl')==audit['raw_metrics_sha256']
    rows=[json.loads(x) for x in (out/'metrics.jsonl').read_text().splitlines()];raw={r['job_id']:r for r in rows}
    assert len(rows)==len(raw)==len(mf['jobs'])==15780 and set(raw)=={j['id'] for j in mf['jobs']}
    assert Counter(r['status'] for r in rows)=={'COMPLETE':15660,'ALIAS':120}
    processed=json.loads((folder/'data/run_metrics.json').read_text());assert len(processed)==14940 and len({r['job_id'] for r in processed})==14940
    for r in processed:
        source=raw[r['job_id']]
        for key in ('awct','makespan','cdi','churn'):
            assert (r[key] is None)==(source[key] is None)
            if r[key] is not None:assert math.isclose(r[key],source[key],abs_tol=1e-8,rel_tol=1e-9)
        assert r['protected_count']==source['protected_count']
    verify=reporting['independent_verification']
    assert verify['status']=='PASS' and verify['frozen_metric_results_checked']==60 and verify['total_metric_results_checked']==88 and verify['primary_gate_decisions_verified']
    assert not stats['hard_budget_violations'] and audit['hard_budget_violations']==0 and audit['locked_assignment_mismatches']==0
    assert stats['G3_v2_supported']==all(all(g.values()) for g in stats['primary_gates'].values())
    historical=0
    for manifest in ('reports/p4/delivery_manifest.json','research_v2/delivery_manifest.json','v2_preparation/delivery_manifest.json'):
        for e in json.loads((ROOT/manifest).read_text())['files']:assert sha(ROOT/e['path'])==e['sha256'],e['path'];historical+=1
    figures=json.loads((folder/'figures/manifest.json').read_text());assert len(figures['figures'])==4 and figures['visual_inspection']!='pending'
    for figure in figures['figures']:
        for path,h in figure['source_sha256'].items():assert sha(ROOT/path)==h,path
        for ext,h in figure['exports_sha256'].items():assert sha(folder/'figures'/f"{figure['name']}.{ext}")==h
        with Image.open(folder/'figures'/f"{figure['name']}.png") as im:assert im.mode=='RGB' and min(im.info['dpi'])>=299
        reader=PdfReader(folder/'figures'/f"{figure['name']}.pdf");assert len(reader.pages)==1
        for font in reader.pages[0]['/Resources']['/Font'].get_object().values():
            obj=font.get_object()
            for child in obj.get('/DescendantFonts',[obj]):
                descriptor=child.get_object()['/FontDescriptor'].get_object();assert any(k in descriptor for k in ('/FontFile','/FontFile2','/FontFile3'))
    event_index={r['event_file']:r['event_sha256'] for r in rows};assert len(event_index)==15660
    if rehash_events:
        for path,h in event_index.items():assert sha(out/path)==h,path
    delivery=ROOT/'formal_v2/delivery_manifest.json'
    if delivery.exists():
        from formal_v2.make_delivery_manifest import delivery_paths
        sealed=json.loads(delivery.read_text())
        assert {e['path'] for e in sealed['files']}=={str(p.relative_to(ROOT)) for p in delivery_paths()}
        for path,h in sealed['prior_delivery_manifest_sha256'].items():assert sha(ROOT/path)==h,path
        assert sealed['freeze_id']==sha(ROOT/'freeze/g2_v2_20261025/inputs_manifest.json')
        assert sealed['G3_v2_supported']==stats['G3_v2_supported']
        for e in sealed['files']:
            assert (ROOT/e['path']).stat().st_size==e['bytes'],e['path']
            if e['path'].startswith('results/g2_v2_20261025/events/'):
                rel=e['path'].removeprefix('results/g2_v2_20261025/');assert event_index[rel]==e['sha256']
            else:assert sha(ROOT/e['path'])==e['sha256'],e['path']
    result={'status':'PASS','freeze_verified':True,'nominal_labels':15780,'physical_executions':15660,'alias_records':120,'reference_jobs':840,
        'persisted_logs_independently_audited':audit['event_records_independently_recomputed'],'independent_frozen_statistic_checks':60,
        'independent_total_statistic_checks':88,'max_abs_statistical_difference':verify['max_abs_numerical_difference'],'historical_file_checksums_unchanged':historical,
        'figure_exports_verified':12,'G3_v2_supported':stats['G3_v2_supported'],'original_v1_G3':'NOT_SUPPORTED'}
    dump(folder/'bundle_check.json',result);print(json.dumps(result))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--events',action='store_true',help='rehash all physical event files in addition to checking the earlier audit receipt');a=p.parse_args();main(a.events)
