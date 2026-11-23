"""Separate arithmetic reconstruction from event archives, without analyzer/selector imports."""
import gzip,hashlib,json,math
from pathlib import Path
from collections import defaultdict

R=Path(__file__).resolve().parents[1];B=R/'revision_r7'
def read(p):
    p=Path(p);return json.loads(gzip.decompress(p.read_bytes()) if p.suffix=='.gz' else p.read_bytes())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read_document(case):
    p=R/case['event_file']
    if p.exists():
        assert sha(p)==case['event_sha256'];return read(p)
    catalog=read(B/'portable/manifest.json')
    entry=next(x for x in catalog['entries'] if x['source_event_file']==case['event_file'])
    assert entry['source_event_sha256']==case['event_sha256']
    assert sha(R/entry['case_file'])==entry['case_sha256']
    assert sha(R/entry['compact_file'])==entry['compact_sha256']
    return read(R/entry['compact_file'])
def avg(x):return math.fsum(x)/len(x) if x else None


def main():
    result=read(B/'analysis/results.json');cal=read(B/'calibration/margins.json')['cells'];expected_rows=read(B/'analysis/case_values.json')
    expected={(r['case_id'],r['network'],r['rule'],r['method']):r for r in expected_rows}
    deltas=[];checks=0
    def compare(a,b):
        nonlocal checks
        checks+=1
        if a is None or b is None:assert a is b;return
        diff=abs(a-b);deltas.append(diff);assert math.isclose(a,b,rel_tol=1e-11,abs_tol=1e-10),(a,b)
    samples=defaultdict(list);rows=[];invariant=0;nonimproving=defaultdict(int);worst=None
    for stage in ['calibration','evaluation']:
        for path in sorted((B/stage/'cases').glob('*.json')):
            case=read(path);doc=read_document(case)
            mean_work=avg([t['work'] for t in doc['workload']['tasks']])
            for condition,meta in doc['metadata'].items():
                net,rule=condition.split('/');ref=doc['runs'][condition+'/DispatchMinAWCT']['clock'];refw=dict(ref['workflow_finishes'])
                pool={c['name']:c for c in doc['pool_forecasts'][condition]};rpred=pool[meta['reference_name']]
                continuations={c['candidate']:c for c in doc['candidate_continuations'] if c['condition']==condition}
                rc=continuations[meta['reference_name']]
                assert all(abs(rc['realized'][g]-refw[g])<1e-8 for g in refw)
                for name,c in continuations.items():
                    wf=dict(c['continuation']['workflow_finishes'])
                    for g in wf:
                        compare(wf[g],c['realized'][g]);compare(pool[name]['workflow_completion'][g],c['predicted'][g])
                        if stage=='calibration':samples[(doc['composition'],condition)].append((name,g,doc['root'],abs(c['predicted'][g]/wf[g]-1),math.log(wf[g]*rc['predicted'][g]/(c['predicted'][g]*rc['realized'][g]))))
                if stage!='evaluation':continue
                starts0=dict(doc['references'][condition]['clock']['starts']);rp=ref['context']['P'];rs=dict(ref['starts'])
                refcdi=avg([max(0.,rs[v]-starts0[v])/mean_work for v in rp]);refsigned=avg([(rs[v]-starts0[v])/mean_work for v in rp])
                for key,value in doc['runs'].items():
                    if not key.startswith(condition+'/'):continue
                    method=key.split('/')[-1];v=value['clock'];ss=dict(v['starts']);wf=dict(v['workflow_finishes']);p=v['context']['P']
                    assert p==rp
                    cdi=avg([max(0.,ss[x]-starts0[x])/mean_work for x in p]);signed=avg([(ss[x]-starts0[x])/mean_work for x in p]);awct=avg(list(wf.values()))
                    changes={g:100*(wf[g]/refw[g]-1) for g in wf};nonref=v['applied_plan']!=ref['applied_plan']
                    row={'composition':doc['composition'],'repeat':doc['repeat'],'network':net,'rule':rule,'method':method,'cases':1,'cdi':cdi,'delta_cdi':cdi-refcdi if p else None,'delta_signed':signed-refsigned if p else None,'awct_change_pct':100*(awct/avg(list(refw.values()))-1),'nonreference':nonref,'workflow_change_pct':changes,'F':len(v['context']['F']),'pool_size':len(pool),'reference_fallback':None,'selected_envelope_misses':{}}
                    if method=='CalibratedGuard':row['reference_fallback']=meta['calibrated_reference_fallback']
                    if method in ['PairedRatioGuard','ConditionalRatioGuard']:
                        m=meta['paired_guards'][method];row['reference_fallback']=m['reference_fallback'];assert nonref != m['reference_fallback']
                        admissible=[x for x in m['candidate_admission'] if x['admitted']]
                        calculated=[]
                        for decision in m['candidate_admission']:
                            c=pool[decision['name']];bounds={};covered=True;e=cal[doc['composition']][condition]
                            for g,t in c['workflow_completion'].items():
                                group=e['conditional'].get(c['name']+'|'+g)
                                if method=='ConditionalRatioGuard' and (group is None or group['distinct_roots']<3):covered=False;break
                                delta=e['global_delta'] if method=='PairedRatioGuard' else group['delta']
                                bounds[g]=math.log(t/rpred['workflow_completion'][g])+delta
                            passes=covered and all(x<=math.log(1.05)+1e-12 for x in bounds.values())
                            assert decision['covered']==covered and decision['admitted']==passes
                            for g,x in bounds.items():compare(x,decision['log_ratio_upper'][g])
                            if passes:calculated.append(c)
                        if calculated:
                            chosen=min(calculated,key=lambda c:(c['cdi'],c['awct'],c['churn'],c['name'],tuple(tuple(q) for q in c['plan']['queues'])))
                            assert chosen['plan']==v['applied_plan']
                            if chosen['cdi']>=rpred['cdi']-1e-12:nonimproving[method]+=1
                            for g,t in wf.items():
                                z=math.log(t*rpred['workflow_completion'][g]/(refw[g]*chosen['workflow_completion'][g]));e=cal[doc['composition']][condition]
                                delta=e['global_delta'] if method=='PairedRatioGuard' else e['conditional'][chosen['name']+'|'+g]['delta']
                                row['selected_envelope_misses'][g]=z>delta+1e-10
                        else:assert v['applied_plan']==ref['applied_plan']
                        invariant+=1
                    target=expected[(case['case_id'],net,rule,method)]
                    for field in ['cdi','delta_cdi','delta_signed','awct_change_pct']:compare(row[field],target[field])
                    assert nonref==target['nonreference'] and row['selected_envelope_misses']==target['selected_envelope_misses']
                    for g,t in changes.items():compare(t,target['workflow_change_pct'][g])
                    rows.append(row)
                    if method=='ConditionalRatioGuard':
                        g=max(changes,key=changes.get)
                        item={'case_id':case['case_id'],'composition':doc['composition'],'repeat':doc['repeat'],'root':doc['root'],'network':net,'rule':rule,'method':method,'workflow':g,'increase_pct':changes[g],'source_event_file':case['event_file'],'source_event_sha256':case['event_sha256']}
                        if worst is None or item['increase_pct']>worst['increase_pct']:worst=item
    for (mix,condition),values in samples.items():
        e=cal[mix][condition];compare(max(v[3] for v in values),e['eta']);compare(max(0.,max(v[4] for v in values)),e['global_delta'])
        assert len(values)==e['observations'];groups=defaultdict(list)
        for name,g,root,eta,z in values:groups[name+'|'+g].append((root,z))
        assert set(groups)==set(e['conditional'])
        for name,v in groups.items():
            compare(max(0.,max(z for root,z in v)),e['conditional'][name]['delta']);assert len({root for root,z in v})==e['conditional'][name]['distinct_roots']
    for level,keys in [('by_repeat',['composition','repeat','network','rule','method']),('by_condition',['composition','network','rule','method']),('by_mix_network',['composition','network','method']),('by_method',['method'])]:
        groups=defaultdict(list)
        for r in rows:groups['/'.join(str(r[k]) for k in keys)].append(r)
        assert set(groups)==set(result['summaries'][level])
        for key,group in groups.items():
            truth=result['summaries'][level][key];wf=[x for r in group for x in r['workflow_change_pct'].values()]
            x={'cases':len(group),'defined_cdi_cases':sum(r['cdi'] is not None for r in group),'mean_cdi':avg([r['cdi'] for r in group if r['cdi'] is not None]),'mean_delta_cdi':avg([r['delta_cdi'] for r in group if r['delta_cdi'] is not None]),'mean_delta_signed':avg([r['delta_signed'] for r in group if r['delta_signed'] is not None]),'mean_awct_change_pct':avg([r['awct_change_pct'] for r in group]),'nonreference_count':sum(r['nonreference'] for r in group),'workflow_count':len(wf),'workflow_violations':sum(t>5+1e-8 for t in wf),'case_violations':sum(max(r['workflow_change_pct'].values())>5+1e-8 for r in group),'max_workflow_change_pct':max(wf),'min_workflow_change_pct':min(wf),'zero_failed_pending_cases':sum(r['F']==0 for r in group),'single_candidate_cases':sum(r['pool_size']==1 for r in group),'mean_pool_size':avg([r['pool_size'] for r in group]),'reference_fallbacks':sum(r['reference_fallback'] for r in group) if group[0]['reference_fallback'] is not None else None,'selected_envelope_workflow_checks':sum(len(r['selected_envelope_misses']) for r in group),'selected_envelope_workflow_misses':sum(sum(r['selected_envelope_misses'].values()) for r in group)}
            assert set(x)==set(truth)
            for name,t in x.items():compare(t,truth[name])
    output={'status':'PASS','implementation':'separate standard-library arithmetic from event archives; no analyzer or selector imports','numeric_checks':checks,'selector_admission_checks':invariant,'maximum_difference':max(deltas),'calibration_cells':len(samples),'evaluation_repairs_reconstructed':len(rows),'analysis_sha256':sha(B/'analysis/results.json'),'margins_sha256':sha(B/'calibration/margins.json')}
    (B/'reports/independent_recomputation.json').write_text(json.dumps(output,indent=2)+'\n')
    diagnostic={'classification':'POST_ANALYSIS_DIAGNOSTIC_WITH_NO_METHOD_OR_THRESHOLD_CHANGE','worst_conditioned_guard_case':worst,'nonreference_choices_without_predicted_CDI_improvement':dict(nonimproving),'interpretation':'The frozen ratio policies prioritize admitted nonreference candidates and use DPM as fallback. Admission and temporal benefit are distinct; these choices do not have the DMG same-pool CDI-direction guarantee. All selected outcomes remain in the full comparison.'}
    (B/'reports/post_analysis_diagnostics.json').write_text(json.dumps(diagnostic,indent=2)+'\n')
    print(json.dumps(output));print(json.dumps(diagnostic))


if __name__=='__main__':main()
