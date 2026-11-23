"""Run P1 acceptance, preserve evidence, and build the stage report.

Uses only hand-built/synthetic execution fixtures. Real corpus files are adapted and
checked, never executed as formal research benchmark scenarios in this command.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform as host_platform
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from sail.audit import audit_result
from sail.data import Corpus
from sail.metrics import paired_metrics
from sail.model import Failure, Plan, Platform
from sail.simulator import Simulator, jsonable
from tests.helpers import fixed_repair, graph


def read(path):
    return json.loads((ROOT/path).read_text())


def digest(path):
    return hashlib.sha256((ROOT/path).read_bytes()).hexdigest()


def write(path,data):
    p = ROOT/path
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(jsonable(data),ensure_ascii=False,indent=2,allow_nan=False)+"\n")


def example(name,w,p,plan,f,queues,expected):
    reference = Simulator(w,p,plan).run()
    run = Simulator(w,p,plan,failure=f,repair=fixed_repair(queues)).run()
    independent = audit_result(run,w,p,expected_failure=f,reference=reference)
    metrics = paired_metrics(run,reference,w)
    for key,value in expected.items():
        observed = metrics.get(key,getattr(run,key,None))
        if value is None:
            assert observed is None,(name,key)
        else:
            assert abs(observed-value)<=1e-9,(name,key,observed,value)
    path = f"reports/p1/examples/{name}.json"
    write(path,{"purpose":"hand-calculated correctness fixture; not a research method comparison",
                "input":{"workload":w,"platform":p,"initial_plan":plan,"failure":f,"repair_queues":queues},
                "expected":expected,"reference":reference,"result":run,"metrics":metrics,
                "independent_reconstruction":independent})
    return {"id":name,"path":path,"events_checked":independent["events_checked"],"trace_sha256":run.trace_hash}


def main():
    if (ROOT/"archive/p1_20261025/snapshot_manifest.json").exists():
        print("P1 is archived. Use archive/p1_20261025/scripts/validate_p1.py in that snapshot, or the current P2 entry point.")
        return 2
    report_dir = ROOT/"reports/p1"
    report_dir.mkdir(parents=True,exist_ok=True)
    cmd = [sys.executable,"-m","pytest","-q","--junitxml=reports/p1/pytest_results.xml"]
    process = subprocess.run(cmd,cwd=ROOT,text=True,capture_output=True)
    (report_dir/"pytest_stdout.log").write_text(process.stdout+process.stderr)
    print(process.stdout, end="")
    if process.returncode:
        print(process.stderr,end="")
        return process.returncode
    test_suites = ET.parse(report_dir/"pytest_results.xml").getroot().findall("testsuite")
    tests = sum(int(s.get("tests",0)) for s in test_suites)
    failures = sum(int(s.get("failures",0))+int(s.get("errors",0)) for s in test_suites)
    skipped = sum(int(s.get("skipped",0)) for s in test_suites)
    elapsed = sum(float(s.get("time",0)) for s in test_suites)
    cases = read("reports/p1/systematic_results.json")
    assert cases["session_exit_code"]==0 and cases["inputs_unchanged_during_tests"]
    assert cases["counts"]=={"exhaustive_fixed_plan":1024,"synthetic_failure":60}
    assert cases["pytest_collected"]==tests and failures==skipped==0
    assert all(digest(p)==sha for p,sha in cases["source_hashes"].items()),"test input changed after execution"
    protocol = read("configs/protocol_v1.json")
    assert digest("docs/protocol_v1.md")==protocol["protocol_sha256"]
    assert digest("data/manifest_v1.json")==protocol["data_manifest_sha256"]

    corpus = Corpus(ROOT)
    adapter_checks = []
    for record in corpus.manifest["records"]:
        w = corpus.load(record["id"],"adapter_check")
        adapter_checks.append({"record_id":record["id"],"tasks":len(w.tasks),"files":len(w.files),
                               "pbar":w.pbar,"split":record["split"],"raw_sha256":record["raw_sha256"],
                               "executed":False})
    write("reports/p1/adapter_checks.json",{"records":adapter_checks,"verified":len(adapter_checks),"real_execution_runs":0})
    examples = [
        example("interrupted_attempt",graph({"a":10}),Platform((1,10),1),Plan((("a",),())),Failure(1,0),((),("a",)),
                {"makespan":2,"wasted_cpu_seconds":1,"cpu_seconds":2,"cdi":None}),
        example("cancel_and_refetch",graph({"a":1,"b":1},[("a","b",10)]),Platform((1,1,1),1),
                Plan((("a",),("b",),())),Failure(2,1),((),(),("b",)),{"makespan":13,"transfer_bytes":11,"cdi":None}),
        example("protected_delay",graph({"a":4,"b":1,"c":2},workflows={"a":"w0","b":"w1","c":"w1"}),
                Platform((1,1),1),Plan((("a",),("b","c"))),Failure(0.5,0),((),("b","a","c")),
                {"awct":6,"makespan":7,"cdi":12/7,"churn":0}),
    ]
    write("reports/p1/examples/index.json",examples)
    synthetic = [c for c in cases["cases"] if c["kind"]=="synthetic_failure"]
    max_error = max(c["oracle_max_finish_error"] for c in cases["cases"] if c["kind"]=="exhaustive_fixed_plan")
    event_count = sum(c["events_checked"] for c in cases["cases"])
    p0_tests = sum(t.get("classname","").startswith("scripts.test_p0_data_validation") for s in test_suites for t in s.findall("testcase"))
    assert p0_tests==17
    summary = {"stage":"P1","status":"PASS","executed_at":datetime.now(timezone.utc).isoformat(),
               "python":host_platform.python_version(),"platform":host_platform.platform(),
               "dependencies":{p:importlib.metadata.version(p) for p in ["numpy","networkx","jsonschema","pytest"]},
               "test_command":"python -m pytest -q --junitxml=reports/p1/pytest_results.xml",
               "tests":{"total":tests,"passed":tests-failures-skipped,"failed_or_errored":failures,"skipped":skipped,
                        "p0_regression":p0_tests,"p1":tests-p0_tests,"suite_wall_seconds":elapsed},
               "systematic_cases":cases["counts"],"systematic_event_records_checked":event_count,
               "exhaustive_max_finish_error":max_error,"synthetic_F_empty":sum(not c["effective_failure"] for c in synthetic),
               "synthetic_P_empty":sum(c["protected_count"]==0 for c in synthetic),
               "adapter_verified":len(adapter_checks),"real_corpus_execution_runs":0,"formal_experiment_runs":0,
               "hand_calculated_examples":len(examples),"protocol_sha256":protocol["protocol_sha256"],
               "manifest_sha256":protocol["data_manifest_sha256"],"code_and_test_hashes":cases["source_hashes"],
               "scope":"event executor, input adapter, independent replay and paired metrics; no scheduling-policy performance claims",
               "gates":{"P1":"PASS","G1":"PENDING_P2_BASELINES","G2":"NOT_READY"}}
    write("reports/p1/acceptance_summary.json",summary)
    write("project_state.json",{
        "updated_at":summary["executed_at"],"current_stage":"P1_COMPLETE","next_stage":"P2",
        "authoritative_design":"docs/protocol_v1.md","latest_acceptance_report":"reports/p1/P1_阶段验收报告.md",
        "p1_executor_implemented":True,"p1_adapter_implemented":True,"p1_independent_auditor_implemented":True,
        "initial_HEFT_implemented":False,"B0_B1_B2_implemented":False,"SAIL_implemented":False,
        "selected_lambda":None,"selected_mu":None,"formal_experiment_frozen":False,"formal_runs_completed":0,
        "P1_passed":True,"G1_passed":False,"G2_passed":False,
        "protocol_config_is_design_snapshot":"configs/protocol_v1.json retains P0 design state; this file records implementation progress",
        "remaining_source_items":["DaTR fulltext","ReadyFS manuscript","FSCD fulltext"]})

    report = f"""# P1 阶段验收报告

