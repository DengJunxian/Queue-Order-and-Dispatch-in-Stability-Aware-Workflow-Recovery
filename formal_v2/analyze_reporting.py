"""Derived tables and independent statistical verification; frozen gates unchanged."""
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from formal_v2.audit_outputs import write_csv
from sail.development import dump
from sail.statistics import paired_bootstrap
from v2_preparation.frozen import verify_v2


def independent_bootstrap(view,target,comparator):
    indexed={}
    for r in view:
        if r['method'] not in (target,comparator):continue
        key=(r['root_seed'],r['mix'],r['nodes'],r['ccr'],r['failure_fraction'],r['method'])
        assert key not in indexed;indexed[key]=r
    roots=sorted({k[0] for k in indexed});cells=sorted({k[1:5] for k in indexed});mixes=sorted({c[0] for c in cells})
    values=np.full((len(roots),len(cells),2),np.nan)
    for i,root in enumerate(roots):
        for j,cell in enumerate(cells):
            a=indexed[(root,*cell,target)];b=indexed[(root,*cell,comparator)]
            assert a['protected_count']==b['protected_count']
            if a['protected_count']:
                assert a['cdi'] is not None and b['cdi'] is not None;values[i,j,0]=a['cdi']-b['cdi']
            else:assert a['cdi'] is None and b['cdi'] is None
            values[i,j,1]=a['awct']/b['awct']-1
    rng=np.random.Generator(np.random.PCG64(83000));indices=rng.integers(0,len(roots),size=(5000,len(roots)))
    counts=np.zeros((5000,len(roots)),dtype=np.int32)
    np.add.at(counts,(np.repeat(np.arange(5000),len(roots)),indices.ravel()),1)
    allcounts=np.vstack((np.ones((1,len(roots)),dtype=np.int32),counts));out={}
    for k,name in enumerate(('cdi','relative_awct')):
        arr=values[:,:,k];mask=np.isfinite(arr);sums=allcounts@np.where(mask,arr,0);denom=allcounts@mask.astype(np.int32)
        cellmeans=np.divide(sums,denom,out=np.full(sums.shape,np.nan),where=denom>0);mixmeans=[]
        for mix in mixes:
            part=cellmeans[:,[j for j,c in enumerate(cells) if c[0]==mix]];valid=np.isfinite(part);n=valid.sum(axis=1)
            mixmeans.append(np.divide(np.nansum(part,axis=1),n,out=np.full(len(allcounts),np.nan),where=n>0))
        estimates=np.mean(np.stack(mixmeans),axis=0);point=estimates[0];draws=estimates[1:];defined=np.isfinite(draws)
        out[name]={'point':float(point) if np.isfinite(point) else None,'defined_pairs':int(mask.sum()),'undefined_pairs':int((~mask).sum()),
                   'defined_bootstrap_draws':int(defined.sum()),'ci95':[float(x) for x in np.quantile(draws,[.025,.975])] if defined.all() else None,
                   'upper95':float(np.quantile(draws,.95)) if defined.all() else None}
    return out


