"""Descriptive paired results; environment counts are not source-repeat counts."""
import csv
import math
import json
from collections import defaultdict
from statistics import mean
from revision_r7.common import ROOT,OUT,read,dump,sha
from revision_r7.portable_io import read_document


def summarize(rows):
    workflow=[x for r in rows for x in r['workflow_change_pct'].values()]
    def average(name):
        values=[r[name] for r in rows if r[name] is not None]
        return mean(values) if values else None
    result={'cases':len(rows),'defined_cdi_cases':sum(r['cdi'] is not None for r in rows),'mean_cdi':average('cdi'),'mean_delta_cdi':average('delta_cdi'),'mean_delta_signed':average('delta_signed'),'mean_awct_change_pct':average('awct_change_pct'),'nonreference_count':sum(r['nonreference'] for r in rows),'workflow_count':len(workflow),'workflow_violations':sum(x>5+1e-8 for x in workflow),'case_violations':sum(max(r['workflow_change_pct'].values())>5+1e-8 for r in rows),'max_workflow_change_pct':max(workflow),'min_workflow_change_pct':min(workflow),'zero_failed_pending_cases':sum(r['F']==0 for r in rows),'single_candidate_cases':sum(r['pool_size']==1 for r in rows),'mean_pool_size':average('pool_size')}
    result['reference_fallbacks']=sum(r['reference_fallback'] for r in rows) if rows[0]['reference_fallback'] is not None else None
    result['selected_envelope_workflow_checks']=sum(len(r['selected_envelope_misses']) for r in rows)
    result['selected_envelope_workflow_misses']=sum(sum(r['selected_envelope_misses'].values()) for r in rows)
    return result


