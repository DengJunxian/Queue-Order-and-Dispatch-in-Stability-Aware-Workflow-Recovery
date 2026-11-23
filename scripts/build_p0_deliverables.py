"""Build P0 reports, machine-readable design, and an executed read-only notebook.

Consumes observed audit outputs. Does not run scheduling experiments or select weights.
"""
import contextlib
import csv
import hashlib
import io
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads((ROOT / path).read_text())


def write(path, value):
    p = ROOT / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def digest(path):
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def main():
    summary = read("reports/p0/data_summary.json")
    manifest = read("data/manifest_v1.json")
    profiles = list(csv.DictReader((ROOT / "reports/p0/data_profiles.csv").open()))
    tests = read("reports/p0/test_results.json")
    env = read("reports/p0/environment.json")
    config = {
        "version": "1.0", "date": "2026-10-25", "design_status": "FINAL_V1",
        "user_authorized_to_start": True, "authorized_current_stage": "P0",
        "formal_experiment_status": "NOT_READY_NOT_RUN", "formal_experiment_frozen": False,
        "scheduler_implemented": False, "formal_runs_completed": 0,
        "protocol_markdown": "docs/protocol_v1.md", "protocol_sha256": digest("docs/protocol_v1.md"),
        "data_manifest": "data/manifest_v1.json", "data_manifest_sha256": digest("data/manifest_v1.json"),
        "data_split": {"real_development": 0, "real_validation": 0, "real_test_core": 19, "real_test_scale_holdout": 1,
                       "distinct_real_topologies": 7, "development_and_validation": "independent synthetic DAGs"},
        "source_revision": manifest["source_revision"],
        "scenario": {"mixes": {"A": ["M", "E", "S"], "B": ["M", "M", "E"], "C": ["E", "S", "S"]},
                     "arrival_times": [0, 0, 0], "nodes": [4, 8], "ccr": [0.5, 2.0],
                     "failure_fractions": [0.3, 0.6], "failure_node": "uniform over all nodes, no resampling",
                     "failure_type": "single permanent, immediate detection", "restart": "from scratch",
                     "completed_outputs": "durable at completion, zero write overhead in main model",
                     "healthy_running_preemption": False, "runtime_normalization": "per-workflow arithmetic mean",
                     "speed_distribution": "8 Uniform(0.5,1.5), first m, normalize mean=1"},
        "randomness": {"generator": "numpy.random.PCG64", "seed_derivation": "SHA256(protocol_v1|root_seed|mix|stream|stable_id), first 16 bytes little-endian",
                       "streams": ["platform", "failure", "runtime", "synthetic"], "method_in_key": False,
                       "development_seeds": list(range(10000,10020)), "validation_seeds": list(range(20000,20010)),
                       "planned_test_seeds": list(range(60000,60030)), "minimum_test_seeds": list(range(60000,60010)),
                       "selected_test_seeds": None, "selection_requires_development_profiling": True},
        "sets": {"Q": "all pending at shared post-failure snapshot including interrupted attempts",
                 "F": "Q assigned to failed node before failure", "P": "healthy-assigned Q minus F and strict logical descendants of F",
                 "protection_set_shared_across_methods": True, "empty_P_actual_CDI": None},
        "communication": {"input_start": "all logical parents completed", "within_task_transfer": "serial remote files",
                          "cross_task_contention": False, "same_healthy_producer_node_cost": 0,
                          "failed_source": "durable storage at same effective B", "destination_change": "cancel and restart input preparation",
                          "external_inputs": "pre-staged", "cpu_queue": "strict head order; no ready backfilling"},
        "methods": ["B0_Requeue_EFT", "B1_Dependency_Repair", "B2_Global_Dynamic_HEFT", "SAIL", "NoStability", "NoChurn", "Fixed_H1", "Fixed_H2"],
        "aliases": {"Fixed_H0": "B0_Requeue_EFT"}, "faithful_DaTR_replication": False,
        "candidate_hops": [0,1,2], "outside_H": "fixed assignment and relative queue order, flexible times",
        "objective": "predicted_AWCT/fixed_predicted_no_fault_AWCT + lambda*predicted_CDI + mu*Churn",
        "metrics": {"CDI": "mean over fixed P of max(0,actual_start - matched_actual_no_fault_start)/pbar",
                    "Churn": "optional node changes in Q minus F / max(1,len(Q))",
                    "same_fault_signed_delay": "mean_P(actual_start_method - actual_start_B0)/pbar",
                    "actual_reference_visible_to_scheduler": False},
        "parameter_selection": {"lambda_grid": [0,0.1,0.3,1,3], "mu_grid": [0,0.01,0.1],
                                "selected_lambda": None, "selected_mu": None, "development_shortlist": 3,
                                "awct_relative_budget": 0.05, "selection_order": ["CDI", "AWCT", "Churn", "lambda", "mu"],
                                "selection_scope": "development shortlist then independent validation only"},
        "statistics": {"cluster": "root_seed, preserving all mixes/axes/methods in block", "bootstrap_repetitions": 5000,
                       "ci": "percentile two-sided 95%; AWCT budget one-sided upper 95%",
                       "inference_population": "fixed benchmark corpus under simulated environmental variation",
                       "primary": ["CDI SAIL minus B2", "AWCT relative difference SAIL vs B2"],
                       "mechanism_comparisons": ["NoStability", "NoChurn", "Fixed_H0", "Fixed_H1", "Fixed_H2"],
                       "mechanism_pvalues": "not required; Holm correction if reported"},
        "robustness": {"subset": "3 mixes x 2 CCR x first 10 test seeds; nodes=4, failure_fraction=0.6",
                       "scenario_count": 60, "runtime_cv": [0.1,0.3], "error_model": "mean-corrected lognormal task work",
                       "control_delay_pbar_units": 0.1, "primary_methods_only": True},
        "nominal_run_budget": {"30_seeds_core": 6120, "10_seeds_core": 2040, "required_robustness": 840,
                               "30_seeds_total": 6960, "10_seeds_total": 2880,
                               "excluded": ["development", "validation", "tests", "timing repetitions", "scale holdout"]},
        "profiling_budget_hours": 12, "code_revision": None, "scenario_manifest": None,
        "literature_access_limits": ["DaTR fulltext not obtained", "ReadyFS manuscript access failed", "FSCD direct fulltext 403"],
        "gates_remaining": ["P1 simulator correctness", "P2 baseline specification", "P3 development/validation and profiling", "G2 full freeze"],
    }
    write("configs/protocol_v1.json", config)
    budget = read("planning/experiment_budget_plan.json")
    budget.update({"user_authorized_to_start": True, "protocol_design_status": "FINAL_V1",
                   "data_manifest": "data/manifest_v1.json", "design_config": "configs/protocol_v1.json"})
    budget["notes"] = ["20 raw JSON files have been independently validated; 19 core and 1 scale test-only holdout.",
                       "Parameter selection and test seed count require development/validation and profiling before formal freeze.",
                       "P0 robustness in this older budget means priority-zero required experiments, not experiments run during phase P0.",
                       "Parameter-induced equivalent method configurations require explicit aliases; counts are nominal execution budgets."]
    write("planning/experiment_budget_plan.json", budget)

    grouped = defaultdict(list)
    for row in profiles:
        grouped[row["topology_group"]].append(row)
    table = ["| 家族/规模 | JSON数 | 每份任务数 | 每份边数 | 拓扑组 | 用途 |", "| --- | ---: | ---: | ---: | --- | --- |"]
    for gid, rows in grouped.items():
        r = rows[0]
        table.append(f"| {r['family']} {r['tasks']} | {len(rows)} | {r['tasks']} | {r['edges']} | {gid} | {'规模留出' if int(r['tasks'])>90 else '核心测试'} |")
    text = f"""# P0 数据验证报告

执行时间：{summary['executed_at']}。原始数据 revision：`{summary['source_revision']}`。

**20/20份记录可用于所定义的DAG工作量与文件依赖仿真。** 原始字节哈希、schema结构、任务/文件标识、执行记录连接、父子引用、无环性、正运行时间及非负文件大小均通过；独立检查发现37条日期元数据格式告警，已保留。

{chr(10).join(table)}

合计1,283条任务记录、1,965条有向依赖、2,493个文件对象。20份日志没有字节完全相同的重复文件；按家族内无标号有向图精确同构检查，只有7个不同拓扑组。SRA Search的每个规模含5份同拓扑日志，Montage的两份58任务记录同构。推断以固定基准集合为条件，日志数不等于独立拓扑数。

## 检查结果

| 检查 | 观察结果 |
| --- | --- |
| Git blob SHA 与本地SHA-256 | 20/20一致，来自同一固定revision |
| 官方WfFormat validator | 20/20有效，0 error、0 warning（见原始日志） |
| 独立结构/语义检查 | 0阻断错误，37时间戳警告 |
| 任务ID、执行ID与文件ID唯一性 | 通过；specification与execution任务ID集合一致 |
| 父子依赖对称、引用存在、DAG无环 | 通过 |
| 运行时间 | 全部有限且>0；范围0.039–4343.699原始秒 |
| 文件字节 | 有限非负整数；零字节文件0个 |
| 文件生产者 | 每个内部文件无歧义；所有内部生产消费依赖均为直接边 |
| 额外补边 / 无数据控制边 | 0 / 0 |
| 审计器异常输入测试 | {tests['passed']}通过、{tests['failed']}失败；覆盖重复ID、环、缺失、非法运行时间、非法字节和文件依赖 |

运行时间跨度大且跨应用测量背景不同。主实验按每个工作流的平均任务运行时间归一化，保留相对任务形态；原始尺度作为扩展，不据此声称恢复某个真实集群的绝对执行时间。

## 日期警告及处理

20个executedAt字段和17个createdAt字段不满足本审计采用的带时区RFC3339形式。官方validator结构检查通过不等于date-time format已强制检查。本报告把日期问题记作警告，因为仿真时序来自任务工作量、DAG、合成到达与故障事件；不以来源日期推断任务开始结束时间。原始字段未被修复或覆盖。

## 划分与可复算材料

19份40–90任务日志进入核心测试；103任务Montage进入独立规模留出。全部真实记录均为测试用途。开发/验证采用独立合成DAG，参数与随机流见 `docs/protocol_v1.md`；没有按测试算法表现选择实例。

逐文件画像：`reports/p0/data_profiles.csv`；逐条警告：`reports/p0/data_issues.json`；数据身份：`data/manifest_v1.json`；解析表：`data/processed/`；原始传输来源：`data/acquisition_manifest.json`；只读审计程序：`scripts/validate_p0_data.py`；检查输入异常的测试：`scripts/test_p0_data_validation.py`；可查看的notebook：`notebooks/p0_data_validation.ipynb`。

本次通过支持后续仿真输入使用；故障时间、故障节点、资源速度和运行时间扰动仍是协议定义的模拟变量。没有从原始记录获得真实故障标签，也没有运行SAIL算法比较。
"""
    (ROOT / "reports/p0/数据验证报告.md").write_text(text)

    # Execute the actual notebook code sequentially in a plain Python namespace.
    # These cells only inspect observed outputs and do not rerun simulation or tuning.
    cells = [{"cell_type": "markdown", "metadata": {}, "source": [
        "# P0 数据审计结果\n", "代码单元已由同一Python运行时顺序执行并保存实际stdout；未启动Jupyter服务。\n",
        "审计脚本与17项异常输入测试已经执行；本notebook只读其结果，不运行调度实验。请从项目根目录运行。"]}]
    code_cells = [
        "from pathlib import Path\nimport json, csv\nroot = Path.cwd()\nsummary = json.loads((root / 'reports/p0/data_summary.json').read_text())\nprint(json.dumps(summary, ensure_ascii=False, indent=2))\n",
        "from collections import defaultdict\ngroups = defaultdict(list)\nfor row in csv.DictReader((root / 'reports/p0/data_profiles.csv').open()):\n    groups[row['topology_group']].append(row)\nfor group, rows in groups.items():\n    r = rows[0]\n    print(group, r['family'], 'tasks=', r['tasks'], 'edges=', r['edges'], 'logs=', len(rows))\n",
        "manifest = json.loads((root / 'data/manifest_v1.json').read_text())\nfrom collections import Counter\nprint('split_counts:', dict(Counter(r['split'] for r in manifest['records'])))\nprint((root / 'reports/p0/test_results.json').read_text())\nassert len(manifest['records']) == 20\nassert summary['errors'] == 0\nassert summary['distinct_family_topologies'] == 7\n",
    ]
    namespace = {}
    for index, code in enumerate(code_cells, 1):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exec(compile(code, f"p0_notebook_cell_{index}", "exec"), namespace)
        cells.append({"cell_type": "code", "metadata": {}, "execution_count": index, "source": code.splitlines(True),
                      "outputs": [{"output_type": "stream", "name": "stdout", "text": stdout.getvalue().splitlines(True)}]})
    write("notebooks/p0_data_validation.ipynb", {"cells": cells, "metadata": {
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python", "version": env["python"]},
        "execution_note": "Cells executed sequentially by build_p0_deliverables.py; actual stdout captured."},
        "nbformat": 4, "nbformat_minor": 4})

    phase = """# P0 阶段验收与下一步

日期：2026-10-25。用户已授权按计划开始，并首先完成本阶段。

**决策：G0允许进入实现与正确性验证。** P0形成了可检查的数据、研究协议与文献定位；当前算法性能和正式投稿条件尚待后续实验。

| 项目 | 已完成的证据 | 验收判断 |
| --- | --- | --- |
| 新颖性核查 | 13项研究矩阵、书目与查询记录；FTDR/Repair/Last-K方法正文核查 | 问题收窄为保护任务预计延迟驱动的范围选择；DaTR全文未取得，绝对首创性未确立 |
| 原始数据 | 20份固定revision文件，Git blob与SHA-256一致 | 可追溯 |
| 数据质量 | 官方20/20；独立0错误、37日期警告；17项审计器测试通过 | 可用于已定义的仿真输入 |
| 测试划分 | 7拓扑组；19份核心测试、1份规模留出；独立合成开发/验证 | 防止同拓扑日志被错误当作独立训练/测试样本 |
| 协议 | F/Q/P、通信、随机故障、候选、指标、对照、统计、预算及变更规则 | 设计v1定稿；参数/代码/场景尚未到G2冻结 |
| 资源/时间 | Python3.12、10逻辑CPU、审计依赖已验证；内存值本次未读取到 | 可开始P1；仿真吞吐必须在开发阶段实测 |

## 对原计划的落实

保留8个方法配置和两项必做稳健性。30种子名义预算6,960次，10种子名义预算2,880次，均未运行。使用真实原始文件字节推导通信量；不需要补造边权。明确无预取为“逻辑父依赖齐备后才开始输入准备”，并给出迁移取消/重读与持久化读取规则。

数据从候选状态提升到已验证状态；原始日志的测量时间戳仍保持原样。研究从宽泛的局部恢复描述收敛到显式保护项与范围选择的机制检验。

## 证据边界与来源余项

P0-01原列的DaTR全文精读尚未达成：本次可读取的是出版社摘要与章节片段，未把它标记为全文已读。ReadyFS接受稿和FSCD正文也有访问限制。来源余项记录在文献表并进入P2的基线适配检查；不影响P1模拟器开发，但原版算法复现或首创性声称必须等相应证据。

权重仍为null，正式种子数尚待profiling决定，代码revision和最终场景manifest尚未生成。当前“研究协议定稿”指选择程序与评价规则确定，不表示调参完成或正式实验已封存。

## 下一阶段交付

P1建立事件模拟器和数据适配器；首先用手算DAG检查输入准备、资源队列、故障重试、完成输出持久化、过期事件及无影响故障。之后完成独立日志复算器、未来信息隔离和H外约束测试，再进入共同基线与SAIL实现。输入审计器的17个测试不替代这些模拟器测试。

CSCWD 2027官网截止仍按2026-10-31规划。P0完成后，本届冲刺取决于P1/G1正确性验收和P3实际profiling，当前没有证据承诺全部研究可在该日期前完成。完整路线与原定验收规范继续有效。

## 主要产物

- `docs/P0_新颖性核查与定位.md`
- `docs/literature_matrix.csv`、`docs/literature_records.json`、`docs/references_verified.bib`
- `reports/p0/数据验证报告.md`、`reports/p0/data_summary.json`
- `data/manifest_v1.json`、`data/acquisition_manifest.json`
- `docs/protocol_v1.md`、`configs/protocol_v1.json`
- `notebooks/p0_data_validation.ipynb`
- `scripts/validate_p0_data.py`、`scripts/test_p0_data_validation.py`
"""
    (ROOT / "reports/p0/P0_阶段验收.md").write_text(phase)
    # Native receipt: only approved aggregates and ordinary public links, no personal data/absolute paths.
    receipt = {"schemaVersion": 1, "items": [{
        "id": "p0-data-quality", "title": "工作流数据已通过结构与依赖验证", "queries": [{
            "id": "p0-observed-audit", "source": {
                "label": "WfInstances P0审计", "files": ["data_profiles.csv", "data_summary.json", "data_issues.json"],
                "links": [{"label": "WfInstances 固定版本", "href": "https://github.com/wfcommons/WfInstances/tree/249866063b3bd7d6a36a5a55d4202c1f683099c0"}],
                "metricDefinitions": ["验证范围为20份真实工作流JSON中的任务、依赖、文件和执行记录。"],
                "filters": ["家族：Montage、Epigenomics、SRA Search", "数据用途：全部真实记录为测试留出"],
                "caveats": ["20份日志只有7组不同拓扑，重复执行日志不代表独立拓扑样本。", "37处日期格式告警保留；这些字段不用于仿真时序。", "本次没有运行SAIL性能实验。"],
                "executedAt": summary["executed_at"],
                "evidenceFlow": [{"kind": "validation", "title": "实际检查", "description": "20份Git blob与SHA-256匹配；官方20/20通过；独立审计0阻断错误。审计器17项异常输入测试通过。"}]
            },
            "columns": [{"field": "files", "label": "JSON数"}, {"field": "tasks", "label": "任务数"}, {"field": "edges", "label": "依赖边数"}, {"field": "topologies", "label": "拓扑组数"}, {"field": "errors", "label": "阻断错误"}, {"field": "warnings", "label": "日期告警"}],
            "rows": [{"files": 20, "tasks": 1283, "edges": 1965, "topologies": 7, "errors": 0, "warnings": 37}],
            "preview": {"kind": "aggregate", "note": "全部20份记录的聚合审计结果", "totalRows": 20}
        }]}]}
    write("reports/p0/inline_sources.json", receipt)
    print("Built protocol config, report, phase decision, executed notebook, and receipt payload.")


if __name__ == "__main__":
    main()
