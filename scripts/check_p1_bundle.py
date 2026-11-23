"""Verify the P1 handoff without rerunning tests or experiments."""
import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads((ROOT/path).read_text())


def digest(path):
    return hashlib.sha256((ROOT/path).read_bytes()).hexdigest()


def main():
    summary = read("reports/p1/acceptance_summary.json")
    manifest = read("reports/p1/artifact_manifest.json")
    cfg = read("configs/protocol_v1.json")
    state = read("project_state.json")
    cases = read("reports/p1/systematic_results.json")
    adapters = read("reports/p1/adapter_checks.json")
    suites = ET.parse(ROOT/"reports/p1/pytest_results.xml").getroot().findall("testsuite")
    checks = {
        "all_artifact_hashes_match":all(digest(r["path"])==r["sha256"] for r in manifest["records"]),
        "tested_code_and_inputs_unchanged":all(digest(p)==sha for p,sha in summary["code_and_test_hashes"].items()),
        "protocol_and_test_data_unchanged":digest("docs/protocol_v1.md")==cfg["protocol_sha256"]==summary["protocol_sha256"] and digest("data/manifest_v1.json")==cfg["data_manifest_sha256"]==summary["manifest_sha256"],
        "all_tests_passed":all(int(s.get("failures",0))==int(s.get("errors",0))==int(s.get("skipped",0))==0 for s in suites) and sum(int(s.get("tests",0)) for s in suites)==summary["tests"]["passed"],
        "systematic_cases_complete":cases["session_exit_code"]==0 and cases["inputs_unchanged_during_tests"] and cases["completed_cases"]==1084 and cases["counts"]=={"exhaustive_fixed_plan":1024,"synthetic_failure":60},
        "twenty_inputs_adapted_without_real_execution":adapters["verified"]==20 and adapters["real_execution_runs"]==0 and all(not r["executed"] for r in adapters["records"]),
        "hand_calculated_examples_present":len(read("reports/p1/examples/index.json"))==3,
        "P1_passed_with_P2_pending":state["P1_passed"] and state["current_stage"]=="P1_COMPLETE" and not state["G1_passed"] and not state["G2_passed"],
        "research_status_not_overstated":state["formal_runs_completed"]==0 and not state["formal_experiment_frozen"] and not state["initial_HEFT_implemented"] and not state["B0_B1_B2_implemented"] and not state["SAIL_implemented"] and state["selected_lambda"] is None and state["selected_mu"] is None,
    }
    result = {"checks":checks,"passed":sum(checks.values()),"failed":sum(not v for v in checks.values()),"scope":"P1 handoff consistency"}
    # This self-check result is derived after the artifact manifest; do not add it to that manifest.
    (ROOT/"reports/p1/bundle_checks.json").write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result,indent=2))
    return int(not all(checks.values()))


if __name__=="__main__":
    raise SystemExit(main())
