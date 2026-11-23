"""Run P2 plus regressions, build reviewable examples, and issue the G1 report."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from sail.audit import audit_result
from sail.metrics import paired_metrics
from sail.model import Failure,Plan,Platform
from sail.scheduling import Baseline,initial_heft
from sail.simulator import Simulator,content_hash,jsonable
from tests.helpers import graph


def read(path): return json.loads((ROOT/path).read_text())
def sha(path): return hashlib.sha256((ROOT/path).read_bytes()).hexdigest()


def write(path,data):
    p=ROOT/path;p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(jsonable(data),ensure_ascii=False,indent=2,allow_nan=False)+"\n")


def create_examples():
    examples=[]
    w,p=graph({"a":10,"b":1,"c":12,"d":1},[("a","b",3)]),Platform((1,2),1)
    schedule=initial_heft(w,p)
    run=Simulator(w,p,schedule.plan).run()
    audit=audit_result(run,w,p)
    assert schedule.plan==Plan((("d","b"),("a","c"))) and run.makespan==11
    path="reports/p2/examples/initial_gap_insertion.json"
    write(path,{"purpose":"hand-calculated initial rank and gap-insertion witness",
                "workload":w,"platform":p,"schedule":schedule,"actual_execution":run,"independent_reconstruction":audit,
                "expected":{"order":["a","c","b","d"],"queues":[["d","b"],["a","c"]],"makespan":11}})
    examples.append({"id":"initial_gap_insertion","path":path})
    cases=[("three_scopes",graph({"a":4,"b":1,"c":1,"r":8,"e":2},[("a","b",1),("b","c",1)]),
            Platform((1,1,1),1),Plan((("a",),("b","c"),("r","e"))),Failure(1,0)),
           ("input_progress",graph({"a":1,"b":1},[("a","b",10)]),
            Platform((1,1,1),1),Plan((("a",),("b",),())),Failure(2,2))]
    for name,w,p,plan,f in cases:
        reference=Simulator(w,p,plan).run()
        runs,policies={},{}
        for label in ("B0","B1","B2"):
            b=Baseline(label)
            runs[label]=Simulator(w,p,plan,failure=f,repair=b).run();policies[label]=b
        assert runs["B0"].context==runs["B1"].context==runs["B2"].context
        rows={}
        for label,b in policies.items():
            audit=audit_result(runs[label],w,p,expected_failure=f,reference=reference)
            rows[label]={"scope":b.last_schedule.scope,"snapshot":b.last_snapshot,"schedule":b.last_schedule,
                         "actual_execution":runs[label],"metrics":paired_metrics(runs[label],reference,w,same_fault_b0=runs["B0"]),
                         "independent_reconstruction":audit}
        if name=="three_scopes":
            assert [sorted(b.last_schedule.scope) for b in policies.values()]==[["a"],["a","b","c"],["a","b","c","e"]]
        else:
            assert dict(runs["B0"].starts)["b"]==11 and dict(runs["B2"].starts)["b"]==2
        path=f"reports/p2/examples/{name}.json"
        write(path,{"purpose":"scope/communication correctness fixture, not research performance evidence",
                    "workload":w,"platform":p,"initial_plan":plan,"failure":f,"reference":reference,"baselines":rows})
        examples.append({"id":name,"path":path})
    write("reports/p2/examples/index.json",examples)
    return examples


def main():
    if (ROOT/"archive/p2_20261025/snapshot_manifest.json").exists():
        print("P2/G1 is archived; use its snapshot for historical reproduction or the current P3 entry point.")
        return 2
    folder=ROOT/"reports/p2";folder.mkdir(parents=True,exist_ok=True)
    cmd=[sys.executable,"-m","pytest","-q","--acceptance-stage=P2","--junitxml=reports/p2/pytest_results.xml"]
    process=subprocess.run(cmd,cwd=ROOT,text=True,capture_output=True)
    (folder/"pytest_stdout.log").write_text(process.stdout+process.stderr)
    print(process.stdout,end="")
    if process.returncode: print(process.stderr,end="");return process.returncode
    suites=ET.parse(folder/"pytest_results.xml").getroot().findall("testsuite")
    tests=sum(int(s.get("tests",0)) for s in suites)
    failed=sum(int(s.get("failures",0))+int(s.get("errors",0)) for s in suites)
    skipped=sum(int(s.get("skipped",0)) for s in suites)
    elapsed=sum(float(s.get("time",0)) for s in suites)
    new_tests=sum("test_p2_" in t.get("classname","") for s in suites for t in s.findall("testcase"))
    cases=read("reports/p2/systematic_results.json")
    expected={"exhaustive_fixed_plan":1024,"synthetic_failure":60,"p2_initial_enumeration":192,
              "p2_small_fault_enumeration":256,"p2_development_baselines":72}
    assert cases["session_exit_code"]==0 and cases["inputs_unchanged_during_tests"] and cases["counts"]==expected
    assert cases["pytest_collected"]==tests and tests==577 and new_tests==345 and failed==skipped==0
    assert all(sha(p)==digest for p,digest in cases["source_hashes"].items())
    cfg=read("configs/protocol_v1.json")
    assert sha("docs/protocol_v1.md")==cfg["protocol_sha256"]
    assert sha("data/manifest_v1.json")==cfg["data_manifest_sha256"]
    archive=read("archive/p1_20261025/snapshot_manifest.json")
    assert all(sha("archive/p1_20261025/"+r["path"])==r["sha256"] for r in archive["records"])
    # Run the unchanged P1 handoff checker against its archived code/state, not live P2 flags.
    old=subprocess.run([sys.executable,str(ROOT/"archive/p1_20261025/scripts/check_p1_bundle.py")],cwd=ROOT,text=True,capture_output=True)
    (folder/"archived_p1_check.log").write_text(old.stdout+old.stderr)
    assert old.returncode==0
    examples=create_examples()
    new_cases=[r for r in cases["cases"] if r["kind"].startswith("p2_")]
    dev=[r for r in new_cases if r["kind"]=="p2_development_baselines"]
    summary={"stage":"P2","status":"PASS","G1":"PASS","executed_at":datetime.now(timezone.utc).isoformat(),
             "python":platform.python_version(),"dependencies":{p:importlib.metadata.version(p) for p in ["numpy","networkx","jsonschema","pytest"]},
             "tests":{"passed":tests,"p2_new":new_tests,"p0_p1_regression":tests-new_tests,"failed":failed,"skipped":skipped,"suite_wall_seconds":elapsed},
             "case_counts":cases["counts"],"P2_cases":len(new_cases),"P2_baseline_executions":sum(r.get("baseline_runs",0) for r in new_cases),
             "P2_event_records_checked":sum(r["events_checked"] for r in new_cases),
             "max_forecast_vs_public_oracle_error":max(r["max_finish_error"] for r in new_cases),
             "development_F_empty":sum(r["F_empty"] for r in dev),"development_P_empty":sum(r["P_empty"] for r in dev),
             "protocol_sha256":cfg["protocol_sha256"],"manifest_sha256":cfg["data_manifest_sha256"],
             "code_and_test_hashes":cases["source_hashes"],"P1_snapshot_files":archive["files"],"P1_archived_check":"PASS",
             "kernel":"protocol_v1_HEFT_EFT","baseline_scopes":{"B0":"F","B1":"F union (Desc(F) intersect Q)","B2":"Q"},
             "faithful_DaTR_replication":False,"source_assessment":"docs/P2_共同内核与基线说明.md",
             "formal_experiment_runs":0,"real_holdout_scheduling_runs":0,"examples":examples,
             "SAIL_implemented":False,"G2":"NOT_READY","selected_lambda":None,"selected_mu":None}
    write("reports/p2/acceptance_summary.json",summary)
    state=read("project_state.json")
    state.update({"updated_at":summary["executed_at"],"current_stage":"P2_G1_COMPLETE","next_stage":"P3",
                  "latest_acceptance_report":"reports/p2/P2_G1_阶段验收报告.md","initial_HEFT_implemented":True,
                  "B0_B1_B2_implemented":True,"P2_passed":True,"G1_passed":True,"SAIL_implemented":False,
                  "G2_passed":False,"formal_experiment_frozen":False,"formal_runs_completed":0,
                  "selected_lambda":None,"selected_mu":None,"P1_snapshot":"archive/p1_20261025"})
    write("project_state.json",state)
    budget=read("planning/experiment_budget_plan.json")
    budget.update({"P2_G1_status":"PASS","P2_acceptance_report":"reports/p2/P2_G1_阶段验收报告.md",
                   "initial_heft_implemented":True,"B0_B1_B2_implemented":True,"SAIL_implemented":False,
                   "implementation_flag_scope":"complete eight-method research suite; SAIL and ablations pending"})
    write("planning/experiment_budget_plan.json",budget)
    report=f"""# P2 / G1 阶段验收报告

