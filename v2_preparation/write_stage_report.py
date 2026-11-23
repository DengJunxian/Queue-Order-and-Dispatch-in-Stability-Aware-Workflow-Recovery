"""Stage narrative and mutable progress pointer, kept outside sealed algorithms."""
import csv
import json
import sys
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from sail.development import dump


def main():
    p=ROOT/'v2_preparation'
    def read(path):return json.loads((p/path).read_text())
    check=read('reports/stage_check.json');assert check['status']=='PASS'
    cfg=json.loads((ROOT/'freeze/g2_v2_20261025/freeze.json').read_text());data=read('reports/new_data_summary.json');effects=read('reports/same_pool_statistics.json')['effects']
    dev=read('development/summary.json');budget=read('reports/budget_decision.json');timing=read('reports/full_application_summary.json')['summary']
    def e(v,pct=False):
        k=100 if pct else 1;return f"{v['point']*k:+.4f}{'%' if pct else ''} [{v['ci95'][0]*k:+.4f}, {v['ci95'][1]*k:+.4f}]" if v['ci95'] else 'NA'
    def table(h,rows):return '| '+' | '.join(h)+' |\n| '+' | '.join(['---']*len(h))+' |\n'+'\n'.join('| '+' | '.join(r)+' |' for r in rows)
    effectrows=[[v,e(s['cdi']),e(s['relative_awct'],True),str(s['cluster_count']),str(s['cdi']['defined_pairs'])] for v,s in effects.items()]
    timerows=[[x['method'],f"{x['p50_seconds']*1000:.2f}",f"{x['p95_seconds']*1000:.2f}"] for x in timing]
    order=list(csv.DictReader((p/'reports/order_summary.csv').open()));orderrows=[[r['method'],r['label_rows'],f"{float(r['mean_order_disturbance']):.4f}" if r['mean_order_disturbance'] else 'NA',r['NA_scenarios'],f"{float(r['mean_Churn']):.4f}"] for r in order if r['variant']=='main']
    datarows=[[r['family'],r['id'],str(r['tasks']),r['topology_group']] for r in read('data/manifest_v2.json')['records']]
    report=f'''# v2冻结前验证与G2_v2阶段验收报告

日期：2026-10-25。结论：**同池对照、未见数据、顺序指标、完整应用耗时、开发精度与预算检查已完成，G2_v2已冻结。** 当前真实v2调度执行数为0；v1的G3未获支持结论及上一轮探索交付均保持原hash。

## 1. 同池最小AWCT对照已补齐

新增PoolMinAWCT10与已有BudgetSelect10共用同一候选生成、完整计划去重、整数预算、预计质量可行集合；PoolMinAWCT以预计AWCT、Churn、候选名、完整队列排序，不使用CDI破并列。全部900旧场景运行完成，其生成的原BudgetSelect决策与历史日志900/900一致。新增结果属于已见数据上的探索机制证据。

表中均为BudgetSelect10−PoolMinAWCT10，区间为旧根块5,000次bootstrap描述性95%区间。

{table(['条件','CDI差 [95% CI]','AWCT配对相对差 [95% CI]','复用根数','CDI有定义对数'],effectrows)}

主条件CDI减少0.1746，平均配对AWCT成本增加0.6025%。三个扰动条件的CDI区间也均低于0，AWCT成本区间为正。这进一步分开了候选池扩展与选择目标的作用；该发现将在新协议中通过未见拓扑检验。

## 2. 新真实测试输入已取得并验证

通过GitHub连接器从官方WfInstances固定commit取得6份新原始JSON，按读取任何新调度效果前写下的规则选择文件；每个字节均通过Git blob SHA和SHA-256核验。固定schema、依赖/文件/工作量校验均无错误，与v1全部20份图及新增图之间做无标号有向图同构核对，确认6个新组。

{table(['家族','实例ID','任务数','新拓扑组'],datarows)}

共858任务，三工作流组合为245—613任务，较v1覆盖更大规模；不按新效果筛除实例。10条非规范时间戳告警保留，时间戳不进入仿真。原103任务规模留出没有运行。每个新组只有一份代表输入，重复环境根并不创造新的独立拓扑。

全部6组均为测试专用，不用于本阶段的精度或效果选择。Mix A按M/E/S stride1/2/4循环，在前8根覆盖全部8种源组合；B/C保留同家族两个不同源实例。60根提供预定环境随机性，区间推断条件于这份固定新基准。

数据与来源见[data/manifest_v2.json](../data/manifest_v2.json)、[官方固定版本](https://github.com/wfcommons/WfInstances/tree/249866063b3bd7d6a36a5a55d4202c1f683099c0)。已验证数据适配与组合，未执行新真实输入的初始调度、无故障运行或故障运行。

## 3. 顺序扰动指标已实现

指标保留原Q\\F中仍留在原健康节点的任务，计算新旧队列中可比较任务对的逆序比例；输出逆序数、任务对分母、留存任务数及分母为0的NA。该条件分母随任务改派而变，因此与Churn一起解释。

已从原v1、上一轮探索及本轮同池对照的全部10,980个标签计算，包含原NoChurn别名。主条件描述性均值如下。

{table(['方法','主标签数','平均顺序扰动','NA场景','平均Churn'],orderrows)}

完整逐场景分母见[order_metrics.csv](order_metrics.csv)，没有将逆序比例替换为新的主指标，也未把别名或任务对当独立n。

## 4. 完整应用耗时和端到端profiling

20个事先指定的旧主场景，每物理配置3次，单进程执行。420次重放逐项等于历史RunResult。计时覆盖整个`Simulator._apply`：公开快照、候选生成/去重/预测/评分、约束验证、输入失效与计划应用。

{table(['配置','p50（毫秒）','p95（毫秒）'],timerows)}

这些为本机描述性分位数，重复不增加科学样本数，其他主机活动未控制。方法间实测wall time没有注入控制延迟实验；公共控制延迟仍是0.1 pbar的独立敏感性条件。

另在20个独立合成开发案例上，对9个配置共180次故障运行及20次参考计量完整端到端成本，包含独立审计与保存事件。全部原始profiling日志和计时表保留，不把策略回调时间当作完整应用时间。

## 5. 新开发/验证与种子数量决策

开发使用71000—71019、验证使用72000—72009的独立合成随机流，未读取新真实测试调度结果。480开发+240验证场景，各运行BudgetHEFT10/BudgetSelect10/PoolMinAWCT10，共2,160个故障标签及360个无故障参考；独立审计1,706,442条故障执行事件。固定theta0.10与全部方法，没有本阶段参数搜索。

按开发根块均值差SD及0.05半宽目标，PoolMinAWCT对照估计需要30根，BudgetHEFT对照估计需要40根。在预先限定的30/60两档中选60。规划SD分别为0.05036和0.14473；正态近似精度规划不是新基准实际CI宽度的保证。

最大新Mix613任务，相对192任务合成图按任务数平方放大10.1934，再乘2并加600秒分析余量；端到端p95构成的保守预算估计为**{budget['conservative_estimated_hours']:.2f}小时**，通过12小时门槛。这个数值是预算估计，尚非新基准实测耗时。

## 6. 新协议、任务覆盖与冻结

新主比较升级为同池BudgetSelect10−PoolMinAWCT10，并要求同预算BudgetHEFT10对照也满足预定支持条件。两项分别要求CDI区间上界<0、至少两个Mix方向<0、AWCT相对差单侧95%上界≤5%，同时硬预算违规为0。原v1主假设不改写。

主轴：60根81000—81059×3Mix×2节点×2CCR×2故障比例，1,440场景；9配置。正式bootstrap固定5,000次、seed83000，以根整块重采样各Mix/轴/方法，保留原NA规则。所有预算水平与扰动条件预先封存，不能看新效果后更换。

| 部分 | 方法/参考标签 |
| --- | --- |
| 主故障运行：1,440×9 | 12,960 |
| 主无故障参考 | 720 |
| CV0.1/0.3和控制延迟：180×6 | 1,080 |
| 误差匹配参考 | 120 |
| 预算敏感性额外5水平×60×3 | 900 |
| 合计名义标签 | 15,780 |
| theta0/1的BudgetHEFT确定性别名 | 120 |
| 预计物理执行 | 15,660 |

冻结目录：[freeze/g2_v2_20261025](../../freeze/g2_v2_20261025/freeze.json)。封存60根、180份公共工作流、240个实际工作量向量、6份原始/解析输入、协议、场景、执行/统计/方法代码hash及开发/预算记录。故障具体时刻留待冻结后按匹配实际无故障makespan计算；当前只存规则。

## 7. 验收与交付

本阶段214项新测试通过，覆盖同池身份、CDI不参与AWCT破并列、六个预算水平端点别名、队列逆序与独立穷举、适配器、检查点恢复、别名覆盖及篡改拒绝。小图fixture的执行身份为CORRECTNESS_FIXTURE，未执行新真实基准。

独立复核本轮8项同池统计量，全部900个控制日志、420次计时重放、原交付文件与v2全部输入/源码hash。真实新输入调度执行数0。详见[stage_check.json](stage_check.json)、[冻结配置](../../freeze/g2_v2_20261025/freeze.json)。

正式入口仅作过不运行模拟器的验证：

```sh
python v2_preparation/run_confirmatory.py --plan-only
```

已准备好冻结执行与分析入口，未来运行应保持本次冻结原样：

```sh
python v2_preparation/run_confirmatory.py
python v2_preparation/analyze_confirmatory.py
```

**阶段验收通过：G2_v2为FROZEN，新的G3结果尚未产生。** 旧v1及上一轮探索没有覆盖。本阶段的后续任务是按已封存15,780标签执行、独立复算，再判断新假设；不能把当前探索机制结果或冻结就绪状态写成新确认性发现。
'''
    (p/'reports/V2_G2_冻结前验证与阶段验收报告.md').write_text(report)
    status={'stage':'G2_V2_FROZEN_NOT_RUN','completed_at':datetime.now(timezone.utc).isoformat(),'freeze':'freeze/g2_v2_20261025',
            'selected_root_count':60,'nominal_jobs':15780,'expected_physical_executions':15660,'planned_alias_records':120,'new_unseen_topology_groups':6,
            'new_real_test_scheduling_runs':0,'ready_for_confirmatory':True,'new_G3_result':None,'original_v1_G3':'NOT_SUPPORTED',
            'tests_passed':214,'same_pool_control_runs':900,'synthetic_fault_labels':2160,'full_application_replays':420,
            'conservative_budget_hours':budget['conservative_estimated_hours'],'report':'v2_preparation/reports/V2_G2_冻结前验证与阶段验收报告.md',
            'next_stage':'V2_CONFIRMATORY_EXECUTION_AND_G3'}
    dump(p/'status.json',status)
    (p/'README.md').write_text('''# v2冻结前证据与正式实验入口

当前状态：G2_v2已冻结，新真实调度运行0。新协议与15,780个任务已经封存，旧结果保持。

- [阶段验收](reports/V2_G2_冻结前验证与阶段验收报告.md)
- [定稿protocol_v2](protocol_v2.md)
- [冻结配置](../freeze/g2_v2_20261025/freeze.json)
- [新未见拓扑manifest](data/manifest_v2.json)
- [当前状态](status.json)

执行准备核验：`python v2_preparation/run_confirmatory.py --plan-only`。
交付核验：`python v2_preparation/check_stage.py`。
正式执行：`python v2_preparation/run_confirmatory.py`；完整后分析：`python v2_preparation/analyze_confirmatory.py`。

新阶段采用独立目录。`sail/`、v1/P4和`research_v2/`旧交付不改写；原始负向结果与本轮探索结果分别保留身份。
''')
    current=ROOT/'progress/current.json';dump(current,status)
    (ROOT/'LATEST_RESEARCH.md').write_text('''# 当前研究进展

2026-10-25：G2_v2已冻结；6个未见拓扑组、60根种子、15,780名义标签，真实v2调度运行0。

当前报告：[v2冻结前验证与阶段验收](v2_preparation/reports/V2_G2_冻结前验证与阶段验收报告.md)。
当前协议：[protocol_v2](v2_preparation/protocol_v2.md)。
机器入口：[progress/current.json](progress/current.json)。该进度指针可随阶段推进更新，未列入不可变交付hash。

历史P4与`research_v2`状态文件保持原hash。下一阶段为冻结的新确认性执行及G3判断。
''')
    print(json.dumps(status,ensure_ascii=False))


if __name__=='__main__':main()
