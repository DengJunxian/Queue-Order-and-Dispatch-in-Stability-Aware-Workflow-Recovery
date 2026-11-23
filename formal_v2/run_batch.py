"""Launch the sealed v2 entry point; keep progress outside immutable deliveries."""
import json
import re
import subprocess
import sys
from datetime import datetime,timezone
from pathlib import Path
from time import perf_counter
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from sail.development import dump
from v2_preparation.frozen import verify_v2,sha


def main():
    freeze=ROOT/'freeze/g2_v2_20261025';output=ROOT/'results/g2_v2_20261025';folder=ROOT/'formal_v2/reports';folder.mkdir(parents=True,exist_ok=True)
    cfg,mf=verify_v2(ROOT,freeze);jobs=mf['jobs'];count=0;journal=output/'metrics.jsonl'
    if journal.exists():
        ids=[json.loads(x)['job_id'] for x in journal.read_text().splitlines()]
        if ids!=[j['id'] for j in jobs[:len(ids)]]:raise ValueError('checkpoint is not the expected immutable job prefix')
        count=len(ids)
    start=perf_counter();utc=datetime.now(timezone.utc);local=utc.astimezone(ZoneInfo('Asia/Shanghai'))
    command=[sys.executable,str(ROOT/'v2_preparation/run_confirmatory.py'),'--freeze',str(freeze),'--output',str(output)]
    def progress(n,status):
        now=datetime.now(timezone.utc);prefix=jobs[:n];aliases=sum(bool(j.get('execution_alias_of')) for j in prefix)
        dump(ROOT/'progress/current.json',{'stage':status,'freeze':'freeze/g2_v2_20261025','freeze_id':sha(freeze/'inputs_manifest.json'),
             'formal_labels_completed':n,'nominal_jobs':len(jobs),'physical_executions_completed':n-aliases,'alias_records_completed':aliases,
             'started_at':utc.isoformat(),'updated_at':now.isoformat(),'display_timezone':'Asia/Shanghai','original_v1_G3':'NOT_SUPPORTED',
             'next_stage':'INDEPENDENT_AUDIT_STATISTICS_G3_V2','report_folder':'formal_v2/reports'})
    progress(count,'V2_CONFIRMATORY_RUNNING')
    (ROOT/'LATEST_RESEARCH.md').write_text(f'# 当前研究进展\n\n{local:%Y-%m-%d %H:%M}（Asia/Shanghai）：正在按冻结protocol_v2运行全部15,780标签。\n\n实时进度：[progress/current.json](progress/current.json)。\n执行日志：[formal_v2/reports/run_stdout.log](formal_v2/reports/run_stdout.log)。\n\n随后进行独立复算、冻结统计和G3_v2判断。历史交付与算法hash保持。\n')
    with (folder/'run_stdout.log').open('a') as log:
        proc=subprocess.Popen(command,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1)
        dump(folder/'active_process.json',{'pid':proc.pid,'started_at':utc.isoformat(),'local_started_at':local.isoformat(),'command':command,'resume_prefix_labels':count})
        for line in proc.stdout:
            log.write(line);log.flush();match=re.search(r'v2 frozen labels (\d+)/(\d+)',line)
            if match:
                count=int(match[1]);progress(count,'V2_CONFIRMATORY_RUNNING')
                if count%250==0:print(line,end='',flush=True)
            else:print(line,end='',flush=True)
        code=proc.wait()
    end=datetime.now(timezone.utc)
    dump(folder/'execution_wall_clock.json',{'started_at_UTC':utc.isoformat(),'finished_at_UTC':end.isoformat(),
         'started_at_Asia_Shanghai':local.isoformat(),'finished_at_Asia_Shanghai':end.astimezone(ZoneInfo('Asia/Shanghai')).isoformat(),
         'wall_seconds':perf_counter()-start,'exit_code':code,'command':command,'resume_prefix_labels':count if code else 0,
         'timezone_for_display':'Asia/Shanghai'})
    if code==0:
        summary=json.loads((output/'execution_summary.json').read_text());progress(summary['completed_labels'],'V2_RUNS_COMPLETE_PENDING_AUDIT' if summary['all_complete'] else 'V2_PARTIAL')
    else:progress(count,'V2_EXECUTION_ERROR_PRESERVED')
    raise SystemExit(code)


if __name__=='__main__':main()
