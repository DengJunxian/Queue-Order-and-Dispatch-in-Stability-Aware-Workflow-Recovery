"""Compact complete-plan ledger, sufficient to replay the whole factorial."""
import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from revision_r4.common import OUT, Evidence, read_rows, read_doc, sha, dump, METHODS


def main():
    ev = Evidence(); rows = read_rows(OUT / 'exploratory/dispatch/metrics.jsonl'); assert len(rows) == 23040
    indexed = {(r['scenario_id'], r['rule'], r['method']): r for r in rows}; bases = {}; cases = []
    for case in (c for c in ev.cases if c['variant'] == 'main'):
        sid, bid = case['scenario_id'], case['base_id']
        if bid not in bases:
            b = ev.bases[bid]
            bases[bid] = {**b, 'initial_queues': ev.initial_plan(bid).queues}
        plans = {}
        for m in METHODS:
            row = indexed[sid, 'strict', m]; path = ROOT / row['event_file']; assert sha(path) == row['event_sha256']
            doc = read_doc(path); event = next(e for e in doc['events'] if e['kind'] == 'PLAN_APPLIED')
            plans[m] = {**event['details'], 'source_event_sha256': row['event_sha256']}
        expected = {rule: {m: {k: indexed[sid,rule,m][k] for k in ('awct','cdi','churn','workflow_completion','plan_sha256')} for m in METHODS}
                    for rule in ('strict','skip-unready')}
        ctx = read_doc(ROOT / indexed[sid,'strict','B0']['event_file'])['context']
        cases.append({**{k: case[k] for k in ('scenario_id','base_id','root_seed','mix','nodes','ccr','failure_fraction')},
                      'failure_time': ev.failure(case).time, 'failed_node': ev.failure(case).node,
                      'context': ctx, 'plans': plans, 'expected': expected})
    result = {'scope': 'Complete original strict recovery plans, paired expected outcomes and fixed inputs for replaying all 1440 x 7 x 2 cases.',
              'cases': cases, 'bases': bases, 'original_inputs_manifest_sha256': sha(ROOT/'freeze/g2_v2_20261025/inputs_manifest.json'),
              'metric_journal_sha256': sha(OUT/'exploratory/dispatch/metrics.jsonl')}
    path = ROOT/'paper_v7/artifact/factorial_plans.json.gz'; path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(gzip.compress(json.dumps(result,separators=(',',':')).encode(),compresslevel=6,mtime=0))
    dump(OUT/'reports/factorial_export.json',{'status':'PASS','scenarios':len(cases),'methods':7,'dispatch_rules':2,'complete_plans':10080,
        'path':str(path.relative_to(ROOT)),'bytes':path.stat().st_size,'sha256':sha(path)})
    print('Complete factorial plan ledger exported',path.stat().st_size)


if __name__=='__main__':main()
