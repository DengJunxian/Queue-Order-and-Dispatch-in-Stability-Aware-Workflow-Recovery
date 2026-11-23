"""All declared exploratory comparisons, retaining fallbacks and adverse results."""
import csv
import json
import statistics
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from research_v2.diagnose_existing import write_csv
from sail.development import dump
from sail.statistics import paired_bootstrap


def main():
    folder=ROOT/'research_v2';out=folder/'pilot';report=folder/'reports'
    execution=json.loads((out/'execution_summary.json').read_text());assert execution['all_complete']
    new=[json.loads(x) for x in (out/'metrics.jsonl').read_text().splitlines()]
    assert json.loads((folder/'order_pilot/execution_summary.json').read_text())['all_complete']
    new += [json.loads(x) for x in (folder/'order_pilot/metrics.jsonl').read_text().splitlines()]
    old=[json.loads(x) for x in (ROOT/'results/g2_v1_20261025/metrics.jsonl').read_text().splitlines()]
    old=[r for r in old if r['kind']=='failure']
    allrows=new+[{**r,'method':'LegacySAIL' if r['method']=='SAIL' else r['method']} for r in old]
    effects={};flat=[];summary=[]
    def compare(method,comparator,variant):
        a=[{**r,'method':'SAIL','variant':'main'} for r in allrows if r['method']==method and r['variant']==variant]
        b=[{**r,'variant':'main'} for r in allrows if r['method']==comparator and r['variant']==variant]
        s=paired_bootstrap(a+b,comparator,repetitions=5000,seed=73000)
        for metric in ('cdi','relative_awct'):
            v=s[metric];ci=v['ci95']
            flat.append({'variant':variant,'method':method,'comparator':comparator,'metric':metric,'point':v['point'],
                         'CI95_low':ci[0] if ci else None,'CI95_high':ci[1] if ci else None,'upper95':v['upper95'],
                         'root_blocks_reused':s['cluster_count'],'pairs_reused':v['defined_pairs'],'NA':v['undefined_pairs'],'purpose':'EXPLORATORY_POST_G3'})
        return s
    for variant in ('main','cv0.1','cv0.3','control_delay'):
        effects[variant]={}
        for method in ('QueueRepair0','BudgetHEFT10','BudgetSelect10','B0AssignmentReorder'):
            effects[variant][method]={c:compare(method,c,variant) for c in ('B2','LegacySAIL')}
            g=[r for r in new if r['variant']==variant and r['method']==method]
            assert all(r.get('optional_moves',0)<=r.get('budget_cap',0) for r in g)
            summary.append({'variant':variant,'method':method,'scenarios_reused':len(g),'mean_AWCT':statistics.mean(r['awct'] for r in g),
                            'mean_CDI':statistics.mean(r['cdi'] for r in g if r['cdi'] is not None),'CDI_NA':sum(r['cdi'] is None for r in g),
                            'mean_Churn':statistics.mean(r['churn'] for r in g),'hard_budget_violations':sum(r.get('optional_moves',0)>r.get('budget_cap',0) for r in g),
                            'predicted_quality_infeasible':sum(r['quality_feasible'] is False for r in g) if method=='BudgetSelect10' else None,
                            'actual_AWCT_over_1.05_B2':sum(r['awct']>1.05*next(x['awct'] for x in old if x['scenario_id']==r['scenario_id'] and x['method']=='B2') for r in g)})
        effects[variant]['mechanisms']={'QueueRepair0_vs_B0':compare('QueueRepair0','B0',variant),
                                       'B0AssignmentReorder_vs_B0':compare('B0AssignmentReorder','B0',variant),
                                       'BudgetSelect10_vs_BudgetHEFT10':compare('BudgetSelect10','BudgetHEFT10',variant)}
        print('exploratory analysis '+variant,flush=True)
    dump(report/'pilot_statistics.json',{'purpose':'EXPLORATORY_POST_G3','effects':effects,'method_summary':summary,
         'source_estimator':'unchanged sail.statistics.paired_bootstrap; variant/method relabelled only in in-memory comparison views',
         'new_independent_real_test_sets':0,'original_G3_status':'NOT_SUPPORTED','p_values_reported':False,
         'interval_interpretation':'Descriptive effects on reused v1 benchmarks; design followed v1 outcomes. Intervals do not establish new confirmatory support.'})
    write_csv(report/'paired_effects.csv',flat);write_csv(report/'method_summary.csv',summary)
    print(json.dumps(summary,ensure_ascii=False))


if __name__=='__main__':main()
