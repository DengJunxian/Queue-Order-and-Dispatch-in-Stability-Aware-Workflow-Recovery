"""Generate the stage report directly from audited data and sealed statistics."""
import json
import sys
from datetime import datetime,timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from sail.development import dump


def main():
    folder=ROOT/'formal_v2/reports';out=ROOT/'results/g2_v2_20261025'
    def read(path):return json.loads(path.read_text())
    stats=read(out/'statistics.json');extra=read(folder/'reporting_statistics.json');audit=read(folder/'audit_summary.json');check=read(folder/'bundle_check.json')
    execution=read(out/'execution_summary.json');clock=read(folder/'execution_wall_clock.json');assert audit['status']==check['status']=='PASS'
    supported=stats['G3_v2_supported'];verdict='通过' if supported else '未通过';now=datetime.now(ZoneInfo('Asia/Shanghai'))
    def num(v,d=4):return f'{v:.{d}f}' if v is not None else 'NA'
    def effect(metric,pct=False):
        k=100 if pct else 1;p=metric['point'];ci=metric['ci95'];unit='%' if pct else ''
        value=f'{k*p:+.4f}{unit}' if p is not None else 'NA'
        return value+(f' [{k*ci[0]:+.4f}, {k*ci[1]:+.4f}]' if ci else ' [CI未定义]')
    def table(h,rows):return '| '+' | '.join(h)+' |\n| '+' | '.join(['---']*len(h))+' |\n'+'\n'.join('| '+' | '.join(r)+' |' for r in rows)
    comps=('PoolMinAWCT10','BudgetHEFT10');primary=[];gate_rows=[];mixrows=[]
    for comp in comps:
        g=stats['primary'][comp];s=g['overall'];negative=sum(x['cdi']['point'] is not None and x['cdi']['point']<0 for x in g['mixes'].values())
        primary.append([comp,effect(s['cdi']),effect(s['relative_awct'],True),num(s['relative_awct']['upper95']*100 if s['relative_awct']['upper95'] is not None else None)+'%',f'{negative}/3'])
        flags=stats['primary_gates'][comp]
        gate_rows.append([comp,'满足' if flags['CDI_upper_below_zero'] else '未满足','满足' if flags['AWCT_upper_within_5pct'] else '未满足','满足' if flags['at_least_two_mix_directions'] else '未满足'])
        for mix,s in g['mixes'].items():mixrows.append([comp,mix,effect(s['cdi']),effect(s['relative_awct'],True),str(s['cdi']['defined_pairs']),str(s['cdi']['undefined_pairs'])])
    main_summary={r['method']:r for r in extra['method_summary'] if r['variant']=='main'}
    names=['B0','B1','B2','LegacySAIL','QueueRepair0','BudgetHEFT10','BudgetSelect10','PoolMinAWCT10','B0AssignmentReorder']
    methodrows=[[m,num(main_summary[m]['mean_AWCT']),num(main_summary[m]['mean_CDI']),num(main_summary[m]['mean_Churn']),num(main_summary[m]['mean_order_disturbance']),str(main_summary[m]['CDI_NA'])] for m in names]
    secondary=[[name,effect(s['cdi']),effect(s['relative_awct'],True)] for name,s in stats['secondary'].items()]
    robust=[]
    for variant,g in stats['robustness'].items():
        for comp,s in g.items():robust.append([variant,comp,effect(s['cdi']),effect(s['relative_awct'],True),str(s['cdi']['defined_pairs']),str(s['cdi']['undefined_pairs'])])
    theta=[]
    for tag in ('0','0.05','0.1','0.2','0.5','1'):
        for base in ('PoolMinAWCT','BudgetHEFT'):
            s=extra['supplemental']['theta0.1'][base+'10'] if tag=='0.1' else stats['budget_sensitivity'][tag][base]
            theta.append([tag,base,effect(s['cdi']),effect(s['relative_awct'],True),str(s['cdi']['undefined_pairs'])])
    quality=[]
    for r in extra['method_summary']:
        if r['method'].startswith(('BudgetSelect','PoolMinAWCT')):
            quality.append([r['variant'],r['method'],str(r['labels']),str(r['quality_infeasible']),str(r['actual_AWCT_gt_1.05_B2']),str(r['predicted_feasible_but_actual_over']),str(r['threshold_rounding_disagreements'])])
    times=[[m,str(main_summary[m]['full_apply_samples']),num(main_summary[m]['full_apply_p50_seconds']*1000 if main_summary[m]['full_apply_p50_seconds'] is not None else None,2),
            num(main_summary[m]['full_apply_p95_seconds']*1000 if main_summary[m]['full_apply_p95_seconds'] is not None else None,2)] for m in names]
    coverage=[[v,str(c['scenarios']),str(c['F_empty']),str(c['P_empty'])] for v,c in audit['coverage'].items()]
    planning='新假设满足全部预定支持条件，可以进入P5组织结果与论文论证。' if supported else '新假设未满足全部预定支持条件，应按本次结果重评具体主张。新基准现已成为已见数据，后续方法变更需要独立版本与验证。'
    interpretation=('同池两方法共享候选生成、预算筛选和质量集合，比较集中于计划选择规则。本次结果支持预计CDI选择在这一冻结候选池中提供保护延迟增量，同时付出相对同池AWCT最小化的完成时间成本；在同预算BudgetHEFT10对照中，总体CDI和AWCT均改善。两项比较的三个Mix均为CDI改善方向。' if supported else '两项比较共同界定选择规则的增量及其完成时间成本，具体支持范围由上表全部冻结门槛决定。')
    report=f'''# protocol_v2 正式确认性实验与 G3_v2 阶段验收报告

出具时间：{now:%Y-%m-%d %H:%M}，Asia/Shanghai。协议：[冻结protocol_v2](../../freeze/g2_v2_20261025/protocol_v2.md)；冻结标识：`{audit['freeze_id']}`。

**全部15,780个标签执行完成，独立日志复算和统计核验通过；G3_v2判断为：{verdict}。** 原v1的G3未获支持结论与此前探索结果保持原身份。{planning}

## 1. 两项预定比较及G3_v2判断

差值均为BudgetSelect10−对照，CDI负值表示保护任务延迟较低，AWCT正值表示完成时间成本。正式主比较为同池PoolMinAWCT10，必要实用对照为同预算BudgetHEFT10；两项都须满足协议门槛。双侧95%区间与AWCT单侧95%上界均来自冻结的5,000次根块bootstrap、seed83000。

{table(['对照','CDI差 [95% CI]','AWCT平均配对相对差 [95% CI]','AWCT单侧上界','Mix改善方向'],primary)}

{table(['对照','CDI区间上界<0','AWCT上界≤5%','至少两个Mix方向<0'],gate_rows)}

全部硬改派预算违规为0，B0AssignmentReorder的完整分配核对不一致为0。冻结统计脚本返回`G3_v2_supported={str(supported).lower()}`，独立统计路径复核了数值、NA传播及所有门槛判断。

{interpretation}

{table(['对照','Mix','CDI差 [95% CI]','AWCT相对差 [95% CI]','CDI有定义对数','NA对数'],mixrows)}

G3判断使用冻结的整体比较和预定方向条件；资源分层、质量不可行率、顺序指标及耗时不构成追加门槛。没有按结果改变种子、方法、预算、指标或事件。

## 2. 执行范围与独立性

| 任务组 | 标签数 |
| --- | --- |
| 主故障场景1,440×9配置 | 12,960 |
| 主匹配无故障参考 | 720 |
| CV0.1/CV0.3及控制延迟180×6配置 | 1,080 |
| 误差匹配无故障参考 | 120 |
| 额外5预算水平×60×3配置 | 900 |
| 名义标签合计 | 15,780 |
| 数学别名记录 | 120 |
| 物理执行合计 | 15,660 |

所有标签唯一且覆盖冻结清单；无执行失败、缺失或重复标签。840份无故障参考与1,920个条件ID均已核对；其中300个预算条件复用主实验环境，不能当作新的独立故障样本。Theta0/1的BudgetHEFT分别复用QueueRepair0/B2，别名不提供独立计时或额外统计n。

正式根81000—81059共60个，主轴为3Mix×节点4/8×CCR0.5/2×故障0.3/0.6。数据为封存的6个冻结前未见拓扑组：Montage178/310、Epigenomics119/125、SRA Search22/104任务。三工作流组合245—613任务，所有输入原始/解析hash保持一致；原103任务规模留出未运行。输入的10条时间戳格式告警仍是元数据告警，未用于仿真。

这是以真实工作流记录提供结构、工作量和文件量的仿真实验。区间刻画该固定新基准的预定环境随机性，不将60根解释为60套独立真实拓扑。开发、验证、profiling和此前探索未混入正式标签。

## 3. 持久化日志独立复算

核对15,660份物理事件文件SHA-256及全部任务身份，从保存日志独立重算**{audit['event_records_independently_recomputed']:,}条事件**。检查依赖、CPU及输入准备、永久故障、尝试隔离、健康运行非抢占、范围外分配/顺序、AWCT、makespan、CDI、Churn、顺序逆序数、通信和废弃计算量。

每个条件内的方法共享同一原F/Q/P；故障时刻等于对应实际无故障makespan的固定比例；严格早于故障的事件前缀与匹配无故障执行一致。硬改派预算按整数`floor(theta*max(1,|Q|))`核对，必要F恢复不计入可选改派。

顺序扰动用独立Fenwick计数重算，与封存的归并计数实现对照。B0相对同故障自身的有符号延迟在非空P上派生为0；原始JSONL里的自身参考NA保持原样。

{table(['条件','条件ID数','F空集','P空集/CDI NA'],coverage)}

以上场景全部保留。CDI的NA与数值0分开记录；原始结果中的别名、质量不可行和无影响故障均未删除。

## 4. 统计独立验证与主要描述均值

正式分析由冻结的`v2_preparation/analyze_confirmatory.py`执行。另从独立日志复算数据计算60项已封存指标结果，覆盖两项整体/分Mix比较、全部稳健性、三个机制参照及预定预算对照。使用根重采样计数矩阵、逐轴单元掩码均值及全部Mix的NA传播，独立于原逐次重采样循环；连同补充视图共核对88项指标结果。最大绝对数值差为{extra['independent_verification']['max_abs_numerical_difference']:.3g}。

方法为：同一根块在各Mix/轴/方法中共同重采样；先平均每Mix内有定义轴单元，再对Mix等权。任一Mix完全不适用时统计量未定义；只有全部5,000次抽样均定义才给CI。报告效应与区间，无p值。补充分层及theta0.10匹配子集单列在`reporting_statistics.json`，不改动冻结分析和G3门槛。

{table(['主方法','平均AWCT','平均CDI','平均Churn','平均条件顺序扰动','CDI NA标签'],methodrows)}

本表为有定义场景的直接描述均值；CDI缺失比例在Mix间不同时，其均值差不等于主配对估计。AWCT配对相对差先逐场景计算比率，再按协议汇总，不能用本表AWCT均值之比替代。顺序扰动条件于留在原节点的Q\\F任务对，分母随改派变化，须连同留存任务数、可比较对数和Churn解释。工作流级44,820条slowdown及重试、通信、废弃CPU等附加指标均保留在源表，没有替换主指标。

## 5. 队列机制与B2参照

{table(['比较（前者−后者）','CDI差 [95% CI]','AWCT相对差 [95% CI]'],secondary)}

B0AssignmentReorder完整锁定B0的所有未完成任务节点，包括F，只改变队列顺序；QueueRepair0固定健康任务节点，还可能改变F的恢复节点。两个控制分别保留，避免把恢复节点与顺序的联合变化全归因于顺序。B2是无预算的共同核启发式参照；同预算的归因以两项预定主比较为准。

## 6. 误差与公共控制延迟

{table(['条件','对照','CDI差 [95% CI]','AWCT相对差 [95% CI]','CDI有定义','NA'],robust)}

每个条件有前10根、3Mix、两CCR的60场景，节点4、故障0.6。实际工作量使用均值校正对数正态误差，跨方法复用同任务随机场，重试不重新抽样。控制延迟为公共0.1 pbar：运行中任务和已开始输入准备继续，所有新CPU派发暂停。它是共同等待敏感性，未注入各算法实测wall time。

## 7. 全部预算水平与质量不可行

{table(['theta','同预算对照','CDI差 [95% CI]','AWCT相对差 [95% CI]','NA对数'],theta)}

所有水平使用同一60场景子集；theta0.10复用主实验相应行，不以全部1,440主场景均值代替。没有根据某个有利水平重选主theta。

{table(['条件','方法','标签','预计质量不可行','实际AWCT>1.05×B2','预计可行但实际越界','近阈值数值差异'],quality)}

质量过滤作用于预计值；无质量可行候选时依冻结规则回退。不可行场景完整纳入主要分析。实际逐场景越界是附加诊断，区别于G3对平均配对AWCT的5%研究容忍度；这个容忍度不是业务SLA。实际越界列保留严格比较；末列列出改用1e-9数值容差时判别不同的标签数，不据此删除或重分类原始记录。

## 8. 耗时、资源与复现

正式批次：{clock['started_at_Asia_Shanghai']}至{clock['finished_at_Asia_Shanghai']}，实际wall time {clock['wall_seconds']/60:.2f}分钟。其间包含初始HEFT、无故障执行、故障方法、在线独立审计和事件落盘；另外的持久化日志复算耗时{audit['audit_wall_seconds']/60:.2f}分钟。冻结前约10.56小时是保守规划值，不能作为已执行时长。

{table(['主配置','完整应用样本','p50（毫秒）','p95（毫秒）'],times)}

应用计时覆盖快照、全部候选构造/去重/预测/选择、校验、输入失效与计划应用；别名计时为空。p50/p95为本机描述性分位数，不是CI，不将方法调用数当独立n。批次单进程执行，其他主机活动未控制。调度计算wall time没有加到模拟AWCT，模拟的公共控制延迟敏感性另行报告。

检查入口：

```sh
python formal_v2/check_bundle.py
# 如需再次读取全部物理事件文件校验hash：
python formal_v2/check_bundle.py --events
```

事件独立重算入口为`formal_v2/audit_outputs.py`；重新运行审计应单独保存验收时间记录。主统计复算使用原冻结`v2_preparation/analyze_confirmatory.py`，不能覆盖方法/输入后继续沿用本次确认性身份。

关键交付：[原始执行摘要](../../results/g2_v2_20261025/execution_summary.json)、[冻结统计](../../results/g2_v2_20261025/statistics.json)、[日志审计](audit_summary.json)、[数值复核与补充视图](reporting_statistics.json)、[完整配对表](data/paired_effects.csv)、[全部方法汇总](data/method_summary.csv)、[四幅图及图注](figures/manifest.json)。

旧阶段的`formal_runs_completed=0`字段为冻结时刻快照，按不可变证据保留；本阶段实际执行身份以`execution_summary.json`、本报告和`progress/current.json`为准。此前三份交付清单共{check['historical_file_checksums_unchanged']:,}项文件校验和保持。

## 9. 阶段验收结论

实验执行、独立复算、统计和交付完整性验收通过。**G3_v2：{verdict}。** {planning} 后续科学叙事应同时保留效率成本、NA、质量不可行及零/负向结果；DaTR/ReadyFS/FSCD全文和原版算法忠实复现的来源边界仍沿用既有记录。
'''
    report_path=folder/'V2_正式确认性实验与G3_v2_阶段验收报告.md';report_path.write_text(report)
    receipt={'stage':'V2_CONFIRMATORY_COMPLETE','execution_and_integrity_passed':True,'G3_v2_supported':supported,'G3_v2_status':'SUPPORTED' if supported else 'NOT_SUPPORTED',
        'nominal_labels':15780,'physical_executions':15660,'alias_records':120,'reference_jobs':840,'fault_conditions':1920,'root_blocks_main':60,
        'new_unseen_topology_groups':6,'primary_gates':stats['primary_gates'],'independent_event_records':audit['event_records_independently_recomputed'],
        'independent_frozen_statistic_checks':60,'independent_total_statistic_checks':88,'protocol_changed':False,'methods_changed':False,'original_v1_G3':'NOT_SUPPORTED',
        'report':str(report_path.relative_to(ROOT)),'completed_at_Asia_Shanghai':now.isoformat()}
    dump(folder/'stage_acceptance.json',receipt)
    dump(ROOT/'progress/current.json',{**receipt,'stage':'V2_COMPLETE_G3_SUPPORTED' if supported else 'V2_COMPLETE_G3_NOT_SUPPORTED',
        'freeze':'freeze/g2_v2_20261025','next_stage':'P5_PAPER_EVIDENCE_ORGANIZATION' if supported else 'REASSESS_V2_CLAIMS_WITH_FULL_RESULTS'})
    (ROOT/'LATEST_RESEARCH.md').write_text(f'# 当前研究进展\n\n{now:%Y-%m-%d %H:%M}（Asia/Shanghai）：protocol_v2全部15,780标签完成，独立复算与统计验收通过；G3_v2{verdict}。\n\n[本阶段报告]({report_path.relative_to(ROOT)})\n\n[验收回执](formal_v2/reports/stage_acceptance.json)；[当前状态](progress/current.json)。\n\n{planning}\n')
    print(json.dumps(receipt,ensure_ascii=False))


if __name__=='__main__':main()