验收日期：2026-10-25。实际执行时间：{summary['executed_at']}。

**P1通过，可以进入P2的Initial HEFT与共同基线实现。** 事件模拟器、数据适配器、离线配对指标与独立日志校验器均已实现。完整测试为{tests}通过、0失败、0跳过，其中P1为{tests-p0_tests}项，P0回归为{p0_tests}项。

## 1. 实现产物与用途

| 模块 | 已实现内容 | 文件 |
| --- | --- | --- |
| 公共数据与计划契约 | 不可变任务、文件、平台、队列计划、观察快照、F/Q/P与修复约束 | `sail/model.py` |
| 数据适配 | 原始及解析hash校验、任务/文件命名空间、每工作流均值归一化、测试Mix身份、独立合成开发/验证生成器 | `sail/data.py` |
| 事件执行 | CPU与输入准备、严格队首执行、永久故障、重试、持久化读取、迁移取消、控制延迟、过期事件失效 | `sail/simulator.py` |
| 离线评价 | AWCT、makespan、固定P上的CDI、Churn、同故障有符号保护延迟、工作流完成时间比 | `sail/metrics.py` |
| 独立日志校验 | 从输入与日志重建任务、队列、attempt、输入字节和故障集合；复算指标并拒绝篡改记录 | `sail/audit.py` |

