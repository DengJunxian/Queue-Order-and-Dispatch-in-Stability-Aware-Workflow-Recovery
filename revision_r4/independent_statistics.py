"""Independent balanced-design root-mean bootstrap, without the View helper."""
import json
import sys
from pathlib import Path
from collections import defaultdict

import numpy as np

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from revision_r4.common import OUT,read_rows,dump,BS,PM,Q0,AL


def independently_bootstrap(records,a,b,metric,draw_average=False):
    groups=defaultdict(dict)
    for r in records:
        if r['method']=='reference':continue
        key=(r['root_seed'],r['mix'],r['nodes'],r['ccr'],r['failure_fraction'],r.get('draw',0) if draw_average else 0)
        groups[key][r['method']]=r
    values=defaultdict(list)
    for key,runs in groups.items():
        if a not in runs or b not in runs:continue
        x=runs[a][metric]-runs[b][metric] if metric=='cdi' else runs[a]['awct']/runs[b]['awct']-1
        values[key[:-1]].append(x)
    roots=defaultdict(list)
    for cell,xx in values.items():
        assert len(xx)==(3 if draw_average else 1)
        roots[cell[0]].append(float(np.mean(xx)))
    ordered=sorted(roots);sizes={len(roots[k]) for k in ordered};assert len(sizes)==1
    # All three Mixes have the same cell count here, so root/cell means equal
    # the registered equal-cell, equal-Mix estimator. No missing groups occur.
    root_means=np.array([np.mean(roots[k]) for k in ordered])
    indices=np.random.Generator(np.random.PCG64(83000)).integers(0,len(ordered),(5000,len(ordered)))
    estimates=np.mean(root_means[indices],axis=1)
    return {'point':float(np.mean(root_means)),'ci95':np.quantile(estimates,[.025,.975]).tolist(),'upper95':float(np.quantile(estimates,.95))}


def main():
    expected=json.loads((OUT/'analysis/results.json').read_text());dispatch=read_rows(OUT/'exploratory/dispatch/metrics.jsonl')
    errors=read_rows(OUT/'analysis/original_error_extra.jsonl')+read_rows(OUT/'exploratory/error/metrics.jsonl')
    differences=[];comparisons=0
    def check(actual,want):
        nonlocal comparisons
        differences.append(abs(actual['point']-want['point']));differences.append(abs(actual['upper95']-want['upper95']))
        differences.extend(abs(x-y) for x,y in zip(actual['ci95'],want['ci95']));comparisons+=1
    for rule in ('strict','skip-unready'):
        rows=[r for r in dispatch if r['rule']==rule]
        for label,effect in expected['dispatch'][rule]['contrasts'].items():
            a,b=label.split('_minus_')
            check(independently_bootstrap(rows,a,b,'cdi'),effect['cdi'])
            check(independently_bootstrap(rows,a,b,'awct'),effect['relative_awct'])
    for variant in ('cv0.1','cv0.3'):
        rows=[r for r in errors if r['variant']==variant]
        for label,effect in expected['errors'][variant]['paired_effects_averaging_draws_within_root_cell'].items():
            a,b=label.split('_minus_')
            check(independently_bootstrap(rows,a,b,'cdi',True),effect['cdi'])
            check(independently_bootstrap(rows,a,b,'awct',True),effect['relative_awct'])
    assert max(differences)<1e-11
    dump(OUT/'reports/independent_statistics.json',{'status':'PASS','comparison_estimands':comparisons,'point_interval_upper_checks':len(differences),
        'max_abs_difference':max(differences),'independent_of_View':True,'bootstrap_draws':5000,'seed':83000,
        'scope':'Complete balanced main factorial and repeated-error paired effects; no missing-group or topology-population inference.'})
    print('Independent root-mean bootstrap PASS',comparisons,len(differences),max(differences))


if __name__=='__main__':main()
