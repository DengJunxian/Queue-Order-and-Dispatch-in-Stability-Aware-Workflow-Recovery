"""Generate a source-linked stage report and progress state from verified P4 outputs."""
import csv
import json
import statistics
import sys
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from sail.development import dump
from sail.frozen import verify_freeze


def main():
    cfg,_=verify_freeze(ROOT,ROOT/'freeze/g2_v1_20261025');folder=ROOT/'reports/p4'
    def read(path):return json.loads((ROOT/path).read_text())
    s=read('results/g2_v1_20261025/statistics.json');ext=read('reports/p4/extended_statistics.json')
    audit=read('reports/p4/audit_summary.json');check=read('reports/p4/bundle_check.json');diag=read('reports/p4/diagnostic_summary.json')
    clock=read('reports/p4/execution_wall_clock.json');pred=read('reports/p4/prediction_diagnostic.json')
    assert audit['status']==check['status']==diag['status']=='PASS'
    supported=s['CDI_interval_supports_improvement'] and s['AWCT_budget_supported'] and s['at_least_two_mix_directions']
    means={r['method']:r for r in ext['method_summary'] if r['variant']=='main'}
    processed=list(csv.DictReader((folder/'data/run_metrics.csv').open()))
    def effect(v,pct=False):
        k=100 if pct else 1;unit='%' if pct else '';ci=v['ci95']
        return f"{v['point']*k:+.4f}{unit} [{ci[0]*k:+.4f}, {ci[1]*k:+.4f}]" if ci else 'NA'
    def table(headers,rows):return '| '+' | '.join(headers)+' |\n| '+' | '.join(['---']*len(headers))+' |\n'+'\n'.join('| '+' | '.join(r)+' |' for r in rows)
    primaryrows=[['整体',effect(s['primary']['cdi']),effect(s['primary']['relative_awct'],True)]]
    primaryrows += [[f'Mix {m}',effect(s['mixes'][m]['cdi']),effect(s['mixes'][m]['relative_awct'],True)] for m in 'ABC']
    mechan=[['NoStability','稳定性评分的作用'],['NoChurn','μ=0，与SAIL相同的别名'],['B0','固定H0'],['Fixed_H1','固定H1'],['Fixed_H2','固定H2']]
    mechrows=[[m,meaning,effect(s['mechanisms'][m]['cdi']),effect(s['mechanisms'][m]['relative_awct'],True)] for m,meaning in mechan]
    robustnames={'main_subset':'匹配主实验子集：CV=0、δ=0','cv0.1':'工作量误差CV=0.1','cv0.3':'工作量误差CV=0.3','control_delay':'公共控制延迟δ=0.1 pbar'}
    robustrows=[[label,effect(ext['robustness'][name]['statistics']['cdi']),effect(ext['robustness'][name]['statistics']['relative_awct'],True)] for name,label in robustnames.items()]
    rawrows=[[m,f"{means[m]['mean_AWCT_seconds']:.4f}",f"{means[m]['mean_CDI']:.4f}",f"{means[m]['mean_Churn']:.4f}"] for m in ('B0','B1','B2','SAIL','NoStability','NoChurn','Fixed_H1','Fixed_H2')]
    timrows=[[r['method'],f"{r['p50_seconds']*1000:.2f}",f"{r['p95_seconds']*1000:.2f}"] for r in diag['timing_summary']]
    coverage=[[m,str(v['scenarios']),str(v['F_empty']),str(v['P_empty'])] for m,v in audit['coverage'].items()]
    desc=[r for r in processed if r['variant']=='main' and r['method']=='SAIL']
    signed=statistics.mean(float(r['same_fault_signed_delay']) for r in desc)
    protected=statistics.mean(float(r['protected_fraction']) for r in desc)
    report=f'''# P4 / G3 阶段验收报告

日期：2026-10-25。权威协议：[protocol_v1](../../docs/protocol_v1.md)；冻结包：[g2_v1_20261025](../../freeze/g2_v1_20261025/freeze.json)。

**P4正式实验、完整性核验和统计交付已完成；G3原定的继续投稿支持条件未通过。** SAIL相对B2的CDI差为+0.5835，95%区间[+0.5328,+0.6351]，三个Mix的方向均为正。AWCT平均配对相对增幅为+2.7671%，单侧95%上界为+3.0385%，满足预设5%研究容忍度。结果支持“稳定性评分在受限候选中有作用、可减少改派”，未支持“相对共同核全局重排B2降低保护任务延迟”的主张。

## 1. 执行范围与证据身份

使用开发/验证阶段选定的λ={cfg['selected_lambda']}、μ={cfg['selected_mu']}，30个根种子60000—60029。主轴为3个Mix×2节点数×2CCR×2故障时机；实际故障时刻严格按每个匹配无故障执行的0.3/0.6 makespan计算。故障节点保留冻结抽样，包括无影响故障。

| 任务组 | 故障场景 | 故障方法标签 | 匹配无故障参考 | 合计标签 |
| --- | --- | --- | --- | --- |
| 主实验与五项机制对照 | 720 | 5,760 | 360 | 6,120 |
| CV=0.1/0.3工作量误差 | 120 | 480 | 120 | 600 |
| 公共控制延迟 | 60 | 240 | 0，复用匹配主参考 | 240 |
| 合计 | 900 | 6,480 | 480 | 6,960 |

6,960个标签全部完成；6,240次物理执行、720条NoChurn→SAIL别名、失败记录0、缺失标签0、重复标签0。NoChurn因μ=0数学等价，引用SAIL事件文件，保留为别名；不构成独立运行、机制证据或计时样本。Fixed-H0直接对应B0。

原始主批次从{clock['started_at']}至{clock['finished_at']}（UTC），wall time {clock['wall_seconds']:.2f}秒，约{clock['wall_seconds']/60:.2f}分钟。这一数值只表示批次吞吐，排除本报告的复算、统计和诊断时间。正式名义预算不含开发、验证、耗时重复及103任务规模留出；本次未新增规模留出或其他扩展实验。

数据身份仍是19份真实核心工作流JSON形成的固定基准，随机变化来自平台、故障与工作量场。30根种子不能解释为30套相互独立的真实数据集。103任务规模留出保持未使用。真实轨迹来源与仿真资源条件在[data/manifest_v1.json](../../data/manifest_v1.json)中可追溯。

## 2. 完整性与独立正确性核验

核对全部冻结任务ID、结果状态与事件文件SHA-256；对6,240份物理执行日志独立重算{audit['persisted_event_records_recomputed']:,}条事件。复核CPU/输入事件、依赖、永久故障、重试、队列约束、AWCT、makespan、CDI、Churn及F/Q/P。900个故障场景内各方法的故障上下文一致，故障前严格早于τ的事件前缀与匹配无故障执行一致。

{table(['条件','故障场景','F空集','P空集/CDI NA'],coverage)}

主实验12个F空集场景全部保留；主实验有效故障比例708/720=98.33%。全部900场景P非空，因此主比较720对、各误差/延迟条件60对CDI均有定义。每项bootstrap的5,000次重采样也全部有定义。

另外实施1,120次确定性诊断回放：720次主SAIL候选诊断，加400次计时补充。全部运行结果与原正式日志逐项相等，核对817,119条回放事件。它们没有增加独立故障场景数或正式运行标签数。统计复核采用独立的向量化“先计算根种子均值再重采样”路径，核对44项指标的点估计、双侧区间和单侧上界，误差均小于1e-11；该等价路径在本次完整平衡网格、无NA条件下成立。

验收回执：[audit_summary.json](audit_summary.json)、[bundle_check.json](bundle_check.json)、[diagnostic_summary.json](diagnostic_summary.json)。原始B0同故障自身参考字段为NA，派生表将非空P上的B0自身延迟记为0；原始JSONL没有改写。

## 3. 主假设H1与G3判断

正式统计继续使用G2封存的`sail/statistics.py`及`analyze_frozen_experiments.py`：以root_seed整块重采样，所有Mix/资源条件/方法共享同一抽样根，5,000次、PCG64种子73000。先平均各Mix中的轴单元，再对Mix等权；区间是双侧percentile 95%，预算使用单侧95%上界。

CDI差定义为SAIL−对照，负值表示保护任务延迟改善。AWCT相对差先在每个配对场景计算SAIL/AWCT对照−1，再按协议汇总。

{table(['范围','CDI配对差 [95% CI]','AWCT配对相对差 [95% CI]'],primaryrows)}

| 冻结支持条件 | 实际结果 | 判定 |
| --- | --- | --- |
| 整体CDI区间上界<0 | +0.6351 | 未满足，方向相反 |
| 至少两个Mix的CDI点估计<0 | 0/3个Mix | 未满足 |
| AWCT相对差单侧95%上界≤5% | +3.0385% | 满足 |
| 消融/固定范围能解释具体机制 | 评分及固定范围对照有信息，但未克服B2差距 | 部分支持机制 |

**H1未获支持，G3继续按原主张投稿的门槛未通过。** 在节点4/8、CCR0.5/2、故障时机0.3/0.6的所有预定单轴分层里，SAIL−B2的CDI区间也都在0以上。完整分层数值见[data/paired_effects.csv](data/paired_effects.csv)，未用分层替换主比较。

区间仅刻画固定真实基准在本协议模拟环境中的随机变动，不外推所有科学工作流或真实集群。5%是研究容忍度；结果没有建立业务SLA。

## 4. 机制假设H2/H3及零结果

{table(['对照','对应机制','CDI差 [95% CI]','AWCT相对差 [95% CI]'],mechrows)}

相对NoStability，稳定性项使CDI减少0.0611，代价是平均配对AWCT增加0.4592%。该证据支持H2在当前有限候选集中的作用。相对B0、固定H1和固定H2，SAIL的CDI均较低；与固定H2的AWCT相对差接近零，区间跨零，不能据此宣称严格等效或逐场景支配。这些比较支持H3的一部分适应价值，同时保留固定H2效率相近的结果。

NoChurn的差及区间均为0，原因是μ=0的完全等价。这里没有独立证据可识别Churn惩罚项的收益。所有五项机制比较完整展示，不报告p值，也未挑选有利的比较对象。

主实验的描述性均值如下；每方法均为720场景，CDI定义数720。AWCT均值之比与“配对相对增幅的平均”是不同统计量，不能互换。

{table(['方法','平均AWCT（秒）','平均CDI','平均Churn'],rawrows)}

SAIL的平均Churn为0.0521，B2为0.4546；这里的Churn是可选改派任务数除以全部Q任务数。该结果说明当前方案大幅减少改派，但保护任务启动延迟更高，两个指标不能互相替代。SAIL相对同故障B0的平均有符号保护延迟为{signed:+.4f}个pbar，主实验P/Q平均覆盖率为{protected*100:.2f}%。

## 5. 必做稳健性

每条件60场景、10根种子、3个Mix、CCR0.5/2、4节点、故障时机0.6。CV误差使用冻结的均值校正对数正态工作量向量；各方法共享任务随机场与匹配无故障参考。控制延迟为所有方法统一暂停新CPU派发0.1 pbar，运行中任务和已开始输入准备继续。

{table(['条件','CDI差 [95% CI]','AWCT相对差 [95% CI]'],robustrows)}

所有条件均保留正的CDI差及高于0的区间，未改变主结论。各行是该条件下SAIL与B2的配对比较；未把行间差异解释为误差水平的因果效应，也未把不同条件合并扩大样本量。控制延迟实验是公共等待敏感性，不等于将每个方法的实测wall time注入模拟器。

## 6. 候选范围与耗时诊断

720场景的规范化H0/H1/H2选择次数分别为223/177/320；一/二/三个不同候选计划的场景分别为39/83/598，非退化比例681/720=94.58%。SAIL与NoStability在229/720=31.81%的场景选择不同计划。开发阶段73.75%的场景只有一个计划，正式数据的候选结构明显不同；这一差别提示开发分布的代表性需要后续研究，不能直接当作已证明的性能原因。

主实验CV=0时，所选候选CDI预测与实际CDI的最大绝对差为{pred['max_abs_predicted_vs_actual_CDI_error']:.3g}。这排除了“当前主实验的所选计划CDI预测数值明显失准”这一解释。它仍未分解候选范围、目标权衡和初始队列结构各自对B2差距的贡献。

完整调度应用耗时覆盖快照、候选生成/去重、预计回放/评分、约束校验、输入失效处理及最终计划应用。20个结果检查前选定的场景，每物理方法3次，单进程测量；SAIL的首轮样本复用候选回放。机器为当前macOS arm64、Python3.12.14，其他主机活动未控制，数值用于本机描述性开销比较。

{table(['物理配置','p50（毫秒）','p95（毫秒）'],timrows)}

原批次的`policy_seconds`只含策略回调，另在派生表保留。它不替代本节的完整应用边界；NoChurn的派生计时为空值。p50/p95为420个原始重复中各方法60个样本的描述性分位数，不作为置信区间，计时重复不增加统计n。

## 7. 交付物与复现

- 原始结果：[`metrics.jsonl`](../../results/g2_v1_20261025/metrics.jsonl)、6,240份事件JSON、[`execution_summary.json`](../../results/g2_v1_20261025/execution_summary.json)。
- 封存主分析：[`statistics.json`](../../results/g2_v1_20261025/statistics.json)；分层与稳健性：[`extended_statistics.json`](extended_statistics.json)。
- 主表：[`run_metrics.csv`](data/run_metrics.csv)、[`paired_effects.csv`](data/paired_effects.csv)、[`method_summary.csv`](data/method_summary.csv)。
- 全部19,440条工作流级slowdown、分Mix/家族描述均值与6,480条尝试/重启/浪费CPU/通信字节/makespan：[data/](data/)。这些附加指标没有升为确认性主指标。
- 候选、计时原始重复和分位数：[candidate_diagnostics.csv](data/candidate_diagnostics.csv)、[full_application_timings.csv](data/full_application_timings.csv)、[timing_summary.csv](data/timing_summary.csv)。
- 四幅图均含PDF/SVG/300DPI不透明RGB PNG、完整源数据hash、图注及alt：[figures/figure_manifest.json](figures/figure_manifest.json)、[captions_and_alt.md](figures/captions_and_alt.md)。PDF固定180mm宽、嵌入字体且无Type3；已检查图例、坐标、区间、别名和标签。它们是研究阶段图件，后续论文版面与当届格式检查仍属于P5/P6。
- P3/G2历史证据另存于[archive/p3_20261025](../../archive/p3_20261025/snapshot_manifest.json)，1,795个文件hash验证。所有G2固定算法、参数、统计函数、协议和输入保持原hash。

在固定依赖环境中，从项目根目录执行：

```sh
python scripts/check_p4_bundle.py
# 如需从持久化原始事件重新审计：
python scripts/audit_p4_outputs.py
# 如需重新计算已封存统计与附加视图：
python scripts/analyze_frozen_experiments.py --freeze freeze/g2_v1_20261025 --output results/g2_v1_20261025
python scripts/analyze_p4_extensions.py
```

附加图表/诊断脚本与清单见[`delivery_manifest.json`](delivery_manifest.json)。重新测量耗时会产生新的本机测量，须单独保存，避免覆盖本次证据。历史P3验证入口会重写旧阶段进度，应在独立的P3快照副本运行。

## 8. 下一阶段判断

原论文主线需要由当前证据重新评估。可保留的发现是：显式稳定性评分可改善有限范围候选内的CDI，自适应范围相对固定范围有价值，SAIL减少改派；而全局B2在本基准上的平均AWCT与CDI均更好。后续若研究“改派约束下的效率—延迟权衡”，这是基于已见结果提出的更窄问题，应明确标为探索性新方向。

本阶段不调整λ/μ、事件、种子、指标或对照来挽回H1，也不以Churn替换CDI门槛。若继续改算法或目标，需要独立版本、重新设计留出验证，并保留本次负向结果；若进入P5，应围绕上述真实发现组织论证。DaTR/ReadyFS/FSCD全文及原算法忠实复现边界继续保留，不据共同核基线声称优于这些原版算法。
'''
    (folder/'P4_G3_阶段验收报告.md').write_text(report)
    now=datetime.now(timezone.utc).isoformat()
    receipt={'stage':'P4','status':'COMPLETE','P4_execution_and_validation_passed':True,'G3_original_hypothesis_supported':bool(supported),
             'G3_status':'SUPPORTED' if supported else 'NOT_SUPPORTED','H1':'NOT_SUPPORTED','H2':'SUPPORTED_WITHIN_BOUNDED_CANDIDATES',
             'H3':'PARTIAL_SUPPORT','NoChurn':'MATHEMATICAL_ALIAS_MU_ZERO','formal_labels':6960,'physical_executions':6240,'aliases':720,
             'main_roots':30,'main_scenarios':720,'all_scenarios':900,'failure_records':0,'primary':s['primary'],
             'protocol_changed':False,'frozen_algorithms_changed':False,'new_independent_diagnostic_scenarios':0,
             'report':'reports/p4/P4_G3_阶段验收报告.md','completed_at':now}
    dump(folder/'stage_acceptance.json',receipt)
    state=read('project_state.json');state.update({'updated_at':now,'current_stage':'P4_COMPLETE_G3_NOT_SUPPORTED',
        'next_stage':'RESEARCH_DIRECTION_REASSESSMENT_BEFORE_P5','P4_passed':True,'P4_complete':True,'G3_passed':bool(supported),
        'G3_status':'NOT_SUPPORTED','latest_acceptance_report':receipt['report'],'formal_runs_completed':6960,
        'formal_actual_executions':6240,'formal_alias_records':720,'P3_snapshot':'archive/p3_20261025','diagnostic_replays':1120})
    dump(ROOT/'project_state.json',state)
    budget=read('planning/experiment_budget_plan.json');budget.update({'status':'P4_COMPLETE_G3_NOT_SUPPORTED','runs_completed':6960,
        'physical_executions_completed':6240,'alias_records_completed':720,'main_scenarios_completed':720,'all_fault_scenarios_completed':900,
        'reference_executions_completed':480,'diagnostic_replays_excluded_from_formal_counts':1120,'P4_wall_seconds':clock['wall_seconds'],
        'P4_acceptance_report':receipt['report'],'G3_passed':bool(supported),'updated_at':now})
    dump(ROOT/'planning/experiment_budget_plan.json',budget)
    print(json.dumps({'P4_complete':True,'G3_supported':bool(supported),'report':receipt['report']},ensure_ascii=False))


if __name__=='__main__':main()
