"""Separate numerical recomputation; does not import the analysis or simulation code."""
import gzip,hashlib,json,math
from collections import defaultdict
from pathlib import Path
from statistics import mean
import numpy as np

ROOT=Path(__file__).resolve().parents[1];BASE=ROOT/'revision_r6'
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def rows(p):return [json.loads(x) for x in p.read_text().splitlines()]
def close(a,b):
    if a is None or b is None:assert a==b;return 0.
    assert math.isclose(a,b,rel_tol=1e-11,abs_tol=1e-11),(a,b)
    return abs(a-b)
def quantile(values,p):
    s=sorted(values);f=(len(s)-1)*p;lo=math.floor(f);hi=math.ceil(f)
    return s[lo]+(s[hi]-s[lo])*(f-lo)
def main():
    result=read(BASE/'analysis/results.json');arrays=read(BASE/'analysis/contrast_arrays.json')
    data=rows(BASE/'holdout/metrics.jsonl');assert len(data)==4800
    index={(r['case_id'],r['network'],r['rule'],r['method']):r for r in data}
    cases=defaultdict(list)
    for r in data:cases[r['graph_id'],r['root'],r['network'],r['rule'],r['method']].append(r)
    graphs=arrays['graph_order'];groups=arrays['family_indices'];keys=list(arrays['arrays'])
    maximum=0.;rebuilt=[]
    def pair(graph,root,net,rule,method,reference,metric):
        values=[]
        for r in cases[graph,root,net,rule,method]:
            b=index[r['case_id'],net,rule,reference][metric];a=r[metric]
            if a is not None and b is not None:values.append(a/b-1 if metric=='awct' else a-b)
        return mean(values) if values else None
    for key in keys:
        parts=key.split('/');net=parts[0];a=[]
        for g in graphs:
            row=[]
            for root in range(91000,91004):
                if parts[1]=='interaction':
                    v=pair(g,root,net,'skip-unready','B0AssignmentReorder','B0',parts[2])-pair(g,root,net,'strict','B0AssignmentReorder','B0',parts[2])
                else:
                    method,reference=parts[2].split('_minus_');v=pair(g,root,net,parts[1],method,reference,parts[3])
                row.append(v)
            a.append(row)
        for x,y in zip(sum(a,[]),sum(arrays['arrays'][key],[])):maximum=max(maximum,close(x,y))
        rebuilt.append(a)
    matrix=np.asarray(rebuilt);assert np.all(np.isfinite(matrix))
    # Explicit family -> graph -> root means; frozen draws shared across contrasts.
    draws=np.load(BASE/'analysis/resamples.npz');gi=draws['graph_indices'];ri=draws['root_indices'];samples=[]
    for draw in range(5000):
        families=[]
        for f in range(4):
            selected=[]
            for j in range(3):
                selected.append(sum(matrix[:,gi[f,draw,j],int(root)] for root in ri[f,draw,j])/4)
            families.append(sum(selected)/3)
        samples.append(sum(families)/4)
    samples=np.array(samples);checks=0
    for j,key in enumerate(keys):
        parts=key.split('/');expected=result['interactions'][parts[0]+'/'+parts[2]] if parts[1]=='interaction' else result['networks'][parts[0]][parts[1]]['contrasts'][parts[2]][parts[3]]
        point=mean(mean(mean(matrix[j,g]) for g in group) for group in groups)
        values=[point,quantile(samples[:,j],.025),quantile(samples[:,j],.975)]
        for x,y in zip(values,[expected['point'],*expected['ci95']]):maximum=max(maximum,close(x,y));checks+=1
    # Independently reconstruct all method means and completion-threshold counts.
    method_fields=0
    for net,byrule in result['networks'].items():
        for rule,out in byrule.items():
            for method,s in out['methods'].items():
                rr=[r for r in data if (r['network'],r['rule'],r['method'])==(net,rule,method)]
                for metric in ['cdi','awct','signed','absolute']:
                    gm=[]
                    for group in groups:
                        graphmean=[]
                        for i in group:
                            rootmeans=[]
                            for root in range(91000,91004):
                                v=[r[metric] for r in cases[graphs[i],root,net,rule,method] if r[metric] is not None]
                                if v:rootmeans.append(mean(v))
                            if rootmeans:graphmean.append(mean(rootmeans))
                        gm.append(mean(graphmean))
                    maximum=max(maximum,close(mean(gm),s[metric]['point']));method_fields+=1
                for ref in ['PoolMinAWCT10','DispatchMinAWCT']:
                    ratios=[t/index[r['case_id'],net,rule,ref]['workflow_completion'][g]-1 for r in rr for g,t in r['workflow_completion'].items()]
                    observed=sum(x>.05+1e-10 for x in ratios);expected=s['workflow_cost_vs_'+ref]
                    assert observed==expected['count_above_5pct'];maximum=max(maximum,close(max(ratios),expected['maximum']));method_fields+=2
    ledger=read(BASE/'compact/manifest.json');eta={'strict':0.,'skip-unready':0.};errors=0;plan_checks=0
    full_guards=defaultdict(lambda:{'cases':0,'selected_nonreference':0,'mean_quality_fallback':0,'workflow_violations':0,'max_forecast_abs_error':0.})
    for entry in ledger['entries']:
        p=ROOT/entry['compact_path'];assert sha(p)==entry['compact_sha256']
        d=json.loads(gzip.decompress(p.read_bytes()))
        for c in d.get('calibration_candidates',[]):
            for g,t in c['realized'].items():
                error=abs(c['predicted'][g]/t-1);maximum=max(maximum,close(error,c['relative_prediction_errors'][g]));eta[c['rule']]=max(eta[c['rule']],error);errors+=1
        for model,m in d['metadata'].items():
            key=entry['stage']+'/'+model;s=full_guards[key];s['cases']+=1;s['selected_nonreference']+=int(m['nonreference_selected']);s['mean_quality_fallback']+=int(m['mean_quality_fallback'])
            ref=d['runs'][model+'/DispatchMinAWCT']['clock'];guard=d['runs'][model+'/DispatchMatchedGuard']['clock']
            assert (ref['applied_plan']!=guard['applied_plan'])==m['nonreference_selected'];plan_checks+=1
            actual=dict(ref['workflow_finishes']);realized=dict(guard['workflow_finishes'])
            s['workflow_violations']+=sum(t/actual[g]>.05+1+1e-10 for g,t in realized.items())
            for name in ['DispatchMinAWCT','DispatchMatchedGuard']:
                completed=dict(d['runs'][model+'/'+name]['clock']['workflow_finishes']);pred=d['predictions'][model][name]['workflow_completion']
                s['max_forecast_abs_error']=max(s['max_forecast_abs_error'],max(abs(t-completed[g]) for g,t in pred.items()))
            if entry['stage']=='holdout':
                assert s['workflow_violations']==0 and s['max_forecast_abs_error']<1e-8
            if entry['stage']=='measured/evaluation':
                cg=d['runs'][model+'/CalibratedGuard']['clock'];fallback=m['calibrated_reference_fallback']
                if fallback:assert cg['applied_plan']==ref['applied_plan']
                s['calibrated_reference_fallbacks']=s.get('calibrated_reference_fallbacks',0)+int(fallback)
    for rule,v in eta.items():maximum=max(maximum,close(v,result['calibration']['eta'][rule]))
    observed=rows(BASE/'measured/evaluation/metrics.jsonl');ix={(r['case_id'],r['rule'],r['method']):r for r in observed};observed_fields=0
    for repeat,ruledata in result['measured'].items():
        for rule,methods in ruledata.items():
            for method,s in methods.items():
                rr=[r for r in observed if r['repeat']==int(repeat) and r['rule']==rule and r['method']==method]
                maximum=max(maximum,close(mean(r['awct'] for r in rr),s['awct']))
                maximum=max(maximum,close(mean(r['cdi'] for r in rr if r['cdi'] is not None),s['cdi']))
                ratios=[t/ix[r['case_id'],rule,'DispatchMinAWCT']['workflow_completion'][g]-1 for r in rr for g,t in r['workflow_completion'].items()]
                assert sum(x>.05+1e-10 for x in ratios)==s['workflow_violations_above_5pct']
                maximum=max(maximum,close(max(ratios),s['worst_workflow_inflation']));observed_fields+=4
    out={'status':'PASS','independence':'separate calculation code in the same research project, not an external team','contrast_arrays':len(keys),'contrast_cells':int(matrix.size),'contrast_points_and_interval_endpoints':checks,'method_mean_and_tail_fields':method_fields,'observed_summary_fields':observed_fields,'calibration_candidate_workflow_error_checks':errors,'calibration_eta_recomputed':eta,'applied_guard_plan_checks':plan_checks,'maximum_numerical_difference':maximum,'guard_diagnostics':dict(full_guards),'source_sha256':{str(p.relative_to(ROOT)):sha(p) for p in [BASE/'analysis/results.json',BASE/'analysis/contrast_arrays.json',BASE/'analysis/resamples.npz',BASE/'compact/manifest.json']}}
    (BASE/'reports/independent_recomputation.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out))
if __name__=='__main__':main()
