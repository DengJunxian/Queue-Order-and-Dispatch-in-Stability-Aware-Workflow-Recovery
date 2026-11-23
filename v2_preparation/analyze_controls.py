"""Same-pool contrasts and order metrics on every retained historical label."""
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from research_v2.diagnose_existing import write_csv
from sail.development import dump
from sail.frozen import result_from_json
from sail.statistics import paired_bootstrap
from v2_preparation.metrics import queue_disturbance


def main():
    folder=ROOT/'v2_preparation';assert json.loads((folder/'ablation/execution_summary.json').read_text())['all_complete']
    new=[json.loads(x) for x in (folder/'ablation/metrics.jsonl').read_text().splitlines()]
    selected=[json.loads(x) for x in (ROOT/'research_v2/pilot/metrics.jsonl').read_text().splitlines()]
    selected=[r for r in selected if r['method']=='BudgetSelect10']
    effects={};effectrows=[]
    for variant in ('main','cv0.1','cv0.3','control_delay'):
        a=[{**r,'method':'SAIL','variant':'main'} for r in selected if r['variant']==variant]
        b=[{**r,'variant':'main'} for r in new if r['variant']==variant]
        result=paired_bootstrap(a+b,'PoolMinAWCT10',repetitions=5000,seed=73000);effects[variant]=result
        for metric in ('cdi','relative_awct'):
            v=result[metric];ci=v['ci95'];effectrows.append({'variant':variant,'contrast':'BudgetSelect10-PoolMinAWCT10','metric':metric,'point':v['point'],
                'CI95_low':ci[0] if ci else None,'CI95_high':ci[1] if ci else None,'upper95':v['upper95'],'roots':result['cluster_count'],'defined_pairs':v['defined_pairs'],'NA_pairs':v['undefined_pairs'],'purpose':'EXPLORATORY_ON_V1_DATA'})
    dump(folder/'reports/same_pool_statistics.json',{'purpose':'EXPLORATORY_ON_V1_DATA','effects':effects,'source_decisions_match':900,'new_independent_test_sets':0})
    write_csv(folder/'reports/same_pool_effects.csv',effectrows)
    metricrows=[]
    for location in ('results/g2_v1_20261025','research_v2/pilot','research_v2/order_pilot','v2_preparation/ablation'):
        root=ROOT/location
        for row in [json.loads(x) for x in (root/'metrics.jsonl').read_text().splitlines()]:
            if row.get('kind')=='reference':continue
            result=result_from_json(json.loads((root/row['event_file']).read_text()))
            metricrows.append({'scenario_id':row['scenario_id'],'method':row['method'],'variant':row['variant'],
                'root_seed':row['root_seed'],'mix':row['mix'],**queue_disturbance(result.context,result.applied_plan),
                'Churn':row['churn'],'status':row['status'],'source':location})
    assert len(metricrows)==10980
    groups=defaultdict(list)
    for r in metricrows:groups[r['variant'],r['method']].append(r)
    summary=[]
    for (variant,method),rows in sorted(groups.items()):
        values=[r['order_disturbance'] for r in rows if r['order_disturbance'] is not None]
        summary.append({'variant':variant,'method':method,'label_rows':len(rows),'defined_scenarios':len(values),'NA_scenarios':len(rows)-len(values),
            'mean_order_disturbance':statistics.mean(values) if values else None,'total_inversions':sum(r['queue_inversions'] for r in rows),
            'total_comparable_pairs':sum(r['comparable_pairs'] for r in rows),'mean_Churn':statistics.mean(r['Churn'] for r in rows)})
    write_csv(folder/'reports/order_metrics.csv',metricrows);write_csv(folder/'reports/order_summary.csv',summary)
    dump(folder/'reports/order_metric_summary.json',{'label_rows':10980,'summary':summary,
         'definition':'per-scenario inverted-pair fraction among Q\\F tasks retained on their original healthy node; then mean defined scenarios',
         'interpretation':'Denominator changes when tasks move, so order disturbance must be read with retained-task counts, comparable-pair counts and Churn.',
         'alias_note':'NoChurn rows preserve original aliases; no independent observations added'})
    print(json.dumps({v:{k:r[k] for k in ('cdi','relative_awct')} for v,r in effects.items()}))


if __name__=='__main__':main()
