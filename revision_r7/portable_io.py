"""Read unchanged full archives or hash-bound compact timing evidence."""
import gzip,hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read_document(case):
    p=ROOT/case['event_file']
    if p.exists():
        assert sha(p)==case['event_sha256'];return json.loads(gzip.decompress(p.read_bytes()))
    manifest=json.loads((ROOT/'revision_r7/portable/manifest.json').read_text())
    record=next(r for r in manifest['entries'] if r['source_event_file']==case['event_file'])
    assert record['source_event_sha256']==case['event_sha256']
    cp=ROOT/record['case_file'];assert sha(cp)==record['case_sha256']
    p=ROOT/record['compact_file'];assert sha(p)==record['compact_sha256']
    return json.loads(gzip.decompress(p.read_bytes()))