公共调度入口只接收不可变Snapshot和FailureContext，包含预计工作量、已完成/已运行观测和输入准备进度。真实工作量与未来完成事件保存在执行器私有状态。未来扰动不同但当前观测相同的两次运行，给策略的快照与决策完全一致。

## 2. 实际验证证据

| 验证层 | 实际覆盖 | 结果 |
| --- | --- | --- |
| 手算与事件边界 | 链、汇聚、串行输入、准备与CPU重叠、无回填、完成/故障同刻、故障为0时刻 | 通过 |
| 故障与数据 | 完成输出持久化、源节点失效继续读取、健康已准备输入保留、中断从头重试、旧CPU/输入事件失效 | 通过 |
| 修复约束 | F必须包含、H只能含Q、健康运行任务固定、H外节点和相对队列顺序固定、增强图无环 | 通过 |
| 指标与信息隔离 | P固定、P空集为NA、共同Q分母、强制迁移不计Churn、有符号延迟、单位变化不改变CDI | 通过 |
| 适配器 | 20/20真实记录经hash核对后适配；重复日志/命名空间与规模留出保留 | 通过；真实执行运行数0 |
| 小图系统枚举 | 固定拓扑编号下64种四任务DAG边集×16种双节点分配，合计1,024组 | 与独立解析递推的任务开始/完成时间一致；最大完成时间差{max_error:g} |
| 合成故障验证 | 开发种子10000–10009×3 Mix×4/8节点，合计60场景 | 无故障解析对照、故障日志复算、故障前前缀一致、重复轨迹hash一致 |
| 日志反例 | 提前开始、错误字节、未知任务、重复/缺失提交、错误AWCT、篡改P/控制延迟、伪造过期事件 | 均被独立校验器拒绝 |

系统性验证共完成1,084组检查，独立核验{event_count:,}条事件记录。60个合成故障场景中F为空{summary['synthetic_F_empty']}个、P为空{summary['synthetic_P_empty']}个；全部保留。系统性小图枚举覆盖固定编号下的全部DAG边子集和节点分配；未穷举所有资源队列排列及故障时刻。

独立解析对照使用逻辑依赖与队列前序的递推公式，未调用事件执行器。日志校验使用单独的状态重建与NetworkX无环检查，未调用模拟器状态转移或生产计划校验函数。对AWCT、makespan、Churn、计算损失、传输字节和开始/完成时刻进行交叉核对，CDI从匹配无故障日志另行计算。

## 3. 可审阅的手算日志

三组示例保存输入、初始队列、故障、修复队列、全部事件、配对参考、指标及独立重建结果：

- `examples/interrupted_attempt.json`：原任务在t=1中断，较快健康节点重试后t=2提交；旧t=10完成事件被忽略，makespan仍为2。
- `examples/cancel_and_refetch.json`：已经传输1字节后目标节点故障，新目标重新取10字节，总计11字节，任务t=13完成。
- `examples/protected_delay.json`：保护任务开始时间从1变为5，pbar=7/3，因此CDI=12/7；AWCT=6，强制迁移不计Churn。

