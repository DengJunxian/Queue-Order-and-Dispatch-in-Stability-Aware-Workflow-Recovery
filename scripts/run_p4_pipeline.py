"""Launch the sealed P4 runner and preserve its stdout and wall-clock record."""
import json
import subprocess
import sys
import time
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


if __name__=="__main__":
    folder=ROOT/"reports/p4";folder.mkdir(parents=True,exist_ok=True)
    output=ROOT/"results/g2_v1_20261025"
    command=[sys.executable,str(ROOT/"scripts/run_frozen_experiments.py"),"--freeze",str(ROOT/"freeze/g2_v1_20261025"),"--output",str(output)]
    begin=time.perf_counter();start=datetime.now(timezone.utc).isoformat()
    state=json.loads((ROOT/"project_state.json").read_text())
    state.update({"current_stage":"P4_RUNNING","P4_started_at":start})
    (ROOT/"project_state.json").write_text(json.dumps(state,ensure_ascii=False,indent=2)+"\n")
    with (folder/"run_stdout.log").open("a") as log:
        process=subprocess.Popen(command,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
        for line in process.stdout:
            log.write(line);log.flush();print(line,end="",flush=True)
        code=process.wait()
    result={"started_at":start,"finished_at":datetime.now(timezone.utc).isoformat(),"exit_code":code,
            "wall_seconds":time.perf_counter()-begin,"command":command,"output":str(output)}
    (folder/"execution_wall_clock.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    raise SystemExit(code)