执行时间：{summary['executed_at']}。依据：定稿protocol_v1；实现版本0.2.0。

**P2完成，G1通过，可以进入P3的SAIL候选范围与选择机制实现。** Initial HEFT、B0/B1/B2已接入共同排程内核、P1事件执行和独立日志校验。正式实验仍为0次，G2尚未到达。

## 1. 交付与协议落实

| 项目 | 已实现行为 | 证据 |
| --- | --- | --- |
| Initial HEFT | 原DAG upward rank、确定性工作流/任务并列、全健康节点EFT空隙插入 | `sail/scheduling.py`、手算日志 |
| B0 | H=F，H外分配与相对队列顺序固定 | 共同kernel与独立作用域核对 |
| B1 | H=F∪(Desc(F)∩Q)，只沿逻辑DAG闭包 | 独立NetworkX后代集合与实际决策一致 |
| B2 | H=Q，Done与健康Running固定 | 共同kernel、资源预约和独立事件校验 |
| 预计回放 | 公开快照初始化P1事件内核，保留输入进度和健康Running预计剩余时间 | `sail/forecast.py`、独立解析对照 |
| 共同条件 | 共享初始计划、真实工作量、故障节点/时刻及F/Q/P | 跨方法故障前前缀、上下文与既有损失一致性检查 |

