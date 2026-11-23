"""Write the completed exploratory report, evidence map and separate v2 state."""
import json
import sys
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from sail.development import dump


def main():
    folder=ROOT/'research_v2';reports=folder/'reports'
    def read(p):return json.loads((ROOT/p).read_text())
    s=read('research_v2/reports/pilot_statistics.json');d=read('research_v2/reports/existing_diagnosis.json')['summary']
    check=read('research_v2/reports/bundle_check.json');assert check['status']=='PASS'
    def e(x,pct=False):
        k=100 if pct else 1;c=x['ci95'];return f"{k*x['point']:+.4f}{'%' if pct else ''} [{k*c[0]:+.4f}, {k*c[1]:+.4f}]"
    def table(headers,rows):return '| '+' | '.join(headers)+' |\n| '+' | '.join(['---']*len(headers))+' |\n'+'\n'.join('| '+' | '.join(r)+' |' for r in rows)
    legacy={r['scenario_id']:r for r in [json.loads(x) for x in (ROOT/'results/g2_v1_20261025/metrics.jsonl').read_text().splitlines()] if r.get('method')=='B2'}
    pilot=[json.loads(x) for x in (folder/'pilot/metrics.jsonl').read_text().splitlines()]
    qrows=[]
    for variant in ('main','cv0.1','cv0.3','control_delay'):
        g=[r for r in pilot if r['method']=='BudgetSelect10' and r['variant']==variant]
        qrows.append([variant,str(len(g)),str(sum(not r['quality_feasible'] for r in g)),
                      str(sum(r['awct']>1.05*legacy[r['scenario_id']]['awct'] for r in g)),
                      str(sum(r['quality_feasible'] and r['awct']>1.05*legacy[r['scenario_id']]['awct'] for r in g))])
    methods=['QueueRepair0','B0AssignmentReorder','BudgetHEFT10','BudgetSelect10']
    mainrows=[]
    for m in methods:
        a=s['effects']['main'][m]['B2'];mean=next(r for r in s['method_summary'] if r['variant']=='main' and r['method']==m)
        mainrows.append([m,e(a['cdi']),e(a['relative_awct'],True),f"{mean['mean_Churn']:.4f}"])
    mechanisms=[]
    for variant,g in s['effects'].items():
        for name,a in g['mechanisms'].items():mechanisms.append([variant,name,e(a['cdi']),e(a['relative_awct'],True)])
    robust=[]
    for variant,g in s['effects'].items():
        if variant=='main':continue
        for m in methods:
            a=g[m]['B2'];robust.append([variant,m,e(a['cdi']),e(a['relative_awct'],True)])
    decomposition=[[m,str(r['n']),f"{r['total_CDI_gap']:.6f}",f"{r['candidate_set_gap']:.6f}",f"{r['selection_gap']:.6f}",str(r['best_H012_worse_than_B2'])] for m,r in d.items()]
    report=f'''# G3后研究重评与探索阶段验收报告

日期：2026-10-25。状态：**研究重评与探索计算完成；protocol_v2形成可审阅草案，新确认性冻结尚未建立。** 原v1的G3结论仍为NOT_SUPPORTED。新工作全部位于`research_v2/`，v1的58项交付文件逐项hash保持不变。

本阶段形成了具体的机制证据：保持B0的全部任务分配不变、只重新排列队列，在这批已见主场景上使CDI降低0.6105、平均配对AWCT降低2.10%。预算候选选择器在可选改派比例不超过10%的构造约束下，相对直接预算HEFT降低CDI和平均AWCT；相对无预算B2的CDI区间跨零，且部分场景的预计质量条件不可行。

## 1. 原结果的候选集合分解

定义每个主场景的`c_star=min(CDI_B0, CDI_FixedH1, CDI_FixedH2)`。这些方法已在原实验中完整运行，因此可用实际CDI形成有限候选集的下包络。逐场景有精确恒等式：

`CDI_SAIL - CDI_B2 = (c_star - CDI_B2) + (CDI_SAIL - c_star)`。

第一项为候选集合包络差，第二项为当前选择相对该包络的差。此处的c_star使用实际结果，是事后诊断的oracle，不是已验证的新在线策略。

{table(['范围','场景','总CDI差','候选包络差','选择差','最小候选CDI仍高于B2的场景'],decomposition)}

整体总差0.583458中，候选包络项为0.583295，选择项为0.000163。按这个净差分解，约99.97%的差距在最小候选包络与B2之间。566/720场景即使取实际CDI最低的H0/H1/H2也没有达到B2，124场景较低、30场景相同。这说明在原有三类候选内进一步强调CDI选择，能回收的平均差距很小。

按B2是否移动保护任务P对CDI差作描述性分组，移动P的贡献为{d['all']['moved_P_contribution']:.6f}，未移动P的贡献为{d['all']['unmoved_P_contribution']:.6f}，二者相加等于总差。该分组没有固定其他调度决策，不能当作迁移的因果效应。

## 2. 新增控制与执行身份

初始探索规格在新方法运行前写入[pilot_spec.json](../pilot_spec.json)，看到v1结果后设计，使用原900场景。增加三个原型：

- QueueRepair0：健康待执行任务保持原节点，F执行必要恢复，允许全部Q重排；可选改派为0。
- BudgetHEFT10：允许全部Q重排；可选改派任务数不超过`floor(0.10*max(1,|Q|))`。该预算不包含F。
- BudgetSelect10：在原H0/H1/H2、QueueRepair0、BudgetHEFT10与预算可行的B2组成的计划池中，先过滤预算，再在预计AWCT≤1.05×预计B2的计划中选预计CDI最低者。无质量可行计划时，以预算内最小预计AWCT回退，明确保留不可行标志。

初步结果后，为分开QueueRepair0的F放置变化与队列变化，增加B0AssignmentReorder。其[追加规格](../order_control_spec.json)写于追加运行前：完整固定B0对所有未完成任务的节点分配，包括F，只允许重新排列队列。该追加设计也属于探索。

三个初始控制各900次，加锁定分配对照900次，共**3,600次新物理执行**，覆盖全部900个旧场景；原来的6,960个正式标签保持原义。新增独立真实测试集为0、新故障场景为0、原始G3状态没有改变。原103任务规模留出未使用。

## 3. 主场景的完整结果

全部720场景保留，CDI NA为0。区间沿用原根种子整块bootstrap函数，5,000次、种子73000；主条件有30根，误差/延迟各10根。这些是新设计在已见固定基准上的描述性区间。

{table(['方法','CDI差vs B2 [95% CI]','AWCT配对相对差vs B2 [95% CI]','平均Churn'],mainrows)}

BudgetSelect10的平均CDI为3.5118，B2为3.5158；二者差的95%区间跨零，当前结果既没有建立CDI优势，也没有建立等效性。其平均配对AWCT相对B2增加0.9021%，平均Churn为0.0448，B2为0.4546。AWCT配对相对差的平均与AWCT均值之比不同，正文数值按配对规则报告。

BudgetSelect10与BudgetHEFT10的预算相同，但候选池和选择规则不同；本阶段比较支持整个选择程序的作用，尚未将收益单独归因于CDI目标。后续需要同池PoolMinAWCT10对照。

## 4. 队列顺序与同预算机制

{table(['条件','比较（前者−后者）','CDI差 [95% CI]','AWCT配对相对差 [95% CI]'],mechanisms)}

锁定B0全部分配后，只改变顺序的主条件结果为：CDI差−0.6105 [−0.6760,−0.5447]，AWCT相对差−2.0996% [−2.5133,−1.6613]。900个场景的任务分配与B0完全相同，可选Churn始终为0；这是本阶段关于队列顺序的直接控制证据。它表明相同任务分配可以对应不同的保护延迟和完成时间，Churn本身不足以概括执行稳定性。

这是一项确定性仿真干预及重复条件下的结果，不提供实际集群人员协调成本的估计。保留每次输入取消、通信、CPU和重试事件，可供后续机制细分。

## 5. 全部稳健性与质量不可行

{table(['条件','方法','CDI差vs B2 [95% CI]','AWCT相对差vs B2 [95% CI]'],robust)}

BudgetSelect10在两个CV水平及控制延迟下相对B2的CDI区间均跨零。相对同预算HEFT，其CDI差在全部条件下为负且区间低于0；CV0.3时的AWCT差区间跨零，该零结果保留。

预计质量条件与实际AWCT越界逐项报告如下。每行的实际条件均为`AWCT_new > 1.05*AWCT_B2`，属于逐场景诊断，区别于v1对平均AWCT的统计门槛。

{table(['条件','场景','预计质量无可行计划','实际AWCT越过1.05×B2','预计有可行计划但实际仍越界'],qrows)}

主条件71/720=9.86%的场景无预计质量可行候选，均按已写下的规则回退；没有删除这些场景。CV0.3中，实际工作量误差还会使部分预计可行场景越界。因此，本方法构造性保证的是可选改派数量上限；预计质量条件不构成实际逐场景AWCT保证。

## 6. 实现与证据验收

- 新控制测试135项，追加锁定分配测试64项，合计**199项通过**。取消预算的BudgetHEFT与冻结B2逐项等价；预算、输入/资源约束、确定性与预测算术均有对照。
- 早期测试夹具将有依赖的任务误标到不同工作流，模型正确拒绝；已修正夹具，初次XML与最终报告同时保留。修正发生在任何pilot运行前，没有修改v1模型或数据。
- 3,600份事件文件重新校验SHA-256；独立审计并核对**2,700,003条新事件**，900份锁定分配对照的B0分配不一致数为0，可选改派预算违规数为0。
- 原G2算法/协议/数据hash、v1的58个交付文件全部保持；本次没有覆盖旧统计、旧图件或`project_state.json`。新版本状态独立写入`research_v2/status.json`。
- **88项统计量**通过独立向量化根块计算复核；所有点估计、双侧区间和单侧上界差异<1e-11。重采样未把重复方法、任务或日志当成新的n。
- 两幅探索图提供PDF/SVG/300DPI不透明RGB PNG及完整图注，标题明确已见场景及探索性质。全部原始结果、不可行数与零结果可以追溯。

## 7. 论文定位与下一版协议

建议将下一版问题表述为**“共享工作流故障恢复中，如何分开控制任务改派与队列顺序，并在明确改派预算下选择保护延迟较低的修复计划？”** 当前最具体的证据来自固定全部任务分配后的顺序控制，其次是同预算选择程序的权衡。

不再沿用原“有限逻辑后代范围即可相对B2减少CDI”的主张。原确认性结果应完整保留在研究记录与后续论文的适当位置；它说明为什么需要把两个调度自由度分开研究。

定位补核：[Luo等2017作者预印本](https://arxiv.org/abs/1701.07498)已将时间偏差约束与完成时间目标结合，[NASA迭代修复报告](https://ntrs.nasa.gov/citations/19930006099)已有减少计划扰动的目标。本轮读取摘要及元数据，不能将“增加扰动约束”本身作为首创。新增来源与BibTeX分别见[sources.json](../sources.json)、[references_added.bib](../references_added.bib)。

交付的[protocol_v2草案](../protocol_v2_draft.md)已明确：同预算BudgetHEFT为新主比较、同池最小AWCT为必要归因对照、新拓扑组留出、独立种子命名空间、冻结前精度与资源选择，以及完整应用耗时。该草案仍需未见数据manifest、同池对照和顺序扰动指标，才能成为正式freeze_v2。

## 8. 复现与当前决策

```sh
python research_v2/check_bundle.py
```

该检查核对旧交付未变、新源文件hash、3,600份结果、预算/固定分配、CDI重算和88项统计量。原始新模拟入口`run_pilot.py`有源hash绑定的检查点，追加入口`run_order_control.py`拒绝覆盖已有输出。重新运行应使用独立输出版本，保留本次证据。

**本阶段验收：通过。** 值得继续的方向是“预算下的队列修复与分配控制”；新算法的确认性收益、新真实数据的泛化与投稿就绪状态尚待独立阶段验证。下一步优先补同池最小AWCT对照、获取并封存未见拓扑数据，再完成v2冻结；论文定位与证据映射见[P5准备说明](../P5_论文定位与证据映射.md)。
'''
    (reports/'G3后研究重评与探索阶段报告.md').write_text(report)
    now=datetime.now(timezone.utc).isoformat()
    status={'stage':'POST_G3_EXPLORATION_COMPLETE','completed_at':now,'original_formal_status':'P4_COMPLETE_G3_NOT_SUPPORTED',
            'original_formal_labels':6960,'v1_delivery_unchanged':True,'exploratory_physical_runs':3600,'reused_fault_scenarios':900,
            'new_independent_test_sets':0,'new_confirmatory_runs':0,'correctness_tests_passed':199,'budget_violations':0,
            'locked_assignment_mismatches':0,'protocol_v2_status':'DESIGN_DRAFT','ready_for_confirmatory':False,
            'next_required':['same-pool PoolMinAWCT10 control','unseen-topology manifest_v2','queue-order disturbance metric','full application timing','pretest precision/resource choice'],
            'report':'research_v2/reports/G3后研究重评与探索阶段报告.md','protocol':'research_v2/protocol_v2_draft.md'}
    dump(folder/'status.json',status)
    (folder/'README.md').write_text('''# G3之后的探索研究

本目录独立保存看到v1正式结果后的机制研究。原v1交付与G3判断保持；这里的pilot没有新增独立真实测试集。

- [阶段报告](reports/G3后研究重评与探索阶段报告.md)
- [protocol_v2草案](protocol_v2_draft.md)
- [论文定位与证据映射](P5_论文定位与证据映射.md)
- [当前状态](status.json)
- [全部配对效应](reports/paired_effects.csv)
- [验收回执](reports/bundle_check.json)

四个控制各运行原900场景，共3,600次探索执行。199项新测试通过，预算违规0，锁定B0任务分配的对照不一致0。

快速校验：`python research_v2/check_bundle.py`。原算法在`sail/`保持冻结，新原型在本目录。正式v2冻结需要独立数据与已列明的同池控制、指标及计时，详见协议草案。
''')
    (ROOT/'RESEARCH_STATUS.md').write_text('''# 当前研究入口

2026-10-25：已完成G3之后的研究重评和3,600次探索执行，形成protocol_v2草案。

当前交付：[G3后研究重评与探索阶段报告](research_v2/reports/G3后研究重评与探索阶段报告.md)。

新版本状态：[research_v2/status.json](research_v2/status.json)。原根目录`project_state.json`保留v1的P4/G3完成状态，属于已校验交付证据；后续探索没有改写该记录。

下一步：同池最小AWCT控制、未见拓扑数据manifest、顺序扰动指标、完整应用计时，然后封存v2。当前新确认性运行数为0，v1原主假设未获支持的结论保持。
''')
    print(json.dumps(status,ensure_ascii=False))


if __name__=='__main__':main()
