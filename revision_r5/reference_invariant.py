"""Reference-cancelling signed-start sensitivity for the saved R4 factorial."""
import hashlib
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "revision_r5" / "reference_invariant"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    protocol = json.loads((ROOT / "revision_r5/reference_invariant_protocol.json").read_text())
    lock = ROOT / "revision_r5/reference_invariant_registration.json"
    registered = json.loads(lock.read_text())
    for relative, expected in registered["sha256"].items():
        assert sha(ROOT / relative) == expected
    raw = [json.loads(s) for s in (ROOT / protocol["source"]).read_text().splitlines()]
    rows = {(r["scenario_id"], r["rule"], r["method"]): r for r in raw
            if r["method"] in ("B0", "B0AssignmentReorder")}
    assert len(rows) == 1440 * 4
    ids = sorted({k[0] for k in rows})
    grouped = {root: [] for root in range(81000, 81060)}
    cells = {root: set() for root in grouped}
    for sid in ids:
        quartet = [rows[sid, rule, method] for rule in ("strict", "skip-unready")
                   for method in ("B0", "B0AssignmentReorder")]
        assert len({r["context_sha256"] for r in quartet}) == 1
        assert len({r["protected_count"] for r in quartet}) == 1
        assert quartet[0]["protected_count"] > 0
        for rule in ("strict", "skip-unready"):
            assert rows[sid, rule, "B0"]["reference_workflow_completion"] == rows[sid, rule, "B0AssignmentReorder"]["reference_workflow_completion"]
        diffs = [rows[sid, rule, "B0AssignmentReorder"]["protected_signed"] - rows[sid, rule, "B0"]["protected_signed"]
                 for rule in ("strict", "skip-unready")]
        r = quartet[0]
        root = r["root_seed"]
        grouped[root].append([*diffs, diffs[1] - diffs[0]])
        cell = tuple(r[k] for k in ("mix", "nodes", "ccr", "failure_fraction"))
        assert cell not in cells[root]
        cells[root].add(cell)
    assert all(len(x) == 24 for x in grouped.values())
    assert len({tuple(sorted(v)) for v in cells.values()}) == 1
    values = np.array([np.mean(grouped[root], axis=0) for root in sorted(grouped)])
    assert np.isfinite(values).all()
    idx = np.random.Generator(np.random.PCG64(83000)).integers(0, 60, size=(5000, 60))
    boot = values[idx].mean(axis=1)
    count = np.array([np.bincount(row, minlength=60) for row in idx])
    difference = float(np.max(abs(boot - count @ values / 60)))
    assert difference < 1e-12
    loo = (values.sum(axis=0) - values) / 59
    result = {
        "status": "PASS", "purpose": protocol["status"], "sampling_unit": "environment root conditional on six fixed topologies",
        "cases": 1440, "roots": 60, "bootstrap_draws": 5000, "bootstrap_seed": 83000,
        "new_simulation_executions": 0, "new_confirmatory_samples": 0,
        "estimands": {name: {"point": float(values[:, j].mean()),
                             "percentile_ci95": np.quantile(boot[:, j], [.025, .975]).tolist(),
                             "leave_one_root_range": [float(loo[:, j].min()), float(loo[:, j].max())]}
                      for j, name in enumerate(protocol["estimands"])},
        "interpretation": protocol["interpretation"],
        "direct_vs_counts_max_abs_difference": difference,
        "input_sha256": registered["sha256"], "registration_sha256": sha(lock),
    }
    for relative, expected in registered["sha256"].items():
        assert sha(ROOT / relative) == expected
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
