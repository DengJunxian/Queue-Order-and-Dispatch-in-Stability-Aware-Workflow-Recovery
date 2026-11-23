"""Prespecified robustness/stratum views using the unchanged G2 estimator."""
import csv
import json
import statistics
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from sail.development import dump
from sail.frozen import verify_freeze
from sail.statistics import paired_bootstrap


def write_csv(path,rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)


def main():
    cfg,_=verify_freeze(ROOT,ROOT/'freeze/g2_v1_20261025')
    out=ROOT/'results/g2_v1_20261025';folder=ROOT/'reports/p4'
    rows=[json.loads(x) for x in (out/'metrics.jsonl').read_text().splitlines()]
    rows=[r for r in rows if r['kind']=='failure']
    rule=cfg['statistical_rule'];kw={'repetitions':rule['repetitions'],'seed':rule['seed']}
    primary=json.loads((out/'statistics.json').read_text())
    main_rows=[r for r in rows if r['variant']=='main']
    robustness={}
    for name in ('main_subset','cv0.1','cv0.3','control_delay'):
        view=([r for r in main_rows if r['root_seed']<60010 and r['nodes']==4 and r['failure_fraction']==0.6]
              if name=='main_subset' else [r for r in rows if r['variant']==name])
        assert len({r['scenario_id'] for r in view})==60
        # Only the local analysis view is relabelled; immutable raw rows retain their original variant.
        result=paired_bootstrap([{**r,'variant':'main'} for r in view],'B2',**kw)
        robustness[name]={'source_variant':name,'scenario_count':60,'statistics':result}
        print('robustness '+name,flush=True)
    strata={}
    for axis in ('mix','nodes','ccr','failure_fraction'):
        levels=sorted({r[axis] for r in main_rows})
        strata[axis]={}
        for level in levels:
            strata[axis][str(level)]=paired_bootstrap([r for r in main_rows if r[axis]==level],'B2',**kw)
        print('stratum '+axis,flush=True)
    summary=[]
    for variant in sorted({r['variant'] for r in rows}):
        for method in sorted({r['method'] for r in rows if r['variant']==variant}):
            group=[r for r in rows if r['variant']==variant and r['method']==method]
            cdi=[r['cdi'] for r in group if r['cdi'] is not None]
            summary.append({'variant':variant,'method':method,'scenarios':len(group),'CDI_defined':len(cdi),'CDI_NA':len(group)-len(cdi),
                            'mean_AWCT_seconds':statistics.mean(r['awct'] for r in group),
                            'mean_CDI':statistics.mean(cdi) if cdi else None,'mean_Churn':statistics.mean(r['churn'] for r in group),
                            'alias_records':sum(r['status']=='ALIAS' for r in group)})
    effects=[]
    def append(group,label,s):
        for metric in ('cdi','relative_awct'):
            v=s[metric];ci=v['ci95']
            effects.append({'group':group,'label':label,'comparator':s['comparator'],'metric':metric,'point':v['point'],
                            'CI95_low':ci[0] if ci else None,'CI95_high':ci[1] if ci else None,'one_sided_upper95':v['upper95'],
                            'root_clusters':s['cluster_count'],'defined_pairs':v['defined_pairs'],'NA_pairs':v['undefined_pairs'],
                            'defined_draws':v['defined_bootstrap_draws'],'total_draws':s['repetitions']})
    append('primary','Overall',primary['primary'])
    for name,s in primary['mixes'].items():append('mix',name,s)
    for name,s in primary['mechanisms'].items():append('mechanism',name,s)
    for name,s in robustness.items():append('robustness',name,s['statistics'])
    for axis,levels in strata.items():
        for level,s in levels.items():append('stratum:'+axis,level,s)
    result={'robustness':robustness,'strata':strata,'method_summary':summary,
            'interpretation':'Robustness and strata are prespecified descriptive views; primary hypothesis remains the frozen main comparison.',
            'frozen_estimator_used':True,'raw_rows_modified':False,'p_values_reported':False}
    dump(folder/'extended_statistics.json',result)
    write_csv(folder/'data/method_summary.csv',summary);write_csv(folder/'data/paired_effects.csv',effects)


if __name__=='__main__':main()
