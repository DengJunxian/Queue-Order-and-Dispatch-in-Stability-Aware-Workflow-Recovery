"""Post-hoc sensitivity for fixed R4 results; never writes an R4 artifact."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "revision_r5" / "analysis_existing"
PROTOCOL = ROOT / "revision_r5" / "analysis_existing_protocol.json"
LOCK = ROOT / "revision_r5" / "analysis_existing_registration.json"
AL, BS, PF = "B0AssignmentReorder", "BudgetSelect10", "ProtectedFirst"
METHODS = {"B0", AL, "QueueRepair0", BS, "PoolMinAWCT10", PF, "WorkflowGuard"}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, allow_nan=False) + "\n")


def main() -> None:
    p = json.loads(PROTOCOL.read_text())
    registration = json.loads(LOCK.read_text())
    assert registration["analysis_has_run"] is False
    for relative, expected in registration["sha256"].items():
        assert sha(ROOT / relative) == expected, f"Registered input changed: {relative}"
    source = ROOT / p["source"]
    raw = [json.loads(line) for line in source.read_text().splitlines()]
    assert len(raw) == 23040
    grid = {}
    for r in raw:
        if r["method"] == "reference":
            continue
        key = r["scenario_id"], r["rule"], r["method"]
        assert key not in grid
        assert r["status"] == "COMPLETE"
        assert r["variant"] == "main"
        assert np.isfinite(r["cdi"]) and np.isfinite(r["awct"]) and r["awct"] > 0
        grid[key] = r
    ids = sorted({key[0] for key in grid})
    assert len(ids) == 1440 and len(grid) == 1440 * 7 * 2
    roots = sorted({r["root_seed"] for r in grid.values()})
    assert roots == list(range(81000, 81060))
    by_root = {root: [] for root in roots}
    case_vectors = {}
    capture_vectors = {}
    for sid in ids:
        assert {m for ss, rule, m in grid if ss == sid and rule == "strict"} == METHODS
        assert {m for ss, rule, m in grid if ss == sid and rule == "skip-unready"} == METHODS
        def val(rule, method, metric):
            return grid[sid, rule, method][metric]
        strict_al = val("strict", AL, "cdi") - val("strict", "B0", "cdi")
        skip_al = val("skip-unready", AL, "cdi") - val("skip-unready", "B0", "cdi")
        row = grid[sid, "strict", "B0"]
        root = row["root_seed"]
        cell = (row["mix"], row["nodes"], row["ccr"], row["failure_fraction"])
        by_root[root].append((cell, sid))
        case_vectors[sid] = [
            strict_al, skip_al, skip_al - strict_al,
            val("strict", BS, "cdi") - val("strict", AL, "cdi"),
            val("skip-unready", BS, "cdi") - val("skip-unready", AL, "cdi"),
            100 * (val("skip-unready", PF, "awct") / val("skip-unready", BS, "awct")
                   - val("strict", PF, "awct") / val("strict", BS, "awct")),
        ]
        capture_vectors[sid] = [val("strict", "B0", "cdi") - val("strict", AL, "cdi"),
                                val("strict", "B0", "cdi") - val("strict", BS, "cdi")]
    expected_cells = {(mix, nodes, ccr, fraction) for mix in "ABC" for nodes in (4, 8)
                      for ccr in (.5, 2) for fraction in (.3, .6)}
    assert all(len(rows) == 24 and {cell for cell, _ in rows} == expected_cells
               for rows in by_root.values())
    values = np.array([np.mean([case_vectors[sid] for _, sid in sorted(by_root[root])], axis=0)
                       for root in roots])
    capture = np.array([np.mean([capture_vectors[sid] for _, sid in sorted(by_root[root])], axis=0)
                        for root in roots])
    rng = np.random.Generator(np.random.PCG64(p["bootstrap"]["seed"]))
    indices = rng.integers(0, len(roots), size=(p["bootstrap"]["draws"], len(roots)))
    point = values.mean(axis=0)
    boot = values[indices].mean(axis=1)
    cap_boot = capture[indices].mean(axis=1)
    counts = np.array([np.bincount(row, minlength=len(roots)) for row in indices])
    indirect = counts @ values / len(roots)
    indirect_capture = counts @ capture / len(roots)
    max_difference = float(max(np.max(abs(indirect - boot)), np.max(abs(indirect_capture - cap_boot))))
    assert max_difference < 1e-12
    se = boot.std(axis=0, ddof=1)
    assert np.all(se > 0)
    max_standardized = np.max(abs((boot - point) / se), axis=1)
    critical = float(np.quantile(max_standardized, .95))
    loo = (values.sum(axis=0) - values) / (len(roots) - 1)
    cap_loo = (capture.sum(axis=0) - capture) / (len(roots) - 1)
    assert np.all(cap_boot[:, 1] > 0) and np.all(cap_loo[:, 1] > 0)
    cap_ratio_boot = cap_boot[:, 0] / cap_boot[:, 1]
    cap_ratio_loo = cap_loo[:, 0] / cap_loo[:, 1]
    prior = json.loads((ROOT / p["prior_analysis"]).read_text())
    prior_estimands = [
        prior["dispatch"]["strict"]["contrasts"][AL + "_minus_B0"]["cdi"],
        prior["dispatch"]["skip-unready"]["contrasts"][AL + "_minus_B0"]["cdi"],
        prior["dispatch_interaction_difference_in_differences_vs_B0"][AL],
        prior["dispatch"]["strict"]["contrasts"][BS + "_minus_" + AL]["cdi"],
        prior["dispatch"]["skip-unready"]["contrasts"][BS + "_minus_" + AL]["cdi"],
    ]
    prior_diffs = []
    for i, estimand in enumerate(prior_estimands):
        prior_diffs.append(abs(point[i] - estimand["point"]))
        prior_diffs.extend(abs(np.quantile(boot[:, i], [.025, .975]) - np.array(estimand["ci95"])))
    assert max(prior_diffs) < 1e-12
    contrasts = {}
    for j, spec in enumerate(p["simultaneous_family"]):
        contrasts[spec["name"]] = {
            **spec, "point": float(point[j]), "bootstrap_se": float(se[j]),
            "percentile_ci95": np.quantile(boot[:, j], [.025, .975]).tolist(),
            "simultaneous_ci95": [float(point[j] - critical * se[j]), float(point[j] + critical * se[j])],
            "leave_one_root_out_range": [float(loo[:, j].min()), float(loo[:, j].max())],
            "leave_one_root_out_sign_changes": int(np.sum(np.sign(loo[:, j]) != np.sign(point[j]))),
        }
    result = {
        "status": "PASS", "analysis_id": p["analysis_id"], "purpose": p["status"],
        "new_simulation_executions": 0, "new_confirmatory_samples": 0,
        "cases": 1440, "root_blocks": 60, "fixed_topologies": 6, "cells_per_root": 24,
        "bootstrap": p["bootstrap"], "simultaneous_method": p["simultaneous_interval"],
        "simultaneous_family_size": 6, "simultaneous_critical_value": critical,
        "contrasts": contrasts,
        "capture_ratio": {
            "point": float(capture.mean(axis=0)[0] / capture.mean(axis=0)[1]),
            "percentile_ci95": np.quantile(cap_ratio_boot, [.025, .975]).tolist(),
            "valid_draws": len(cap_ratio_boot),
            "denominator_bootstrap_range": [float(cap_boot[:, 1].min()), float(cap_boot[:, 1].max())],
            "denominator_percentile_ci95": np.quantile(cap_boot[:, 1], [.025, .975]).tolist(),
            "leave_one_root_out_range": [float(cap_ratio_loo.min()), float(cap_ratio_loo.max())],
            "interpretation": p["capture_ratio"]["interpretation"],
        },
        "verification": {"independent_resampling_draws_checked": 5000,
                         "direct_vs_count_max_abs_difference": max_difference,
                         "prior_point_and_CI_checks": len(prior_diffs),
                         "prior_max_abs_difference": float(max(prior_diffs))},
        "input_sha256": registration["sha256"], "registration_sha256": sha(LOCK),
    }
    for relative, expected in registration["sha256"].items():
        assert sha(ROOT / relative) == expected
    save(OUT / "results.json", result)
    save(OUT / "root_estimands.json", {"columns": [x["name"] for x in p["simultaneous_family"]],
                                      "roots": roots, "values": values.tolist(),
                                      "capture_numerator_denominator": capture.tolist()})
    lines = ["# R5 既有 R4 结果的事后敏感性分析", "", "零新增执行，零新增确认性样本。",
             "六项比较在本分析执行前写入单独清单，但选择发生在已知 R4 结果之后。同时区间只覆盖此六项事后分析族，不能替代整篇研究的多重性控制。", "",
             "| 比较 | 点估计 | 单项 95% 区间 | 同时 95% 区间 | 删一根范围 |", "|---|---:|---|---|---|"]
    for name, v in contrasts.items():
        def interval(key):
            return "[" + ", ".join(f"{x:+.6f}" for x in v[key]) + "]"
        lines.append(f"| {name} | {v['point']:+.6f} | {interval('percentile_ci95')} | {interval('simultaneous_ci95')} | {interval('leave_one_root_out_range')} |")
    cr = result["capture_ratio"]
    lines += ["", f"Capture ratio：{100*cr['point']:.2f}%，95% CI [{100*cr['percentile_ci95'][0]:.2f}%, {100*cr['percentile_ci95'][1]:.2f}%]；删一根范围 [{100*cr['leave_one_root_out_range'][0]:.2f}%, {100*cr['leave_one_root_out_range'][1]:.2f}%]。",
              f"全部 5,000 draw 分母为正，范围 {cr['denominator_bootstrap_range']}。该比例是聚合结果差之比，不是可加因果解释份额。",
              f"标准化 bootstrap 最大偏差临界值 {critical:.6f}。60 次删一环境根后，六项比较的点估计方向均保持：{all(x['leave_one_root_out_sign_changes']==0 for x in contrasts.values())}。",
              f"两种重采样实现最大差 {max_difference:.3g}；已有 5 个点估计及其区间共 {len(prior_diffs)} 次复核最大差 {max(prior_diffs):.3g}。", ""]
    (OUT / "report_zh.md").write_text("\n".join(lines))
    print(json.dumps({"status": "PASS", "capture_ratio": result["capture_ratio"],
                      "simultaneous_critical_value": critical, "contrasts": contrasts}, indent=2))


if __name__ == "__main__":
    main()
