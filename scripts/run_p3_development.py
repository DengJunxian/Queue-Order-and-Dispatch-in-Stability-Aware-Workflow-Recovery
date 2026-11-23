"""Execute the protocol's synthetic development/validation selection only."""
import json
import sys
import traceback
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from sail.development import dump,run_selection


if __name__=="__main__":
    try:
        result=run_selection(ROOT)
        print(json.dumps({"status":result["status"],"selected":result["selected"],"coverage":result["development_coverage"]},ensure_ascii=False),flush=True)
    except Exception:
        dump(ROOT/"reports/p3/selection_failure.json",{"status":"FAILED","traceback":traceback.format_exc(),"formal_runs_completed":0})
        raise
