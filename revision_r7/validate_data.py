"""Validate the fixed source series without running recovery schedules."""
import hashlib
import json
from pathlib import Path
from scripts.validate_p0_data import validate_document, git_blob

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'revision_r7'


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def dump(p, x):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(x, indent=2, allow_nan=False) + '\n')


def main():
    selection = json.loads((OUT/'data/selection_protocol.json').read_text())
    tree = {r['path']: r for r in json.loads((OUT/'data/source_tree.json').read_text())['tree']}
    schema = json.loads((ROOT/'data/schema/wfcommons-schema.json').read_text())
    records, diagnostics, aligned = [], [], []
    for group in selection['new_series']:
        docs = []
        for repeat in selection['repeats']:
            source = group + f'-{repeat:03d}.json'
            path = OUT/'data/raw'/source
            raw = path.read_bytes()
            assert len(raw) == tree[source]['size'] and git_blob(raw) == tree[source]['sha'], source
            profile, issues, graph, parsed = validate_document(json.loads(raw), schema)
            diagnostics.append({'source': source, 'profile': profile, 'issues': issues})
            assert profile['error_count'] == 0, (source, issues)
            assert 20 <= profile['tasks'] <= 400 and profile['edge_bytes_sum'] > 0
            parsed.update({'source_sha256': sha(path), 'source_revision': selection['source_revision'], 'source_path': source})
            target = OUT/'data/processed'/path.name
            dump(target, parsed)
            identity = path.stem
            records.append({'id': identity, 'series': group, 'repeat': repeat, 'family': source.split('/')[1], 'source_url': f"https://github.com/wfcommons/WfInstances/blob/{selection['source_revision']}/{source}", 'git_blob_sha': tree[source]['sha'], 'raw_path': str(path.relative_to(ROOT)), 'parsed_path': str(target.relative_to(ROOT)), 'raw_sha256': sha(path), 'parsed_sha256': sha(target), 'eligible': True, 'tasks': profile['tasks'], 'split': 'prediction' if repeat <= 2 else 'calibration' if repeat == 3 else 'evaluation'})
            docs.append(parsed)
        signatures = []
        for d in docs:
            signatures.append((tuple(t['id'] for t in d['tasks']), tuple(sorted((e['source'], e['target']) for e in d['edges'])), tuple(sorted((tuple(sorted(f['producers'])), tuple(sorted(f['consumers']))) for f in d['files']))))
        equal = all(s == signatures[0] for s in signatures)
        aligned.append({'series': group, 'tasks': len(docs[0]['tasks']), 'exact_task_edge_file_incidence_alignment': equal})
        assert equal, group
    old = json.loads((ROOT/'data/manifest_v1.json').read_text())
    for row in old['records']:
        if row['id'].startswith('srasearch-chameleon-'):
            for kind in ['raw','parsed']:
                assert sha(ROOT/row[kind+'_path']) == row[kind+'_sha256']
            records.append(dict(row, series='pegasus/srasearch/'+row['id'].rsplit('-',1)[0], repeat=int(row['id'].rsplit('-',1)[1]), r7_previously_seen=True))
    assert len(records) == 45
    dump(OUT/'data/manifest.json', {'source_revision': selection['source_revision'], 'status':'VALIDATED_BEFORE_R7_SCHEDULING', 'selection_protocol_sha256':sha(OUT/'data/selection_protocol.json'), 'records':records})
    dump(OUT/'reports/data_validation.json', {'status':'PASS', 'new_source_records':30, 'existing_source_records':15, 'new_series':6, 'new_task_count_sum':sum(r['tasks'] for r in aligned), 'series_alignment':aligned, 'diagnostics':diagnostics, 'manifest_sha256':sha(OUT/'data/manifest.json')})
    print(json.dumps({'status':'PASS','new_records':30,'aligned':aligned}))


if __name__ == '__main__':
    main()
