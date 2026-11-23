"""P4 entry point. Calling it executes the specified frozen experiment jobs."""
import argparse
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from sail.frozen import execute_frozen,verify_freeze


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--freeze",required=True);parser.add_argument("--output",required=True)
    parser.add_argument("--plan-only",action="store_true");parser.add_argument("--limit",type=int)
    args=parser.parse_args()
    if args.plan_only:
        _,manifest=verify_freeze(ROOT,Path(args.freeze));print(json.dumps({"verified":True,"nominal_jobs":len(manifest["jobs"]),"executed":0}))
    else:print(json.dumps(execute_frozen(ROOT,Path(args.freeze),Path(args.output),job_limit=args.limit),ensure_ascii=False))
