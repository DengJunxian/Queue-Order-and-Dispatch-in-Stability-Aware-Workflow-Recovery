"""Seal the completed formal batch and its independent acceptance evidence."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sail.development import dump
from v2_preparation.frozen import sha, verify_v2


def delivery_paths():
    target = ROOT / 'formal_v2/delivery_manifest.json'
    paths = []
    for directory in ('formal_v2', 'results/g2_v2_20261025'):
        paths.extend(p for p in (ROOT / directory).rglob('*')
                     if p.is_file() and p != target
                     and '__pycache__' not in p.parts
                     and '.pytest_cache' not in p.parts)
    return sorted(paths)


def main():
    freeze = ROOT / 'freeze/g2_v2_20261025'
    verify_v2(ROOT, freeze)
    folder = ROOT / 'formal_v2/reports'
    out = ROOT / 'results/g2_v2_20261025'
    read = lambda p: json.loads(p.read_text())
    audit = read(folder / 'audit_summary.json')
    check = read(folder / 'bundle_check.json')
    receipt = read(folder / 'stage_acceptance.json')
    pipeline = read(folder / 'postprocess_summary.json')
    clock = read(folder / 'execution_wall_clock.json')
    assert audit['status'] == check['status'] == 'PASS'
    assert receipt['execution_and_integrity_passed']
    assert clock['exit_code'] == 0
    assert all(step['exit_code'] == 0 for step in pipeline['steps'])
    assert sha(out / 'metrics.jsonl') == audit['raw_metrics_sha256']
    rows = [json.loads(line) for line in (out / 'metrics.jsonl').read_text().splitlines()]
    event_index = {'results/g2_v2_20261025/' + r['event_file']: r['event_sha256']
                   for r in rows}
    assert len(event_index) == 15660
    records = []
    for p in delivery_paths():
        rel = str(p.relative_to(ROOT))
        records.append({'path': rel, 'bytes': p.stat().st_size,
                        'sha256': event_index[rel] if rel in event_index else sha(p),
                        'hash_source': 'independently_verified_event_index'
                        if rel in event_index else 'file_content'})
    result = {
        'purpose': 'CONFIRMATORY_V2_COMPLETED_AND_INDEPENDENTLY_AUDITED',
        'freeze_id': sha(freeze / 'inputs_manifest.json'),
        'files': records,
        'nominal_labels': 15780,
        'physical_executions': 15660,
        'alias_records': 120,
        'G3_v2_supported': receipt['G3_v2_supported'],
        'original_v1_G3': 'NOT_SUPPORTED',
        'event_hash_provenance': 'All physical files were read and rehashed during the independent persisted-log audit; the final index reuses that audited receipt.',
        'mutable_progress_excluded': ['progress/current.json', 'LATEST_RESEARCH.md'],
        'prior_delivery_manifest_sha256': {
            p: sha(ROOT / p) for p in (
                'reports/p4/delivery_manifest.json',
                'research_v2/delivery_manifest.json',
                'v2_preparation/delivery_manifest.json')},
    }
    dump(ROOT / 'formal_v2/delivery_manifest.json', result)
    print(json.dumps({'sealed_files': len(records), 'physical_event_files': len(event_index),
                      'bytes': sum(r['bytes'] for r in records),
                      'G3_v2_supported': receipt['G3_v2_supported']}))


if __name__ == '__main__':
    main()
