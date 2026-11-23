"""Guarded v2 entry point. --plan-only verifies inputs without any simulation."""
import argparse
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from v2_preparation.frozen import execute_v2,verify_v2


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--freeze',default=str(ROOT/'freeze/g2_v2_20261025'));p.add_argument('--output',default=str(ROOT/'results/g2_v2_20261025'))
    p.add_argument('--plan-only',action='store_true');p.add_argument('--limit',type=int);a=p.parse_args()
    if a.plan_only:
        cfg,mf=verify_v2(ROOT,Path(a.freeze));print(json.dumps({'status':cfg['status'],'purpose':cfg['purpose'],'root_seeds':len(cfg['root_seeds']),
            'jobs':len(mf['jobs']),'bases':len(mf['bases']),'scenarios':len(mf['scenarios']),'simulations_executed':0}))
    else:print(json.dumps(execute_v2(ROOT,Path(a.freeze),Path(a.output),a.limit)))
