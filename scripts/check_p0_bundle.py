"""Check the delivered P0 bundle without running scheduling experiments."""
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads((ROOT / path).read_text())


def digest(path):
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def main():
    cfg = read("configs/protocol_v1.json")
    manifest = read("data/manifest_v1.json")
    summary = read("reports/p0/data_summary.json")
    budget = read("planning/experiment_budget_plan.json")
    refs = read("docs/literature_records.json")["records"]
    bib = (ROOT / "docs/references_verified.bib").read_text()
    checks = {
        "design_hash_matches": digest(cfg["protocol_markdown"]) == cfg["protocol_sha256"],
        "manifest_hash_matches": digest(cfg["data_manifest"]) == cfg["data_manifest_sha256"],
        "raw_and_parsed_file_hashes": all(digest(x["raw_path"]) == x["raw_sha256"] and digest(x["parsed_path"]) == x["parsed_sha256"] for x in manifest["records"]),
        "all_valid_core19_holdout1": all(x["eligible"] for x in manifest["records"]) and summary["split_counts"] == {"test_core": 19, "test_scale_holdout": 1},
        "no_test_tuning": cfg["data_split"]["real_development"] == cfg["data_split"]["real_validation"] == 0,
        "state_not_overstated": cfg["formal_runs_completed"] == 0 and not cfg["formal_experiment_frozen"] and not cfg["scheduler_implemented"] and cfg["parameter_selection"]["selected_lambda"] is None and cfg["parameter_selection"]["selected_mu"] is None,
        "budget_scenarios_consistent": all(p["core_total"] == 3*2*2*2*p["seeds"]*8 + 3*2*2*p["seeds"] and p["total_with_p0"] == p["core_total"] + 840 for p in budget["profiles"]),
        "bibliography13_unique": len(refs) == len({x["doi"].lower() for x in refs}) == len(re.findall(r"^@", bib, re.M)) == 13,
        "notebook_executed_outputs": all(c["execution_count"] is not None and c["outputs"] for c in read("notebooks/p0_data_validation.ipynb")["cells"] if c["cell_type"] == "code"),
        "required_artifacts_exist": all((ROOT / p).is_file() for p in ["docs/P0_新颖性核查与定位.md", "reports/p0/数据验证报告.md", "reports/p0/P0_阶段验收.md", "docs/protocol_v1.md", "data/vendor_manifest.json", "requirements-p0.txt"]),
    }
    result = {"checks": checks, "passed": sum(checks.values()), "failed": sum(not v for v in checks.values()),
              "scope": "P0 artifact consistency, not scheduling correctness"}
    (ROOT / "reports/p0/bundle_checks.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return int(not all(checks.values()))


if __name__ == "__main__":
    raise SystemExit(main())
