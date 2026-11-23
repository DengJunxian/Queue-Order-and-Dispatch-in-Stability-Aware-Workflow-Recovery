"""Execution-only sharding; imports the registered runner without editing it."""
import argparse
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from revision_r4 import run_experiments as runner
from revision_r4.common import Evidence,OUT,sha,dump


def main(name,lo,hi):
    registration=json.loads((OUT/'reports/shard_registration.json').read_text())
    assert sha(Path(__file__))==registration['wrapper_sha256']
    item=next(x for x in registration['shards'] if x['name']==name)
    assert (lo,hi)==(item['root_lo'],item['root_hi'])
    class SubsetEvidence(Evidence):
        def __init__(self):
            super().__init__();self.cases=[c for c in self.cases if lo<=c['root_seed']<=hi]
    destination=OUT/'shards'/name;folder=destination/'exploratory/dispatch';folder.mkdir(parents=True,exist_ok=True)
    journal=folder/'metrics.jsonl'
    if not journal.exists():
        prefix=(OUT/'exploratory/dispatch/metrics.jsonl').read_bytes()
        assert sha(OUT/'exploratory/dispatch/metrics.jsonl')==registration['prefix_journal_sha256']
        journal.write_bytes(prefix)
    runner.Evidence=SubsetEvidence;runner.OUT=destination
    runner.main('dispatch')
    rows=[json.loads(s) for s in journal.read_text().splitlines()]
    relevant=[r for r in rows if lo<=r['root_seed']<=hi]
    assert len(relevant)==(hi-lo+1)*24*16 and len({r['job_id'] for r in relevant})==len(relevant)
    dump(destination/'shard_complete.json',{'status':'PASS','root_lo':lo,'root_hi':hi,'journal_sha256':sha(journal)})


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--name',required=True);p.add_argument('--lo',type=int,required=True);p.add_argument('--hi',type=int,required=True)
    a=p.parse_args();main(a.name,a.lo,a.hi)