三个基线只在传给`schedule_scope`的集合上不同，没有各写一套启发式。EFT按预计完成、预计开始、节点ID、插入位置依次取最小值；rank在原逻辑DAG上计算，H外顺序边不加入通信或rank。

## 2. 实际测试结果

| 层次 | 覆盖 | 结果 |
| --- | --- | --- |
| 完整测试套件 | P2新增{new_tests}项，加P0/P1回归{tests-new_tests}项 | **{tests}通过，0失败，0跳过** |
| 初始排程枚举 | 64个四任务DAG边集×3个平台，共192组 | 每步EFT与独立全节点/区间边界枚举一致；完成时间通过解析与事件双核对 |
| 小图故障枚举 | 64边集×2故障节点×2故障比例，共256个场景×3基线 | 768次基线执行通过全部空隙选择、作用域、预测/实际和日志核验 |
| 合成开发网格 | 3开发种子×3 Mix×2节点数×2 CCR×2故障比例，共72个场景×3基线 | 216次基线执行通过共同条件、日志、预计递推和确定性验证 |
| 系统性P2记录 | 共{len(new_cases)}组、{summary['P2_baseline_executions']}次基线执行 | 计入{summary['P2_event_records_checked']:,}条已核验事件；重复核验的参考日志不重复累计 |
| 预计模型内部一致性 | 预计事件回放vs基于公开快照的独立解析对照 | 记录的最大完成时间差{summary['max_forecast_vs_public_oracle_error']:g} |
| P1历史证据 | {archive['files']}个文件封存；原P1交付校验在封存目录运行 | 通过，保留原232项测试对应的代码与状态 |

预计模型内部差值为0表示两种预计计算路径一致，不表示含CV扰动的实际运行时间预测误差为0。小图层在预计=实际条件下另核对了真实完成记录；合成开发层保留CV=0/0.1/0.3和控制延迟，并以独立日志核对实际结果。

72个开发场景中F为空{summary['development_F_empty']}个，P为空{summary['development_P_empty']}个，均完整保留。P为空CDI为NA；F为空时B0/B1保留分配与队列，B2仍可全局重排。没有按方法效果重抽节点、筛选场景或更换种子。

## 3. 关键正确性见证

- **真正的空隙插入**：手算rank为a=11.25、c=9、b=d=0.75，规划顺序a/c/b/d；最终队列为节点0的d/b、节点1的a/c。后规划的d插入b之前的空闲区间，而非追加队尾。
- **EFT并列顺序**：两节点预计结束均为5时，选预计开始为2的节点，而不是开始为4但ID较小的节点。
- **固定集合**：健康Running保持节点与原执行区间；H外任务节点和相对队列顺序不变；H外依赖/队列只传播开始时刻。
- **输入准备**：已在旧目标收到1字节的任务，B0保留进度预计t=11就绪；改变目标的候选按新位置重新准备。源节点失效后不能把持久化读取误计为本地免费。
- **控制延迟**：在τ+δ的新快照重算，期间完成的健康任务视为Done；原F/Q/P不变。
- **信息隔离**：三基线在“观测前缀相同、真实未来时长不同”的测试中产生相同Schedule及Forecast；Running超出估计时使用协议规定的正剩余下限。

