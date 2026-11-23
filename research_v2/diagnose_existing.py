"""Post-outcome decomposition using only the immutable v1 outputs."""
import csv
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from sail.development import dump
from sail.frozen import verify_freeze


def write_csv(path,rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)


def main():
    verify_freeze(ROOT,ROOT/'freeze/g2_v1_20261025');out=ROOT/'results/g2_v1_20261025';folder=ROOT/'research_v2/reports'
    raw=[json.loads(x) for x in (out/'metrics.jsonl').read_text().splitlines()]
    cases=defaultdict(dict)
    for r in raw:
        if r.get('variant')=='main':cases[r['scenario_id']][r['method']]=r
    rows=[]
    for sid,m in sorted(cases.items()):
        a,b=m['SAIL'],m['B2'];local=[m[k] for k in ('B0','Fixed_H1','Fixed_H2')]
        oracle=min(local,key=lambda x:(x['cdi'],x['awct'],x['churn'],x['method']))
        scope_gap=oracle['cdi']-b['cdi'];choice_gap=a['cdi']-oracle['cdi'];total=a['cdi']-b['cdi']
        assert choice_gap>=-1e-10 and math.isclose(scope_gap+choice_gap,total,abs_tol=1e-12)
        ar=json.loads((out/a['event_file']).read_text());br=json.loads((out/b['event_file']).read_text())
        ctx=ar['context'];P=set(ctx['P']);old=dict(ctx['old_assignment'])
        new={v:j for j,q in enumerate(br['applied_plan']['queues']) for v in q}
        sa=dict(ar['starts']);sb=dict(br['starts']);pb=sum(t['work'] for t in json.loads((ROOT/f"freeze/g2_v1_20261025/public/workloads/{a['root_seed']}-{a['mix']}.json").read_text())['tasks'])/len(ar['starts'])
        # Recover the paired no-fault reference through its stable job identity.
        ref=next(x for x in raw if x['job_id']=='ref-'+a['base_id'])
        sr=dict(json.loads((out/ref['event_file']).read_text())['starts'])
        moved={v for v in P if new[v]!=old[v]}
        def contribution(group):return sum(max(0,sa[v]-sr[v])-max(0,sb[v]-sr[v]) for v in group)/len(P)/pb
        cm,cu=contribution(moved),contribution(P-moved)
        assert math.isclose(cm+cu,total,abs_tol=1e-9)
        rows.append({'scenario_id':sid,**{k:a[k] for k in ('root_seed','mix','nodes','ccr','failure_fraction')},
                     'SAIL_CDI':a['cdi'],'B2_CDI':b['cdi'],'best_H012_CDI':oracle['cdi'],'best_H012_method':oracle['method'],
                     'candidate_set_gap':scope_gap,'selection_gap':choice_gap,'total_CDI_gap':total,
                     'B2_moved_P_count':len(moved),'P_count':len(P),'moved_P_contribution':cm,'unmoved_P_contribution':cu,
                     'SAIL_churn':a['churn'],'B2_churn':b['churn']})
    summary={}
    for mix in ('all','A','B','C'):
        g=[r for r in rows if mix=='all' or r['mix']==mix]
        summary[mix]={'n':len(g),**{k:statistics.mean(r[k] for r in g) for k in ('candidate_set_gap','selection_gap','total_CDI_gap','moved_P_contribution','unmoved_P_contribution')},
                      'best_H012_worse_than_B2':sum(r['candidate_set_gap']>1e-12 for r in g),
                      'best_H012_better_than_B2':sum(r['candidate_set_gap']<-1e-12 for r in g)}
    dump(folder/'existing_diagnosis.json',{'purpose':'EXPLORATORY_POST_G3','uses_actual_outcome_oracle':True,'summary':summary,
         'definition':'SAIL-B2 = (minimum actual CDI among H0/H1/H2 - B2) + (SAIL - that minimum). This oracle is an outcome envelope, not a newly validated policy.',
         'partition_note':'Moved/unmoved P partition describes observed task contributions, not a causal mediation estimate.',
         'all_main_scenarios_retained':720,'new_independent_observations':0})
    write_csv(folder/'existing_diagnosis.csv',rows)
    print(json.dumps(summary,ensure_ascii=False))


if __name__=='__main__':main()
