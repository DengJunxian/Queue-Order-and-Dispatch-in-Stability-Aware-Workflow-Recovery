"""Check P3 selection, correctness evidence and G2 freeze without executing it."""
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from sail.development import source_fingerprint
from sail.frozen import verify_freeze


def read(path):return json.loads((ROOT/path).read_text())
def sha(path):return hashlib.sha256((ROOT/path).read_bytes()).hexdigest()


def main():
    summary=read("reports/p3/acceptance_summary.json");selection=read("reports/p3/parameter_selection.json")
    state=read("project_state.json");cfg=read("configs/protocol_v1.json")
    frozen,manifest=verify_freeze(ROOT,ROOT/summary["freeze_path"])
    artifacts=read("reports/p3/artifact_manifest.json")
    archive=read("archive/p2_20261025/snapshot_manifest.json")
    checks={
        "artifact_hashes_match":all(sha(r["path"])==r["sha256"] for r in artifacts["records"]),
        "correctness_source_unchanged":all(sha(p)==h for p,h in summary["test_source_hashes"].items()),
        "selection_source_unchanged":source_fingerprint(ROOT)["sha256"]==selection["source_fingerprint"]["sha256"],
        "independent_selection_complete":selection["development_scenarios"]==480 and selection["validation_scenarios"]==240 and len(selection["shortlist"])==3 and selection["selected"]["feasible"],
        "selected_parameters_match_freeze":frozen["selected_lambda"]==selection["selected"]["lambda"]==state["selected_lambda"] and frozen["selected_mu"]==selection["selected"]["mu"]==state["selected_mu"],
        "twenty_profile_cases":read("reports/p3/profiling_summary.json")["scenarios"]==20,
        "full_correctness_suite_passed":summary["tests"]["failed"]==summary["tests"]["skipped"]==0 and summary["tests"]["passed"]>=622,
        "protocol_and_data_manifest_unchanged":sha("docs/protocol_v1.md")==cfg["protocol_sha256"] and sha("data/manifest_v1.json")==cfg["data_manifest_sha256"],
        "frozen_jobs_complete":len(manifest["jobs"])==frozen["nominal_jobs"]==6960 and len(manifest["scenarios"])==900 and len(manifest["bases"])==480,
        "NoChurn_alias_explicit":frozen["method_aliases"].get("NoChurn")=="SAIL" and summary["expected_physical_executions"]==6240,
        "G2_complete_formal_not_run":state["G2_passed"] and state["formal_experiment_frozen"] and state["formal_runs_completed"]==summary["formal_runs_completed"]==0,
        "P2_snapshot_preserved":all(sha("archive/p2_20261025/"+r["path"])==r["sha256"] for r in archive["records"]),
    }
    result={"checks":checks,"passed":sum(checks.values()),"failed":sum(not v for v in checks.values()),"purpose":"P3/G2 consistency; no test scheduling"}
    (ROOT/"reports/p3/bundle_checks.json").write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result,indent=2));return int(not all(checks.values()))


if __name__=="__main__":raise SystemExit(main())
