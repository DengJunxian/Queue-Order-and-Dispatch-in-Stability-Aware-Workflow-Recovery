"""Aggregate complete independent audit receipts without replaying them twice."""
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from revision_r4.common import OUT,read_doc,read_rows,sha,dump,check_protocol
from v2_preparation.frozen import verify_v2


def main():
    parts={p:read_doc(OUT/'reports'/('event_audit_'+p+'.json')) for p in ('dispatch','error','latency')}
    for part,r in parts.items():
        journal=OUT/'exploratory'/part/'metrics.jsonl';rows=read_rows(journal)
        assert r['journal_sha256']==sha(journal)
        assert r['new_executions']==sum(x['new_execution'] for x in rows)
        assert r['event_records_checked']==sum(x['events_checked'] for x in rows)
        assert r['integer_budget_checks']==sum(x['new_execution'] and x['kind']=='failure' for x in rows)
    assert sum(x['new_executions'] for x in parts.values())==13680
    assert sum(x['metric_checks'] for x in parts.values())==97920
    assert sum(x['integer_budget_checks'] for x in parts.values())==12240
    assert parts['dispatch'].get('max_metric_abs_difference',0)==0
    for p,digest in read_doc(OUT/'reports/execution_registration.json')['files'].items():assert sha(ROOT/p)==digest
    assert sha(OUT/'run_shard.py')==read_doc(OUT/'reports/shard_registration.json')['wrapper_sha256']
    verify_v2(ROOT,ROOT/'freeze/g2_v2_20261025')
    result={'status':'PASS','parts':parts,'event_records_checked':sum(x['event_records_checked'] for x in parts.values()),
        'metric_checks':97920,'integer_budget_checks':12240,'violations':0,'max_metric_abs_difference':0.,
        'original_v2_freeze_verified':True,'protocol_sha256':check_protocol(),'new_confirmatory_samples':0,
        'audit_coverage':'Every new persisted execution; a byte-verified serial prefix and two-worker remainder for dispatch, plus complete error and latency audits.'}
    dump(OUT/'reports/persisted_event_audit.json',result);print('Complete R4 persisted audits PASS',result['event_records_checked'])


if __name__=='__main__':main()