def main():
    folder=ROOT/'formal_v2/reports';out=ROOT/'results/g2_v2_20261025';freeze=ROOT/'freeze/g2_v2_20261025'
    verify_v2(ROOT,freeze);audit=json.loads((folder/'audit_summary.json').read_text());assert audit['status']=='PASS'
    rows=json.loads((folder/'data/run_metrics.json').read_text());frozen=json.loads((out/'statistics.json').read_text())
    mainrows=[r for r in rows if r['variant']=='main'];comparisons=[];flat=[];errors=[];independent_results={}
    def register(group,label,view,target,comparator,result):
        observed=independent_bootstrap(view,target,comparator)
        independent_results[group,label,comparator]=observed
        for metric in ('cdi','relative_awct'):
            e=result[metric];v=observed[metric]
            for key in ('defined_pairs','undefined_pairs','defined_bootstrap_draws'):assert e[key]==v[key],(label,metric,key)
            for key in ('point','upper95'):
                assert (e[key] is None)==(v[key] is None)
                if e[key] is not None:errors.append(abs(e[key]-v[key]))
            assert (e['ci95'] is None)==(v['ci95'] is None)
            if e['ci95'] is not None:errors.extend(abs(a-b) for a,b in zip(e['ci95'],v['ci95']))
            ci=e['ci95'];flat.append({'group':group,'label':label,'target':target,'comparator':comparator,'metric':metric,
                'point':e['point'],'CI95_low':ci[0] if ci else None,'CI95_high':ci[1] if ci else None,'one_sided_upper95':e['upper95'],
                'root_blocks':result['cluster_count'],'defined_pairs':e['defined_pairs'],'NA_pairs':e['undefined_pairs'],'defined_draws':e['defined_bootstrap_draws'],'total_draws':5000})
        comparisons.append(group+':'+label+':'+comparator)
    for comparator,g in frozen['primary'].items():
        register('primary','Overall',mainrows,'BudgetSelect10',comparator,g['overall'])
        for mix,s in g['mixes'].items():register('mix',mix,[r for r in mainrows if r['mix']==mix],'BudgetSelect10',comparator,s)
    for variant,group in frozen['robustness'].items():
        view=[r for r in rows if r['variant']==variant]
        for comparator,s in group.items():register('robustness',variant,view,'BudgetSelect10',comparator,s)
    for key,(target,comparator) in {'BudgetSelect10_vs_B2':('BudgetSelect10','B2'),'B0AssignmentReorder_vs_B0':('B0AssignmentReorder','B0'),'QueueRepair0_vs_B0':('QueueRepair0','B0')}.items():
        register('mechanism',key,mainrows,target,comparator,frozen['secondary'][key])
    for tag,group in frozen['budget_sensitivity'].items():
        view=[r for r in rows if r['variant']=='theta'+tag]
        for comparator,s in group.items():register('theta',tag,view,'BudgetSelect_theta'+tag,comparator+'_theta'+tag,s)
    frozen_checks=len(comparisons)*2
    supplemental={'theta0.1':{},'strata':{}}
    subset=[r for r in mainrows if r['root_seed']<81010 and r['nodes']==4 and r['failure_fraction']==.6]
    def extra(view,target,comparator):
        mapped=[{**r,'variant':'main','method':'SAIL' if r['method']==target else r['method']} for r in view if r['method'] in (target,comparator)]
        return paired_bootstrap(mapped,comparator,repetitions=5000,seed=83000)
    for comparator in ('PoolMinAWCT10','BudgetHEFT10'):
        s=extra(subset,'BudgetSelect10',comparator);supplemental['theta0.1'][comparator]=s
        register('theta','0.1',subset,'BudgetSelect10',comparator,s)
    for axis in ('nodes','ccr','failure_fraction'):
        supplemental['strata'][axis]={}
        for level in sorted({r[axis] for r in mainrows}):
            view=[r for r in mainrows if r[axis]==level];supplemental['strata'][axis][str(level)]={}
            for comparator in ('PoolMinAWCT10','BudgetHEFT10'):
                s=extra(view,'BudgetSelect10',comparator);supplemental['strata'][axis][str(level)][comparator]=s
                register('descriptive_stratum',axis+'='+str(level),view,'BudgetSelect10',comparator,s)
    assert max(errors,default=0)<1e-8
    for comparator,expected in frozen['primary_gates'].items():
        independent=independent_results['primary','Overall',comparator];cdi=independent['cdi'];awct=independent['relative_awct']
        gates={'CDI_upper_below_zero':cdi['ci95'] is not None and cdi['ci95'][1]<0,
               'AWCT_upper_within_5pct':awct['upper95'] is not None and awct['upper95']<=.05,
               'at_least_two_mix_directions':sum(independent_results['mix',m,comparator]['cdi']['point'] is not None and independent_results['mix',m,comparator]['cdi']['point']<0 for m in 'ABC')>=2}
        assert gates==expected,(comparator,gates,expected)
    groups=defaultdict(list)
    for r in rows:groups[r['variant'],r['method']].append(r)
    summaries=[]
    for (variant,method),g in sorted(groups.items()):
        cdi=[r['cdi'] for r in g if r['cdi'] is not None];order=[r['order_disturbance'] for r in g if r['order_disturbance'] is not None]
        apps=[r['full_application_seconds'] for r in g if r['full_application_seconds'] is not None]
        qualities=[r for r in g if r['quality_feasible'] is not None]
        summaries.append({'variant':variant,'method':method,'labels':len(g),'root_blocks':len({r['root_seed'] for r in g}),'CDI_defined':len(cdi),'CDI_NA':len(g)-len(cdi),
            'mean_AWCT':statistics.mean(r['awct'] for r in g),'mean_CDI':statistics.mean(cdi) if cdi else None,'mean_Churn':statistics.mean(r['churn'] for r in g),
            'mean_order_disturbance':statistics.mean(order) if order else None,'order_NA':len(g)-len(order),'total_queue_pairs':sum(r['comparable_pairs'] for r in g),
            'quality_infeasible':sum(r['quality_feasible'] is False for r in qualities) if qualities else None,
            'actual_AWCT_gt_1.05_B2':sum(r['actual_AWCT_gt_1.05_B2'] for r in g),'threshold_rounding_disagreements':sum(r['actual_AWCT_gt_1.05_B2']!=r['actual_AWCT_gt_1.05_B2_tolerant'] for r in g),
            'predicted_feasible_but_actual_over':sum(r['quality_feasible'] is True and r['actual_AWCT_gt_1.05_B2'] for r in g) if qualities else None,
            'full_apply_samples':len(apps),'full_apply_p50_seconds':statistics.median(apps) if apps else None,'full_apply_p95_seconds':float(np.quantile(apps,.95)) if apps else None,
            'alias_records':sum(r['status']=='ALIAS' for r in g),'mean_signed_delay_vs_B0':statistics.mean(r['same_fault_signed_delay'] for r in g if r['same_fault_signed_delay'] is not None) if cdi else None})
    write_csv(folder/'data/paired_effects.csv',flat);write_csv(folder/'data/method_summary.csv',summaries)
    dump(folder/'reporting_statistics.json',{'purpose':'descriptive views accompanying unchanged frozen analysis','supplemental':supplemental,'method_summary':summaries,
        'new_primary_gate_defined':False,'p_values_reported':False,'independent_verification':{'status':'PASS','frozen_metric_results_checked':frozen_checks,
        'total_metric_results_checked':len(comparisons)*2,'comparison_labels':comparisons,'max_abs_numerical_difference':max(errors,default=0),'primary_gate_decisions_verified':True,
        'method':'vectorized multinomial root counts, cell-wise masked sums and explicit all-Mix NA propagation; independent of the sealed bootstrap loop'}})
    print(json.dumps({'independent_frozen_metric_checks':frozen_checks,'total_checks':len(comparisons)*2,'max_abs_error':max(errors,default=0),'G3_v2_supported':frozen['G3_v2_supported']}))


if __name__=='__main__':main()
