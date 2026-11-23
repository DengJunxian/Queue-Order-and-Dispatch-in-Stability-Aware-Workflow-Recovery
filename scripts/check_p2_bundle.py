"""Verify P2/G1 evidence and frozen P1 provenance without rerunning experiments."""
import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def read(path): return json.loads((ROOT/path).read_text())
def sha(path): return hashlib.sha256((ROOT/path).read_bytes()).hexdigest()


def main():
    summary=read("reports/p2/acceptance_summary.json")
    artifacts=read("reports/p2/artifact_manifest.json")
    state=read("project_state.json")
    cfg=read("configs/protocol_v1.json")
    cases=read("reports/p2/systematic_results.json")
    archive=read("archive/p1_20261025/snapshot_manifest.json")
    suites=ET.parse(ROOT/"reports/p2/pytest_results.xml").getroot().findall("testsuite")
    expected={"exhaustive_fixed_plan":1024,"synthetic_failure":60,"p2_initial_enumeration":192,
              "p2_small_fault_enumeration":256,"p2_development_baselines":72}
    checks={
        "all_artifact_hashes_match":all(sha(r["path"])==r["sha256"] for r in artifacts["records"]),
        "tested_inputs_unchanged":cases["inputs_unchanged_during_tests"] and all(sha(p)==digest for p,digest in summary["code_and_test_hashes"].items()),
        "protocol_and_real_data_manifest_unchanged":sha("docs/protocol_v1.md")==cfg["protocol_sha256"]==summary["protocol_sha256"] and sha("data/manifest_v1.json")==cfg["data_manifest_sha256"]==summary["manifest_sha256"],
        "full_suite_passed":all(int(s.get("failures",0))==int(s.get("errors",0))==int(s.get("skipped",0))==0 for s in suites) and sum(int(s.get("tests",0)) for s in suites)==summary["tests"]["passed"],
        "all_planned_validation_cases_present":cases["session_exit_code"]==0 and cases["counts"]==expected and cases["completed_cases"]==1604,
        "P1_archive_hashes_match":all(sha("archive/p1_20261025/"+r["path"])==r["sha256"] for r in archive["records"]),
        "common_baselines_and_G1_complete":state["initial_HEFT_implemented"] and state["B0_B1_B2_implemented"] and state["P2_passed"] and state["G1_passed"],
        "SAIL_and_formal_run_state_preserved":not state["SAIL_implemented"] and not state["G2_passed"] and not state["formal_experiment_frozen"] and state["formal_runs_completed"]==0 and state["selected_lambda"] is None and state["selected_mu"] is None,
        "real_holdout_scheduling_runs_zero":summary["real_holdout_scheduling_runs"]==0,
        "three_reviewable_examples":len(read("reports/p2/examples/index.json"))==3,
        "scope_and_source_decision_recorded":(ROOT/"docs/P2_共同内核与基线说明.md").is_file() and summary["faithful_DaTR_replication"] is False,
    }
    result={"checks":checks,"passed":sum(checks.values()),"failed":sum(not v for v in checks.values()),"scope":"P2/G1 handoff consistency"}
    (ROOT/"reports/p2/bundle_checks.json").write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result,indent=2))
    return int(not all(checks.values()))


if __name__=="__main__": raise SystemExit(main())