def main():
    margins=read(OUT/'calibration/margins.json');registration=read(OUT/'evaluation_registration.json')
    assert sha(OUT/'calibration/margins.json')==registration['margins_sha256']
    for stage in ['calibration','evaluation']:
        receipt=read(OUT/stage/'receipt.json');assert receipt['status']=='PASS'
        assert sha(OUT/stage/'metrics.jsonl')==receipt['metrics_sha256']
    records=[];candidate_errors=[];case_profiles=[]
    for stage in ['calibration','evaluation']:
        for path in sorted((OUT/stage/'cases').glob('*.json')):
            saved=read(path)
            d=read_document(saved);mix=d['composition'];repeat=d['repeat'];root=d['root']
            for sample in saved['candidate_samples']:
                z=math.log(sample['realized']/sample['reference_realized'])-math.log(sample['predicted']/sample['reference_predicted'])
                env=margins['cells'][mix][sample['condition']]
                group=env['conditional'].get(sample['candidate']+'|'+sample['workflow'])
                candidate_errors.append({'stage':stage,'composition':mix,'repeat':repeat,**sample,'candidate_log_error':math.log(sample['realized']/sample['predicted']),'reference_log_error':math.log(sample['reference_realized']/sample['reference_predicted']),'ratio_log_error':z,'global_margin':env['global_delta'],'conditional_margin':group['delta'] if group and group['distinct_roots']>=3 else None,'global_covered':z<=env['global_delta']+1e-10,'conditional_covered':z<=group['delta']+1e-10 if group and group['distinct_roots']>=3 else None})
            if stage!='evaluation':continue
            bykey={r['network']+'/'+r['rule']+'/'+r['method']:r for r in saved['rows']}
            for condition in d['metadata']:
                net,rule=condition.split('/');ref=bykey[condition+'/DispatchMinAWCT'];ref_plan=d['runs'][condition+'/DispatchMinAWCT']['clock']['applied_plan'];info=d['metadata'][condition]
                case_profiles.append({'case_id':saved['case_id'],'composition':mix,'repeat':repeat,'root':root,'network':net,'rule':rule,'F':ref['F'],'Q':ref['Q'],'P':ref['P'],'pool_size':info['pool_size'],'mean_quality_fallback':info['mean_quality_fallback']})
                for method in sorted(k.split('/')[-1] for k in d['runs'] if k.startswith(condition+'/')):
                    r=bykey[condition+'/'+method];run=d['runs'][condition+'/'+method]['clock']
                    changes={g:100*(t/ref['workflow_completion'][g]-1) for g,t in r['workflow_completion'].items()}
                    fallback=None;misses={}
                    if method=='CalibratedGuard':fallback=info['calibrated_reference_fallback']
                    if method in ['PairedRatioGuard','ConditionalRatioGuard']:
                        policy=info['paired_guards'][method];fallback=policy['reference_fallback']
                        if not fallback:
                            selected=next(x for x in d['pool_forecasts'][condition] if x['name']==policy['selected_name'])
                            ref_fc=d['predictions'][condition]['DispatchMinAWCT']['workflow_completion'];env=margins['cells'][mix][condition]
                            for g,t in r['workflow_completion'].items():
                                z=math.log(t/ref['workflow_completion'][g])-math.log(selected['workflow_completion'][g]/ref_fc[g])
                                delta=env['global_delta'] if method=='PairedRatioGuard' else env['conditional'][selected['name']+'|'+g]['delta']
                                misses[g]=z>delta+1e-10
                    records.append({'case_id':saved['case_id'],'composition':mix,'repeat':repeat,'root':root,'network':net,'rule':rule,'method':method,'cdi':r['cdi'],'signed':r['signed'],'awct':r['awct'],'delta_cdi':r['cdi']-ref['cdi'] if r['cdi'] is not None and ref['cdi'] is not None else None,'delta_signed':r['signed']-ref['signed'] if r['signed'] is not None and ref['signed'] is not None else None,'awct_change_pct':100*(r['awct']/ref['awct']-1),'workflow_completion':r['workflow_completion'],'workflow_change_pct':changes,'nonreference':run['applied_plan']!=ref_plan,'reference_fallback':fallback,'selected_envelope_misses':misses,'F':r['F'],'Q':r['Q'],'P':r['P'],'pool_size':info['pool_size']})
    assert len(records)==3744
    summaries={}
    for level,keys in [('by_repeat',['composition','repeat','network','rule','method']),('by_condition',['composition','network','rule','method']),('by_mix_network',['composition','network','method']),('by_method',['method'])]:
        groups=defaultdict(list)
        for r in records:groups['/'.join(str(r[k]) for k in keys)].append(r)
        summaries[level]={key:summarize(rows) for key,rows in sorted(groups.items())}
    out=OUT/'analysis';out.mkdir(exist_ok=True)
    dump(out/'case_values.json',records);dump(out/'candidate_errors.json',candidate_errors);dump(out/'case_profiles.json',case_profiles)
    with (out/'all_method_results.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=['composition','repeat','network','rule','method',*next(iter(summaries['by_repeat'].values())).keys()]);writer.writeheader()
        for key,s in summaries['by_repeat'].items():writer.writerow(dict(zip(['composition','repeat','network','rule','method'],key.split('/')),**s))
    with (out/'workflow_values.csv').open('w',newline='') as f:
        fields=['case_id','composition','repeat','root','network','rule','method','workflow','completion','change_vs_DPM_pct','nonreference'];writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader()
        for r in records:
            for g,t in r['workflow_completion'].items():writer.writerow({**{k:r[k] for k in fields if k in r},'workflow':g,'completion':t,'change_vs_DPM_pct':r['workflow_change_pct'][g]})
    totals={k:read(OUT/k/'receipt.json') for k in ['calibration','evaluation']}
    result={'status':'PASS','scope':'Descriptive paired outcomes conditional on three compositions and two evaluation runtime vectors each; no pseudo-replicated confidence intervals','summaries':summaries,'calibration_cells':margins['cells'],'execution_receipts':totals,'source_sha256':{str(p.relative_to(ROOT)):sha(p) for p in [OUT/'protocol.json',OUT/'data/manifest.json',OUT/'calibration/margins.json',OUT/'evaluation/metrics.jsonl']},'original_protocol_changed':False,'new_confirmatory_samples':0}
    dump(out/'results.json',result)
    print(json.dumps({'status':'PASS','evaluation_rows':len(records),'candidate_error_observations':len(candidate_errors),'by_method':{k:v for k,v in summaries['by_method'].items() if k in ['DispatchMinAWCT','DispatchMatchedGuard','CalibratedGuard','PairedRatioGuard','ConditionalRatioGuard']}}))


if __name__=='__main__':main()
