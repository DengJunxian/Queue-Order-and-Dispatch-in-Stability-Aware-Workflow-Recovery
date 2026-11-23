"""Seal prefreeze receipts; keep only the global progress pointer mutable."""
import hashlib
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from sail.development import dump
from v2_preparation.frozen import verify_v2,sha


def main():
    prep=ROOT/'v2_preparation';target=prep/'delivery_manifest.json';freeze=ROOT/'freeze/g2_v2_20261025';verify_v2(ROOT,freeze)
    paths=[p for p in prep.rglob('*') if p.is_file() and p!=target and '__pycache__' not in p.parts and '.pytest_cache' not in p.parts]
    paths += [p for p in freeze.rglob('*') if p.is_file()]
    records=[{'path':str(p.relative_to(ROOT)),'bytes':p.stat().st_size,'sha256':sha(p)} for p in sorted(paths)]
    result={'purpose':'G2_V2_FROZEN_NOT_RUN','files':records,'new_real_test_scheduling_runs':0,
            'original_v1_G3':'NOT_SUPPORTED','mutable_progress_excluded':['progress/current.json','LATEST_RESEARCH.md'],
            'prior_delivery_manifest_sha256':{p:sha(ROOT/p) for p in ('reports/p4/delivery_manifest.json','research_v2/delivery_manifest.json')},
            'freeze_id':sha(freeze/'inputs_manifest.json')}
    dump(target,result);print(json.dumps({'hashed_delivery_files':len(records),'freeze_id':result['freeze_id'],'new_test_runs':0}))


if __name__=='__main__':main()
