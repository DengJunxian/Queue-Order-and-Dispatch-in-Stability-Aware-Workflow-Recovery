"""Portable timing/plan evidence, retaining the selected full diagnostic event archive."""
import copy,gzip,hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];BASE=ROOT/'revision_r7'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def strip(x):
    if isinstance(x,dict):return {k:strip(v) for k,v in x.items() if k!='events'}
    if isinstance(x,list):return [strip(v) for v in x]
    return x

def main():
    target=BASE/'portable';target.mkdir(exist_ok=True);entries=[]
    for stage in ['calibration','evaluation']:
        (target/stage).mkdir(exist_ok=True)
        for p in sorted((BASE/stage/'cases').glob('*.json')):
            case=json.loads(p.read_text());src=ROOT/case['event_file'];assert sha(src)==case['event_sha256']
            doc=json.loads(gzip.decompress(src.read_bytes()));compact=strip(doc)
            out=target/stage/(p.stem+'.json.gz');raw=json.dumps(compact,separators=(',',':'),allow_nan=False).encode();out.write_bytes(gzip.compress(raw,mtime=0))
            entries.append({'case_file':str(p.relative_to(ROOT)),'case_sha256':sha(p),'source_event_file':case['event_file'],'source_event_sha256':sha(src),'compact_file':str(out.relative_to(ROOT)),'compact_sha256':sha(out),'compact_bytes':out.stat().st_size})
    (target/'manifest.json').write_text(json.dumps({'status':'PASS','cases':len(entries),'retained':'All inputs, public snapshots, plans, predictions, calibration diagnostics, task starts/finishes, workflow completion and metrics; only event arrays removed.','full_log_validation':'Full events audited before export; compact evidence permits arithmetic reconstruction and fresh execution, not persisted-log replay audits.','entries':entries},indent=2)+'\n')
    print(json.dumps({'status':'PASS','cases':len(entries),'compact_bytes':sum(r['compact_bytes'] for r in entries)}))
if __name__=='__main__':main()
