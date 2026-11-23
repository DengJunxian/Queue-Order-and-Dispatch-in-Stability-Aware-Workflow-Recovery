"""Seal this exploratory delivery separately from the original v1 evidence."""
import hashlib
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from sail.development import dump
from sail.frozen import verify_freeze


def main():
    verify_freeze(ROOT,ROOT/'freeze/g2_v1_20261025');folder=ROOT/'research_v2';target=folder/'delivery_manifest.json'
    old=json.loads((ROOT/'reports/p4/delivery_manifest.json').read_text())
    for e in old['files']:assert hashlib.sha256((ROOT/e['path']).read_bytes()).hexdigest()==e['sha256']
    paths=[p for p in folder.rglob('*') if p.is_file() and p!=target and '__pycache__' not in p.parts and '.pytest_cache' not in p.parts]
    paths.append(ROOT/'RESEARCH_STATUS.md')
    entries=[{'path':str(p.relative_to(ROOT)),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(paths)]
    dump(target,{'purpose':'EXPLORATORY_POST_G3','files':entries,'original_v1_delivery':'reports/p4/delivery_manifest.json',
         'original_v1_delivery_sha256':hashlib.sha256((ROOT/'reports/p4/delivery_manifest.json').read_bytes()).hexdigest(),
         'original_G2_freeze':'freeze/g2_v1_20261025','new_confirmatory_runs':0,'new_independent_test_sets':0,
         'protocol_v2_status':'DESIGN_DRAFT','formal_v1_G3_status':'NOT_SUPPORTED'})
    print(json.dumps({'hashed_delivery_files':len(entries),'source_and_results_preserved':True,'new_confirmatory_runs':0}))


if __name__=='__main__':main()