三组完整示例在`examples/initial_gap_insertion.json`、`examples/three_scopes.json`、`examples/input_progress.json`，包含输入、候选选择、预计结果、真实事件与独立重建。后两组为人工指定共同初始队列的语义夹具；系统性开发网格才使用真实Initial HEFT输出。示例不作为论文性能主张。

## 4. P2-03近邻适配决策

详见`docs/P2_共同内核与基线说明.md`。本阶段完成协议明确指定的共同核控制基线：B0不称FTDR复现，B1不称DaTR复现，B2不称全局最优。HEFT的通信/执行适配已经明示；Last-K、Repair、ReadyFS和FSCD与当前触发或资源模型的差异沿用P0分级证据。

本轮没有新增取得DaTR、ReadyFS或FSCD全文。精确原版复现和绝对首创性仍有来源边界；不把未定义的原算法变体临时加入G1。后续新全文若改变最近邻判断，应在G2和正式测试前更新对照与协议版本。G1通过仅覆盖当前协议下的执行正确性、公平共同条件和基线可用性。

## 5. G1验收结论

| 条件 | 判断 |
| --- | --- |
| P1执行与独立校验回归通过 | 通过 |
| Initial HEFT、rank、EFT、并列与插入规则可复核 | 通过 |
| B0/B1/B2共享内核、仅范围不同 | 通过 |
| 同故障前轨迹、相同F/Q/P和真实随机场 | 通过 |
| 健康运行固定、H外约束和增强图无环 | 通过 |
| 正式留出数据独立、未用于效果选择 | 保持；真实留出调度运行数0 |
| 代码/测试输入及原协议hash可追溯 | 通过 |

G1结论：**PASS**。下一阶段为P3：H0/H1/H2候选、去重、预计稳定性/迁移评分、NoStability/NoChurn/固定范围、开发/验证参数选择与profiling。λ/μ保持null，SAIL尚未实现，正式实验未冻结、未运行。

完整套件本次约{elapsed:.2f}秒，该数不是正式实验吞吐估计，也不用于选择确认性样本量。现有名义研究预算保持原计划，P3仍需完整profiling后才能冻结种子数。

## 6. 复算与产物

在项目根目录、Python{summary['python']}及requirements-p2.txt固定依赖环境下运行：

```sh
python scripts/validate_p2.py
python scripts/check_p2_bundle.py
```

测试开始时记录代码、测试、实现说明及协议输入hash，结束时校验未变化。主汇总为`acceptance_summary.json`，原始测试为`pytest_results.xml`与`pytest_stdout.log`，逐场景记录为`systematic_results.json`，文件完整性为`artifact_manifest.json`。

协议hash：`{cfg['protocol_sha256']}`；真实数据manifest hash：`{cfg['data_manifest_sha256']}`，均保持P0定稿值。当前工程状态见根目录`project_state.json`；P1旧代码与数据在`archive/p1_20261025/`，复算历史阶段时先复制封存内容到独立目录，避免覆盖原证据。
"""
    (folder/"P2_G1_阶段验收报告.md").write_text(report)
    paths=sorted([p for p in folder.rglob("*") if p.is_file() and p.name not in {"artifact_manifest.json","bundle_checks.json"}]+
                 [ROOT/p for p in cases["source_hashes"]]+[ROOT/"project_state.json",ROOT/"planning/experiment_budget_plan.json",ROOT/"archive/p1_20261025/snapshot_manifest.json"])
    write("reports/p2/artifact_manifest.json",{"stage":"P2/G1","created_at":summary["executed_at"],
          "records":[{"path":str(p.relative_to(ROOT)),"sha256":hashlib.sha256(p.read_bytes()).hexdigest(),"bytes":p.stat().st_size} for p in paths]})
    print(json.dumps({"P2":"PASS","G1":"PASS","tests":tests,"P2_cases":len(new_cases),"baseline_executions":summary["P2_baseline_executions"],
                      "report":"reports/p2/P2_G1_阶段验收报告.md","formal_runs":0},ensure_ascii=False))
    return 0


if __name__=="__main__": raise SystemExit(main())