这些是执行正确性见证，使用人工指定队列，没有用来比较SAIL性能。

## 4. 对protocol_v1的实现解释

协议原文hash保持 `{protocol['protocol_sha256']}`，数据manifest hash保持 `{protocol['data_manifest_sha256']}`。本阶段没有修改研究假设、测试划分、指标、随机种子或参数选择规则。

1. 同时事件依次处理CPU完成、输入完成、节点故障、计划应用，再启动输入准备与CPU；同刻完成先提交。
2. 输入仅在所有逻辑父任务完成后准备；同任务远端文件按file ID串行，跨任务不争带宽；完成输出即时持久化。
3. 控制延迟只暂停新的CPU派发；输入准备按既有计划正常进行，计划应用时保留健康目标上的实际进度，换目标则取消/重读。这是对协议“暂停新的CPU派发”的直接落实。
4. 过期事件会排空并记录，因此最后一条日志时间可能晚于所有任务完成；makespan从有效完成记录计算。
5. F为空时仍保留故障与策略回调，是否重排交给策略；不重抽故障节点。该口径遵循定稿协议第7节。
6. 本阶段定义修复计划验证契约，H0/H1/H2构造、候选评分和预测候选回放仍按后续阶段实施。

## 5. 阶段状态与下一步

| 条目 | 状态 |
| --- | --- |
| P1-01 环境与适配器 | 完成；Python {summary['python']}，依赖固定于requirements-p1.txt |
| P1-02 资源与事件内核 | 完成 |
| P1-03 通信、持久化与无故障回放 | 完成 |
| P1-04 离线指标与独立日志校验 | 完成 |
| P1-05 正确性和未来信息隔离 | 完成 |
| G1 仿真与baseline共同验收 | 等待P2；不能由P1单独宣布通过 |
| G2 正式实验冻结 | 尚未到达 |

实际测试套件耗时约{elapsed:.2f}秒，该数只描述本机本次验证，不作为调度器性能或正式实验总时长估计。真实留出数据只经过适配，没有运行方法比较；λ/μ尚未选择，正式运行数仍为0。当前工程状态见根目录 `project_state.json`；`configs/protocol_v1.json`保留为设计快照。

下一阶段实现统一Initial HEFT及B0/B1/B2，接入本阶段的计划验证和独立事件核对；随后进行G1。DaTR等全文来源余项仍在P2处理，P1没有将其提升为已完成复现。

## 6. 复算与证据索引

从项目根目录、已安装requirements-p1.txt的Python3.12环境运行：

```sh
python scripts/validate_p1.py
```

该命令执行全套测试、20份数据适配检查、三组手算示例，并重建本报告。只运行测试可使用 `python -m pytest -q`。代码、协议、配置与测试输入的SHA-256在测试开始时记录，结束时核对未变化；完整测试输入hash见 `acceptance_summary.json`。

原始证据：`pytest_stdout.log`、`pytest_results.xml`、`systematic_results.json`、`adapter_checks.json`、`examples/`；主要汇总：`acceptance_summary.json`；文件完整性清单：`artifact_manifest.json`。P0材料保留在相邻目录，不覆盖历史验收结果。
"""
    (report_dir/"P1_阶段验收报告.md").write_text(report)
    paths = sorted([p for p in report_dir.rglob("*") if p.is_file() and p.name not in {"artifact_manifest.json","bundle_checks.json"}]+
                   [ROOT/p for p in cases["source_hashes"]]+[ROOT/"project_state.json"])
    write("reports/p1/artifact_manifest.json",{"created_at":summary["executed_at"],"stage":"P1",
          "records":[{"path":str(p.relative_to(ROOT)),"sha256":hashlib.sha256(p.read_bytes()).hexdigest(),"bytes":p.stat().st_size} for p in paths]})
    print(json.dumps({"P1":"PASS","tests":tests,"systematic_cases":cases["counts"],"events_checked":event_count,
                      "report":"reports/p1/P1_阶段验收报告.md","formal_runs_completed":0},ensure_ascii=False))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
