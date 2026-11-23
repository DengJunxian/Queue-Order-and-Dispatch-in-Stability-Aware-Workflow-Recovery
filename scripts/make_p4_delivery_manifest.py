"""Hash the current P4 delivery; event hashes remain in the audited immutable journal."""
import hashlib
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from sail.development import dump
from sail.frozen import verify_freeze


def main():
    verify_freeze(ROOT,ROOT/'freeze/g2_v1_20261025')
    folder=ROOT/'reports/p4';target=folder/'delivery_manifest.json'
    paths={p for p in folder.rglob('*') if p.is_file() and p!=target}
    paths.update(ROOT/p for p in ('README.md','CSCWD2027_研究与投稿计划.md','CSCWD2027_执行清单.md','project_state.json',
                                  'planning/experiment_budget_plan.json','configs/p4_reporting_spec.json','requirements-p3.txt',
                                  'scripts/run_p4_pipeline.py','scripts/audit_p4_outputs.py','scripts/analyze_p4_extensions.py',
                                  'scripts/diagnose_p4.py','scripts/compile_p4_secondary.py','scripts/plot_p4.py',
                                  'scripts/check_p4_bundle.py','scripts/write_p4_report.py','scripts/make_p4_delivery_manifest.py',
                                  'results/g2_v1_20261025/metrics.jsonl','results/g2_v1_20261025/RUN_MANIFEST.json',
                                  'results/g2_v1_20261025/execution_summary.json','results/g2_v1_20261025/statistics.json',
                                  'freeze/g2_v1_20261025/inputs_manifest.json'))
    records=[{'path':str(p.relative_to(ROOT)),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(paths)]
    audit=json.loads((folder/'audit_summary.json').read_text())
    result={'stage':'P4','purpose':'Auditable stage artifacts; original G2 freeze remains authoritative for algorithms/inputs.',
            'files':records,'event_files':{'count':6240,'sha256_index':'results/g2_v1_20261025/metrics.jsonl',
            'physical_event_audit':'reports/p4/audit_summary.json','recomputed_event_records':audit['persisted_event_records_recomputed']},
            'G3_original_hypothesis_supported':False,'new_independent_diagnostic_observations':0}
    dump(target,result);print(json.dumps({'hashed_delivery_files':len(records),'raw_event_hashes_in_journal':6240}))


if __name__=='__main__':main()
