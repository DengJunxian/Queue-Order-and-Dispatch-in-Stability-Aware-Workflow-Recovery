"""Current-task dependency chain: wait for success, audit, sealed stats, QA tables, plots."""
import json
import os
import subprocess
import sys
import time
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from sail.development import dump


def main():
    folder=ROOT/'formal_v2/reports';folder.mkdir(parents=True,exist_ok=True);output=ROOT/'results/g2_v2_20261025'
    record={'purpose':'current authorized formal task, not a recurring automation','steps':[],'created_at':datetime.now(timezone.utc).isoformat()}
    dump(folder/'postprocess_state.json',{'stage':'WAITING_FOR_COMPLETE_BATCH','pid':os.getpid()})
    while True:
        clock=folder/'execution_wall_clock.json';summary=output/'execution_summary.json'
        if clock.exists():
            c=json.loads(clock.read_text())
            if c['exit_code']!=0:raise RuntimeError('formal batch failed; original failure record preserved')
            if summary.exists() and json.loads(summary.read_text())['all_complete']:break
        time.sleep(2)
    steps=[('INDEPENDENT_LOG_AUDIT',['formal_v2/audit_outputs.py']),
           ('FROZEN_STATISTICS',['v2_preparation/analyze_confirmatory.py']),
           ('INDEPENDENT_STATISTICS_AND_TABLES',['formal_v2/analyze_reporting.py']),
           ('RESULT_FIGURES',['formal_v2/plot_results.py'])]
    for stage,args in steps:
        begin=time.perf_counter();state=json.loads((ROOT/'progress/current.json').read_text());state.update({'stage':'V2_'+stage,'updated_at':datetime.now(timezone.utc).isoformat()});dump(ROOT/'progress/current.json',state)
        dump(folder/'postprocess_state.json',{'stage':stage,'pid':os.getpid()});print('postprocess '+stage,flush=True)
        with (folder/(stage.lower()+'.log')).open('w') as log:
            proc=subprocess.Popen([sys.executable,*args],cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
            for line in proc.stdout:log.write(line);log.flush();print(line,end='',flush=True)
            code=proc.wait()
        record['steps'].append({'stage':stage,'exit_code':code,'wall_seconds':time.perf_counter()-begin});dump(folder/'postprocess_summary.json',record)
        if code:
            dump(folder/'postprocess_state.json',{'stage':'ATTENTION_REQUIRED','failed_step':stage,'exit_code':code})
            raise SystemExit(code)
    dump(folder/'postprocess_state.json',{'stage':'READY_FOR_VISUAL_QA_AND_STAGE_REPORT','finished_at':datetime.now(timezone.utc).isoformat()})
    print('postprocess ready for visual QA and stage report',flush=True)


if __name__=='__main__':main()
