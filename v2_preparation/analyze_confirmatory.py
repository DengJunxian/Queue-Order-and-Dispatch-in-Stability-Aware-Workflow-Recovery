"""Prespecified v2 analysis with the unchanged root-block bootstrap estimator."""
import argparse
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from sail.development import dump
from sail.statistics import paired_bootstrap
from v2_preparation.frozen import verify_v2


def analyze(freeze,output):
    cfg,mf=verify_v2(ROOT,freeze);output=Path(output);summary=json.loads((output/'execution_summary.json').read_text())
    rows=[json.loads(x) for x in (output/'metrics.jsonl').read_text().splitlines()]
    if not summary['all_complete'] or len(rows)!=len(mf['jobs']) or {r['job_id'] for r in rows}!={j['id'] for j in mf['jobs']}:raise ValueError('incomplete/duplicated v2 results')
    failure=[r for r in rows if r['kind']=='failure'];main=[r for r in failure if r['variant']=='main']
    def compare(view,method,comparator):
        mapped=[{**r,'variant':'main','method':'SAIL' if r['method']==method else r['method']} for r in view if r['method'] in (method,comparator)]
        return paired_bootstrap(mapped,comparator,repetitions=5000,seed=83000)
    primary={};gates={}
    for comparator in ('PoolMinAWCT10','BudgetHEFT10'):
        overall=compare(main,'BudgetSelect10',comparator);mixes={m:compare([r for r in main if r['mix']==m],'BudgetSelect10',comparator) for m in 'ABC'}
        c=overall['cdi'];a=overall['relative_awct'];primary[comparator]={'overall':overall,'mixes':mixes}
        gates[comparator]={'CDI_upper_below_zero':c['ci95'] is not None and c['ci95'][1]<0,'AWCT_upper_within_5pct':a['upper95'] is not None and a['upper95']<=.05,
                           'at_least_two_mix_directions':sum(v['cdi']['point'] is not None and v['cdi']['point']<0 for v in mixes.values())>=2}
    robust={v:{c:compare([r for r in failure if r['variant']==v],'BudgetSelect10',c) for c in ('PoolMinAWCT10','BudgetHEFT10','B2')} for v in ('cv0.1','cv0.3','control_delay')}
    secondary={'BudgetSelect10_vs_B2':compare(main,'BudgetSelect10','B2'),'B0AssignmentReorder_vs_B0':compare(main,'B0AssignmentReorder','B0'),'QueueRepair0_vs_B0':compare(main,'QueueRepair0','B0')}
    sensitivity={}
    for theta in (0,.05,.2,.5,1):
        tag=format(theta,'g');view=[r for r in failure if r['variant']=='theta'+tag]
        sensitivity[tag]={c:compare(view,'BudgetSelect_theta'+tag,c+'_theta'+tag) for c in ('PoolMinAWCT','BudgetHEFT')}
    violations=[]
    for r in failure:
        if r['method'].startswith(('Budget','PoolMin')) and r['churn']>r['budget_theta']+1e-12:violations.append(r['job_id'])
    result={'purpose':'CONFIRMATORY_V2','primary':primary,'primary_gates':gates,'hard_budget_violations':violations,
            'G3_v2_supported':all(all(g.values()) for g in gates.values()) and not violations,'robustness':robust,'secondary':secondary,'budget_sensitivity':sensitivity,
            'quality_infeasible':{m:sum(r.get('quality_feasible') is False for r in main if r['method']==m) for m in ('BudgetSelect10','PoolMinAWCT10')},
            'CDI_NA_main_labels':sum(r.get('cdi') is None for r in main),'p_values_reported':False,'original_v1_G3':'NOT_SUPPORTED'}
    dump(output/'statistics.json',result);return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--freeze',default=str(ROOT/'freeze/g2_v2_20261025'));p.add_argument('--output',default=str(ROOT/'results/g2_v2_20261025'));a=p.parse_args()
    r=analyze(Path(a.freeze),Path(a.output));print(json.dumps({'G3_v2_supported':r['G3_v2_supported'],'budget_violations':len(r['hard_budget_violations'])}))
