"""Descriptive per-workflow slowdowns and remaining protocol secondary metrics."""
import json
import statistics
import sys
import platform
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from sail.development import dump
from scripts.analyze_p4_extensions import write_csv


def main():
    out=ROOT/'results/g2_v1_20261025';folder=ROOT/'reports/p4'
    rows=[json.loads(x) for x in (out/'metrics.jsonl').read_text().splitlines()];by_id={r['job_id']:r for r in rows}
    families={'A':('Montage','Epigenomics','SRA Search'),'B':('Montage','Montage','Epigenomics'),'C':('Epigenomics','SRA Search','SRA Search')}
    @lru_cache(maxsize=12)
    def doc(path):return json.loads((out/path).read_text())
    workrows=[];runrows=[]
    for row in rows:
        if row['kind']!='failure':continue
        d=doc(row['event_file']);ref=doc(by_id['ref-'+row['base_id']]['event_file'])
        rf=dict(ref['workflow_finishes'])
        for wid,completion in d['workflow_finishes']:
            workrows.append({'scenario_id':row['scenario_id'],'method':row['method'],'variant':row['variant'],'mix':row['mix'],
                             'root_seed':row['root_seed'],'workflow':wid,'family':families[row['mix']][int(wid[1:])],
                             'completion_seconds':completion,'no_fault_completion_seconds':rf[wid],'slowdown':completion/rf[wid]})
        runrows.append({'job_id':row['job_id'],'scenario_id':row['scenario_id'],'method':row['method'],'variant':row['variant'],
                        'total_attempts':sum(v for _,v in d['attempts']),'restarted_tasks':sum(v>1 for _,v in d['attempts']),
                        'task_count':len(d['attempts']),'cpu_seconds':d['cpu_seconds'],'wasted_cpu_seconds':d['wasted_cpu_seconds'],
                        'wasted_work':d['wasted_work'],'transfer_bytes':d['transfer_bytes'],'makespan':d['makespan']})
    assert len(workrows)==19440 and len(runrows)==6480
    buckets=defaultdict(list)
    for r in workrows:buckets[(r['variant'],r['mix'],r['method'],r['family'])].append(r['slowdown'])
    summary=[{'variant':k[0],'mix':k[1],'method':k[2],'family':k[3],'workflow_observations':len(v),'mean_slowdown':statistics.mean(v)}
             for k,v in sorted(buckets.items())]
    write_csv(folder/'data/workflow_slowdowns.csv',workrows);write_csv(folder/'data/family_slowdown_summary.csv',summary)
    write_csv(folder/'data/run_secondary_metrics.csv',runrows)
    dump(folder/'secondary_summary.json',{'workflow_rows':len(workrows),'failure_label_rows':len(runrows),
         'aggregation':'Family slowdown is the descriptive arithmetic mean of workflow instances within variant/Mix/method/family; repeated families remain explicit.',
         'independent_inference_unit':'root_seed blocks; workflow and attempt rows are not independent experimental observations',
         'new_hypothesis_tests':False})
    import csv
    metrics={r['scenario_id']:r for r in csv.DictReader((folder/'data/run_metrics.csv').open()) if r['variant']=='main' and r['method']=='SAIL'}
    candidates=list(csv.DictReader((folder/'data/candidate_diagnostics.csv').open()))
    errors=[abs(float(r['selected_predicted_CDI'])-float(metrics[r['scenario_id']]['cdi'])) for r in candidates]
    dump(folder/'prediction_diagnostic.json',{'scope':'all720 main selected SAIL predictions','max_abs_predicted_vs_actual_CDI_error':max(errors),
         'interpretation':'Main work CV=0: selected-plan CDI forecast agrees with realized metric; this does not isolate causes of performance against B2.'})
    dump(folder/'environment.json',{'python':sys.version,'executable':sys.executable,'platform':platform.platform(),'machine':platform.machine(),
         'processor':platform.processor(),'specific_CPU_model':None,'CPU_model_reason':'Detailed hardware fields were unavailable through the current environment.',
         'timing_processes':1,'timing_note':'Other host activity was not controlled. Timing repeats are descriptive and not additional independent experiments.'})


if __name__=='__main__':main()
