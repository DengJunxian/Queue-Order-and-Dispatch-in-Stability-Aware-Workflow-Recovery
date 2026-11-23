"""Check P4 coverage, independent vectorized bootstrap arithmetic and stage artifacts."""
import csv
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
from pypdf import PdfReader

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from sail.development import dump
from sail.frozen import verify_freeze


def main():
    cfg,manifest=verify_freeze(ROOT,ROOT/'freeze/g2_v1_20261025')
    folder=ROOT/'reports/p4';out=ROOT/'results/g2_v1_20261025'
    audit=json.loads((folder/'audit_summary.json').read_text())
    assert audit['status']=='PASS' and audit['nominal_labels']==6960 and audit['physical_executions']==6240 and audit['alias_records']==720
    assert audit['raw_metrics_sha256']==hashlib.sha256((out/'metrics.jsonl').read_bytes()).hexdigest()
    rows=[json.loads(x) for x in (out/'metrics.jsonl').read_text().splitlines()]
    assert {r['job_id'] for r in rows}=={r['id'] for r in manifest['jobs']} and len(rows)==6960
    raw={r['job_id']:r for r in rows if r['kind']=='failure'}
    table=list(csv.DictReader((folder/'data/run_metrics.csv').open()))
    assert len(table)==6480 and {r['job_id'] for r in table}==set(raw)
    for r in table:
        x=raw[r['job_id']]
        for key in ('awct','makespan','cdi','churn'):assert abs(float(r[key])-x[key])<1e-10
        assert int(r['protected_count'])>0
        if r['method']=='NoChurn':assert not r['policy_callback_seconds'] and r['execution_alias_of']
    primary=json.loads((out/'statistics.json').read_text());extended=json.loads((folder/'extended_statistics.json').read_text())
    diag=json.loads((folder/'diagnostic_summary.json').read_text());secondary=json.loads((folder/'secondary_summary.json').read_text())
    assert diag['status']=='PASS' and diag['exact_trace_replays']==1120 and diag['new_independent_scenarios']==0
    assert sum(v['scenarios'] for v in diag['by_mix'].values())==720
    assert secondary['workflow_rows']==19440 and secondary['failure_label_rows']==6480
    failure=list(raw.values());main=[r for r in failure if r['variant']=='main']
    checks=[]
    def independent(view,expected,label):
        comparator=expected['comparator'];bykey={}
        for r in view:
            if r['method'] not in {'SAIL',comparator}:continue
            key=(r['root_seed'],r['mix'],r['nodes'],r['ccr'],r['failure_fraction'])
            bykey.setdefault(key,{})[r['method']]=r
        perroot={}
        for key,pair in bykey.items():
            a,b=pair['SAIL'],pair[comparator]
            assert a['protected_count']>0 and b['protected_count']>0
            perroot.setdefault(key[0],[]).append((a['cdi']-b['cdi'],a['awct']/b['awct']-1))
        # Complete balanced cells and no NA imply that root means can be resampled directly.
        assert len({len(v) for v in perroot.values()})==1
        means=np.array([np.mean(perroot[k],axis=0) for k in sorted(perroot)])
        rng=np.random.Generator(np.random.PCG64(73000));indices=rng.integers(0,len(means),size=(5000,len(means)))
        draws=means[indices].mean(axis=1)
        for j,metric in enumerate(('cdi','relative_awct')):
            e=expected[metric];point=means[:,j].mean();ci=np.quantile(draws[:,j],[.025,.975]);upper=np.quantile(draws[:,j],.95)
            assert abs(point-e['point'])<1e-11 and np.max(np.abs(ci-e['ci95']))<1e-11 and abs(upper-e['upper95'])<1e-11,(label,metric)
            checks.append(label+':'+metric)
    independent(main,primary['primary'],'primary')
    for m,s in primary['mixes'].items():independent([r for r in main if r['mix']==m],s,'mix:'+m)
    for m,s in primary['mechanisms'].items():independent(main,s,'mechanism:'+m)
    for name,v in extended['robustness'].items():
        view=([r for r in main if r['root_seed']<60010 and r['nodes']==4 and r['failure_fraction']==.6]
              if name=='main_subset' else [r for r in failure if r['variant']==name])
        independent(view,v['statistics'],'robustness:'+name)
    for axis,levels in extended['strata'].items():
        for level,s in levels.items():independent([r for r in main if str(r[axis])==level],s,'stratum:'+axis+':'+level)
    fm=json.loads((folder/'figures/figure_manifest.json').read_text())
    assert len(fm['figures'])==4
    for figure in fm['figures']:
        for ext,h in figure['exports_sha256'].items():assert hashlib.sha256((folder/'figures'/f"{figure['name']}.{ext}").read_bytes()).hexdigest()==h
        for path,h in figure['source_sha256'].items():assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==h
        pdf=PdfReader(folder/'figures'/f"{figure['name']}.pdf")
        fonts=pdf.pages[0]['/Resources']['/Font'].get_object()
        for font in fonts.values():
            font=font.get_object();children=font.get('/DescendantFonts',[font])
            for child in children:
                descriptor=child.get_object()['/FontDescriptor'].get_object()
                assert any(key in descriptor for key in ('/FontFile','/FontFile2','/FontFile3'))
    delivery=folder/'delivery_manifest.json'
    if delivery.exists():
        for entry in json.loads(delivery.read_text())['files']:
            assert hashlib.sha256((ROOT/entry['path']).read_bytes()).hexdigest()==entry['sha256'],entry['path']
    result={'status':'PASS','freeze_verified':True,'complete_labels':6960,'processed_failure_rows':6480,'independent_statistic_checks':len(checks),
            'statistic_check_names':checks,'independent_arithmetic':'Balanced, fully defined cells: vectorized bootstrap of per-root means, separate implementation from frozen estimator.',
            'raw_log_reaudit':'All 6240 event files and 4662517 events previously independently audited; raw metrics hash matches that receipt.',
            'diagnostic_trace_replays':1120,'figure_exports_verified':12,'G3_primary_support':bool(primary['CDI_interval_supports_improvement'] and primary['AWCT_budget_supported'] and primary['at_least_two_mix_directions'])}
    dump(folder/'bundle_check.json',result);print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
