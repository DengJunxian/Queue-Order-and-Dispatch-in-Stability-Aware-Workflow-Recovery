"""Registered paired analyses with graph/root resampling and full cost tails."""
import warnings
from functools import lru_cache
from revision_r6.common import *
warnings.filterwarnings('ignore',message='Mean of empty slice')

def rows(path):return [json.loads(s) for s in Path(path).read_text().splitlines()]
def native(x):
    if isinstance(x,dict):return {k:native(v) for k,v in x.items()}
    if isinstance(x,(list,tuple)):return [native(v) for v in x]
    if isinstance(x,np.generic):return x.item() if np.isfinite(x) else None
    if isinstance(x,float) and not math.isfinite(x):return None
    return x

def main():
    import math
    global_math=math
    data=rows(OUT/'holdout/metrics.jsonl');assert read(OUT/'holdout/receipt.json')['status']=='PASS' and len(data)==4800
    corpus=HoldoutCorpus();graphs=sorted(corpus.records);families=sorted({r['family'] for r in corpus.records.values()})
    group=[[i for i,g in enumerate(graphs) if corpus.records[g]['family']==f] for f in families]
    rng=np.random.Generator(np.random.PCG64(93000));gi=[];ri=[]
    for indices in group:
        gi.append(np.asarray(indices)[rng.integers(0,3,size=(5000,3))]);ri.append(rng.integers(0,4,size=(5000,3,4)))
    gi=np.array(gi);ri=np.array(ri);(OUT/'analysis').mkdir(exist_ok=True)
    np.savez_compressed(OUT/'analysis/resamples.npz',graph_indices=gi,root_indices=ri)
    def point(a):return float(np.nanmean([np.nanmean(np.nanmean(a[g],axis=1)) for g in group]))
    def estimate(a):
        samples=np.nanmean([np.nanmean(np.nanmean(a[gi[f,:,:,None],ri[f]],axis=2),axis=1) for f in range(4)],axis=0)
        good=samples[np.isfinite(samples)]
        return {'point':point(a),'ci95':np.quantile(good,[.025,.975]).tolist() if len(good) else None,'defined_bootstrap_draws':len(good),'defined_graphs':int(np.sum(np.any(np.isfinite(a),axis=1))),'defined_graph_roots':int(np.sum(np.isfinite(a)))}
    index={(r['case_id'],r['network'],r['rule'],r['method']):r for r in data}
    @lru_cache(maxsize=None)
    def array(network,rule,method,metric,reference=None,relative=False):
        a=np.full((12,4),np.nan)
        for i,g in enumerate(graphs):
            for j,root in enumerate(range(91000,91004)):
                values=[]
                for r in data:
                    if r['graph_id']!=g or r['root']!=root or r['network']!=network or r['rule']!=rule or r['method']!=method:continue
                    v=r[metric]
                    if v is None:continue
                    if reference:
                        q=index[r['case_id'],network,rule,reference][metric]
                        if q is None:continue
                        v=v/q-1 if relative else v-q
                    values.append(v)
                if values:a[i,j]=np.mean(values)
        return a
    result={'status':'COMPLETE','classification':'EXPLORATORY','graph_count':12,'families':families,'cases':192,'method_count':10,'bootstrap':{'seed':93000,'draws':5000,'unit':'family-stratified graph group and environment root within selected graph','scope':'Conditional descriptive intervals for selected structural holdout; undefined CDI cells excluded and counts reported'},'networks':{},'interactions':{},'source_hashes':{'holdout_metrics':sha(OUT/'holdout/metrics.jsonl'),'protocol':sha(OUT/'protocol.json')}}
    audit_arrays={}
    for net in ['independent','shared']:
        result['networks'][net]={}
        for rule in ['strict','skip-unready']:
            out={'methods':{},'contrasts':{}}
            for method in METHOD_NAMES:
                rr=[r for r in data if (r['network'],r['rule'],r['method'])==(net,rule,method)]
                st={metric:estimate(array(net,rule,method,metric)) for metric in ['cdi','awct','signed','absolute']}
                st['cases']=len(rr);st['undefined_CDI_cases']=sum(r['cdi'] is None for r in rr)
                st['positive_CDI_cases']=sum(r['cdi'] is not None and r['cdi']>1e-8 for r in rr)
                st['max_protected_positive_shift']=max((r['max_positive'] or 0.) for r in rr)
                for ref in ['PoolMinAWCT10','DispatchMinAWCT']:
                    ratios=[t/index[r['case_id'],net,rule,ref]['workflow_completion'][g]-1 for r in rr for g,t in r['workflow_completion'].items()]
                    st['workflow_cost_vs_'+ref]={'observations':len(ratios),'fraction_above_5pct':float(np.mean(np.array(ratios)>.05+1e-10)),'count_above_5pct':int(np.sum(np.array(ratios)>.05+1e-10)),'p95':float(np.quantile(ratios,.95)),'p99':float(np.quantile(ratios,.99)),'maximum':max(ratios)}
                    st['paired_AWCT_vs_'+ref]=estimate(array(net,rule,method,'awct',ref,True))
                st['by_family']={f:{metric:float(np.nanmean(np.nanmean(array(net,rule,method,metric)[g],axis=1))) for metric in ['cdi','awct']} for f,g in zip(families,group)}
                out['methods'][method]=st
            for method,ref in [('B0AssignmentReorder','B0'),('BudgetSelect10','B0AssignmentReorder'),('ProtectedSubsequence','ProtectedFirst'),('DispatchMatchedGuard','WorkflowGuard'),('DispatchMatchedGuard','DispatchMinAWCT')]:
                key=method+'_minus_'+ref;out['contrasts'][key]={}
                for metric in ['cdi','signed','awct']:
                    a=array(net,rule,method,metric,ref,metric=='awct');out['contrasts'][key][metric]=estimate(a)
                    audit_arrays[net+'/'+rule+'/'+key+'/'+metric]=a.tolist()
            result['networks'][net][rule]=out
        for metric in ['cdi','signed']:
            a=array(net,'skip-unready','B0AssignmentReorder',metric,'B0')-array(net,'strict','B0AssignmentReorder',metric,'B0')
            result['interactions'][net+'/'+metric]=estimate(a);audit_arrays[net+'/interaction/'+metric]=a.tolist()
    # Complete graph-level outputs, including zero/undefined and adverse outcomes.
    result['by_graph']={g:{net:{rule:{method:{metric:float(np.nanmean(array(net,rule,method,metric)[i])) for metric in ['cdi','awct','signed']} for method in METHOD_NAMES} for rule in ['strict','skip-unready']} for net in ['independent','shared']} for i,g in enumerate(graphs)}
    measured=rows(OUT/'measured/evaluation/metrics.jsonl');assert len(measured)==528
    result['calibration']=read(OUT/'measured/calibration.json');result['measured']={};mi={(r['case_id'],r['rule'],r['method']):r for r in measured}
    for repeat in [4,5]:
        result['measured'][str(repeat)]={}
        for rule in ['strict','skip-unready']:
            result['measured'][str(repeat)][rule]={}
            for method in (*METHOD_NAMES,'CalibratedGuard'):
                rr=[r for r in measured if (r['repeat'],r['rule'],r['method'])==(repeat,rule,method)]
                costs=[t/mi[r['case_id'],rule,'DispatchMinAWCT']['workflow_completion'][g]-1 for r in rr for g,t in r['workflow_completion'].items()]
                result['measured'][str(repeat)][rule][method]={'cases':len(rr),'cdi':float(np.nanmean([r['cdi'] if r['cdi'] is not None else np.nan for r in rr])),'undefined_CDI_cases':sum(r['cdi'] is None for r in rr),'awct':float(np.mean([r['awct'] for r in rr])),'paired_AWCT_vs_DispatchMinAWCT':float(np.mean([r['awct']/mi[r['case_id'],rule,'DispatchMinAWCT']['awct']-1 for r in rr])),'workflow_observations':len(costs),'workflow_violations_above_5pct':int(np.sum(np.array(costs)>.05+1e-10)),'worst_workflow_inflation':max(costs),'nonreference_choices':sum(r['workflow_completion']!=mi[r['case_id'],rule,'DispatchMinAWCT']['workflow_completion'] for r in rr),'calibrated_reference_fallbacks':sum(bool(r.get('guard_metadata',{}).get('calibrated_reference_fallback')) for r in rr if r.get('guard_metadata')) if method=='CalibratedGuard' else None}
    result['source_hashes']['measured_evaluation']=sha(OUT/'measured/evaluation/metrics.jsonl')
    dump(OUT/'analysis/results.json',native(result));dump(OUT/'analysis/contrast_arrays.json',native({'graph_order':graphs,'family_indices':group,'arrays':audit_arrays}))
    print('R6 all holdout/observed analyses complete')

import math
if __name__=='__main__':main()
