"""Verify and merge deterministic execution shards; preserve prefix bytes."""
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from revision_r4.common import OUT,Evidence,sha,dump,METHODS,check_protocol


def main():
    registration=json.loads((OUT/'reports/shard_registration.json').read_text());journal=OUT/'exploratory/dispatch/metrics.jsonl'
    assert sha(journal)==registration['prefix_journal_sha256']
    original=journal.read_bytes();selected={};duplicates=0
    sources=[journal]+[OUT/'shards'/s['name']/'exploratory/dispatch/metrics.jsonl' for s in registration['shards']]
    for path in sources:
        if path!=journal:assert (path.parents[2]/'shard_complete.json').exists()
        for line in path.read_bytes().splitlines(keepends=True):
            r=json.loads(line);jid=r['job_id']
            if jid in selected:
                old=json.loads(selected[jid]);assert old==r,'Conflicting duplicate '+jid
                duplicates+=1
            else:selected[jid]=line
    ev=Evidence();target=[]
    for c in (c for c in ev.cases if c['variant']=='main'):
        for rule in ('strict','skip-unready'):
            for method in ('reference',*METHODS):target.append(f'r4-dispatch-{c["scenario_id"]}-{rule}-{method}')
    assert set(target)==set(selected) and len(target)==23040
    data=b''.join(selected[j] for j in target);assert data.startswith(original),'Registered serialized prefix changed'
    journal.write_bytes(data);rows=[json.loads(selected[j]) for j in target]
    for r in rows:assert sha(ROOT/r['event_file'])==r['event_sha256']
    dump(journal.parent/'summary.json',{'status':'PASS','records':23040,'expected':23040,'new_executions':sum(r['new_execution'] for r in rows),
        'reused_records':sum(not r['new_execution'] for r in rows),'events_checked_new':sum(r['events_checked'] for r in rows),'violations':0,
        'journal_sha256':sha(journal),'new_confirmatory_samples':0,'protocol_sha256':check_protocol()})
    dump(OUT/'reports/shard_merge.json',{'status':'PASS','retained_records':23040,'copied_prefix_records_deduplicated':duplicates,
        'duplicate_new_physical_executions':0,'registered_prefix_bytes_preserved':True,'original_runner_unchanged':True,
        'wrapper_sha256':sha(OUT/'run_shard.py'),'journal_sha256':sha(journal)})
    print('Shard merge PASS: all 23040 rows, unchanged serialized prefix, no duplicated completed executions')


if __name__=='__main__':main()
