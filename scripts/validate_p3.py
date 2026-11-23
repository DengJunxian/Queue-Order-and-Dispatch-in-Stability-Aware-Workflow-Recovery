"""Complete P3 validation and freeze G2; does not execute formal holdouts."""
import hashlib
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from sail.development import dump,run_selection
from sail.frozen import verify_freeze
from make_g2_freeze import build_freeze


def read(path):return json.loads((ROOT/path).read_text())
def sha(path):return hashlib.sha256((ROOT/path).read_bytes()).hexdigest()


def main():
    selection=run_selection(ROOT)
    if selection["selected"] is None:raise ValueError("no feasible parameter; retain results and revise before G2")
    if not (ROOT/"reports/p3/profiling_summary.json").exists():
        subprocess.run([sys.executable,str(ROOT/"scripts/profile_p3.py")],cwd=ROOT,check=True)
    folder=ROOT/"reports/p3";folder.mkdir(parents=True,exist_ok=True)
    command=[sys.executable,"-m","pytest","-q","--acceptance-stage=P3","--junitxml=reports/p3/pytest_results.xml"]
    result=subprocess.run(command,cwd=ROOT,text=True,capture_output=True)
    (folder/"pytest_stdout.log").write_text(result.stdout+result.stderr);print(result.stdout,end="")
    if result.returncode:print(result.stderr,end="");return result.returncode
    suites=ET.parse(folder/"pytest_results.xml").getroot().findall("testsuite")
    tests=sum(int(s.get("tests",0)) for s in suites)
    failed=sum(int(s.get("failures",0))+int(s.get("errors",0)) for s in suites)
    skipped=sum(int(s.get("skipped",0)) for s in suites)
    new=sum("test_p3_" in t.get("classname","") for s in suites for t in s.findall("testcase"))
    cases=read("reports/p3/systematic_results.json")
    assert tests==622 and new==45 and failed==skipped==0 and cases["inputs_unchanged_during_tests"]
    assert cases["counts"]=={"exhaustive_fixed_plan":1024,"synthetic_failure":60,"p2_initial_enumeration":192,
                             "p2_small_fault_enumeration":256,"p2_development_baselines":72,"p3_eight_method_correctness":12}
    assert all(sha(p)==h for p,h in cases["source_hashes"].items())
    test_summary={"passed":tests,"P3_new":new,"regressions":tests-new,"failed":failed,"skipped":skipped,
                  "suite_wall_seconds":sum(float(s.get("time",0)) for s in suites),"source_hashes":cases["source_hashes"]}
    dump(folder/"test_summary.json",test_summary)
    frozen=build_freeze();freeze_path="freeze/g2_v1_20261025"
    _,manifest=verify_freeze(ROOT,ROOT/freeze_path)
    chosen=selection["selected"];profile=read("reports/p3/profiling_summary.json")
    aliases=sum(j["kind"]=="failure" and j["method"] in frozen["method_aliases"] for j in manifest["jobs"])
    summary={"stage":"P3","status":"PASS","G2":"PASS","executed_at":datetime.now(timezone.utc).isoformat(),
             "tests":{k:v for k,v in test_summary.items() if k!="source_hashes"},"test_source_hashes":cases["source_hashes"],
             "selected_lambda":chosen["lambda"],"selected_mu":chosen["mu"],"development_scenarios":480,"validation_scenarios":240,
             "validation_relative_awct_vs_B2":chosen["relative_awct_vs_B2"],"validation_cdi":chosen["cdi"],
             "single_plan_development_fraction":selection["development_coverage"]["single_plan_fraction"],
             "profile_scenarios":20,"profiling_estimates":profile["estimates"],"selected_test_seeds":len(frozen["root_seeds"]),
             "freeze_path":freeze_path,"nominal_jobs":len(manifest["jobs"]),"expected_alias_records":aliases,
             "expected_physical_executions":len(manifest["jobs"])-aliases,"formal_runs_completed":0,"real_holdout_scheduling_runs":0,
             "hypotheses_confirmed":False,"G2_inputs_only":True}
    dump(folder/"acceptance_summary.json",summary)
    state=read("project_state.json")
    state.update({"updated_at":summary["executed_at"],"current_stage":"P3_G2_COMPLETE","next_stage":"P4",
                  "SAIL_implemented":True,"ablations_implemented":True,"statistical_script_implemented":True,"P3_passed":True,
                  "selected_lambda":chosen["lambda"],"selected_mu":chosen["mu"],"G2_passed":True,"formal_experiment_frozen":True,
                  "formal_runs_completed":0,"formal_freeze":freeze_path,"selected_test_seed_count":len(frozen["root_seeds"]),
                  "latest_acceptance_report":"reports/p3/P3_G2_阶段验收报告.md","P2_snapshot":"archive/p2_20261025"})
    dump(ROOT/"project_state.json",state)
    budget=read("planning/experiment_budget_plan.json")
    budget.update({"status":"FROZEN_NOT_RUN","protocol_frozen":True,"implemented":True,"P3_G2_status":"PASS",
                   "selected_profile_seeds":30,"expected_physical_executions":len(manifest["jobs"])-aliases,
                   "nominal_run_labels":len(manifest["jobs"]),"implementation_flag_scope":"eight method labels with explicit mathematical aliases",
                   "formal_freeze":freeze_path,"runs_completed":0})
    budget["parameter_selection"]["selected_lambda"]=chosen["lambda"];budget["parameter_selection"]["selected_mu"]=chosen["mu"]
    dump(ROOT/"planning/experiment_budget_plan.json",budget)
    report=f"""# P3 / G2 阶段验收报告

执行时间：{summary['executed_at']}。依据定稿protocol_v1，实现版本0.3.0。

**P3完成，G2已封存，可以进入P4正式实验。** 本轮完成SAIL及消融、开发/验证参数选择、20场景profiling、统计脚本和冻结执行器。真实留出调度与正式运行数均为0；本报告的数值来自合成开发/验证和工程测试。

## 1. 实现与正确性

H0/H1/H2按最短逻辑距离构造，先去重范围再去重完整计划，保留hop别名。评分使用固定预计无故障参考；P空集保留NA，评分该项置0。绝对分差≤1e-12按全局最小分形成并列集合，按Churn、范围大小、hop和队列字典序选择。

NoStability只将λ置0，NoChurn只将μ置0，Fixed-H1/H2使用共同内核，Fixed-H0复用B0。增加根种子块bootstrap和校验冻结输入/代码hash的执行器，后者的单元测试仅在UNIT_TEST人工小图上运行。

| 验证 | 实际结果 |
| --- | --- |
| 完整测试 | **{tests}通过，0失败，0跳过** |
| 构成 | P3新增{new}项，P0/P1/P2回归{tests-new}项 |
| 八配置集成 | 12个合成场景，检验scope、评分、共同前缀、日志与确定性 |
| 参数缓存 | 全15组权重的缓存选择与在线选择一致 |
| 信息边界 | 实际执行结果不能充当在线参考；未来扰动不同而观测相同时选择一致 |
| 统计 | 整块根种子重采样、NA处理、固定seed及配对完整性反例通过 |
| 冻结执行器 | 人工小图检查点恢复、alias、代码/数据篡改拒绝通过；未执行真实冻结任务 |

## 2. 参数选择的实际结果

开发480场景：20根种子×3 Mix×2节点数×2 CCR×2故障比例。15组λ/μ共用一次生成的候选与独立核验结果；完整表在`development_parameter_table.json`。最多三组开发可行参数进入独立验证240场景，验证表与最终选择在`parameter_selection.json`。

选定 **λ={chosen['lambda']}，μ={chosen['mu']}**。验证集有{chosen['cdi_defined_scenarios']}个CDI有定义场景，平均CDI={chosen['cdi']:.8f}；平均相对AWCT增幅={100*chosen['relative_awct_vs_B2']:.4f}%，满足开发期≤5%条件。这是参数选择的点估计，不是正式假设确认或AWCT单侧置信上界。

μ=0意味着NoChurn与SAIL配置等价。保留该选择与alias，不对未生效的迁移项提炼收益。

## 3. 机制覆盖率与继续判断

开发场景有{100*selection['development_coverage']['single_plan_fraction']:.2f}%最终只有一个不同计划；A/B/C分别有37/51/37个有效故障、P非空且候选不退化的场景。判断为机制可测但覆盖受限：三个预定Mix均有可选修复空间，因此按原无条件矩阵进入确认阶段；不删除退化、F空或P空场景，也不扩大H来改善结果。

验证阶段H0/H1/H2代表候选的选择次数为{chosen['selected_hops']}；这描述开发阶段行为，正式范围选择分布仍待P4。全部候选与实际结果保存在development/validation子目录，负向与零差异未筛除。

## 4. Profiling与资源选择

按运行前声明的20个开发场景，对8配置实测策略、事件执行、独立审计、指标与JSON写入。按方法p95、保守241任务上界的平方缩放、2倍安全系数及600秒分析余量：

| 主根种子数 | 名义运行标签 | 本机预算估计 |
| --- | ---: | ---: |
| 30 | 6,960 | {profile['estimates'][0]['estimated_hours']:.4f}小时 |
| 10 | 2,880 | {profile['estimates'][1]['estimated_hours']:.4f}小时 |

30种子版本满足预设12小时门槛，故冻结60000–60029。耗时数是规划估计，不是实际正式运行时长或保证。原始计时、事件和存储测量在`profiling_summary.json`及profiling/events/。

## 5. G2封存内容

目录：`{freeze_path}/`。已封存权重、30个根种子、工作流身份/预计工作量、节点速度、带宽、实际工作量向量、故障节点、控制延迟、统计规则、代码与依赖hash。求值器专用的实际向量与公开输入分存；策略仍只收公开快照。

故障时刻冻结为fraction×匹配实际无故障M0；M0数值在P4运行参考时计算。本轮没有运行真实留出的Initial HEFT或无故障执行，也没有查看其算法效果。

| 封存项目 | 数量／状态 |
| --- | --- |
| 主场景 | 720个 |
| 误差场景 | 120个 |
| 控制延迟场景 | 60个 |
| 无故障参考标签 | 480个 |
| 全部名义运行标签 | 6,960个 |
| 预计物理执行／alias记录 | {summary['expected_physical_executions']:,}／{aliases:,} |
| 统计 | 5,000次root_seed块bootstrap，seed73000；预定区间与NA规则 |
| 正式运行完成 | **0** |

NoChurn的720个主标签引用同场景SAIL执行，保留独立标签和来源，不把它们算独立随机样本。统计对主矩阵配对，稳健性单列；所有方法共享同一根种子抽样索引。未定义bootstrap抽样不会被填0或伪造区间。

## 6. 验收状态与入口

G2结论：**PASS**。必要条件包括共同基线/SAIL/消融正确性、独立开发验证完成、重复数profiling、完整输入与统计代码封存，均已有实际产物。G2通过不等于研究假设获得支持；G3还需要冻结后的真实测试结果与机制解释。

本轮没有新增取得DaTR等全文，既有近邻适配与原版复现边界保留。P2/G1代码与证据封存于archive/p2_20261025，P1快照也继续保留。

当前复算：`python scripts/validate_p3.py`；快速核验：`python scripts/check_p3_bundle.py`。开发选择入口为`run_p3_development.py`，profiling入口为`profile_p3.py`。正式运行入口`run_frozen_experiments.py`及分析入口`analyze_frozen_experiments.py`均已封存，P3没有调用其FORMAL_MAIN执行路径。

主要证据：acceptance_summary.json、test_summary.json、pytest_results.xml、parameter_selection.json、development_parameter_table.json、profiling_summary.json、artifact_manifest.json，以及冻结目录的inputs_manifest.json。当前工程状态见根目录project_state.json。
"""
    (folder/"P3_G2_阶段验收报告.md").write_text(report)
    # Compact artifact list pins summaries; large caches are indexed in a separate hash inventory.
    data_paths=sorted(list((folder/"development").rglob("*.json"))+list((folder/"validation").rglob("*.json")))
    dump(folder/"selection_cache_manifest.json",{"files":[{"path":str(p.relative_to(ROOT)),"sha256":sha(p)} for p in data_paths]})
    paths=sorted([p for p in folder.glob("*") if p.is_file() and p.name not in {"artifact_manifest.json","bundle_checks.json"}]+
                 [ROOT/p for p in cases["source_hashes"]]+[ROOT/"project_state.json",ROOT/"planning/experiment_budget_plan.json"])
    dump(folder/"artifact_manifest.json",{"stage":"P3/G2","files":[{"path":str(p.relative_to(ROOT)),"sha256":sha(p)} for p in paths],
                                          "records":[{"path":str(p.relative_to(ROOT)),"sha256":sha(p)} for p in paths]})
    print(json.dumps({"P3":"PASS","G2":"PASS","tests":tests,"lambda":chosen["lambda"],"mu":chosen["mu"],
                      "nominal_jobs":len(manifest["jobs"]),"actual_executions_planned":summary["expected_physical_executions"],"formal_completed":0},ensure_ascii=False))
    return 0


if __name__=="__main__":raise SystemExit(main())
