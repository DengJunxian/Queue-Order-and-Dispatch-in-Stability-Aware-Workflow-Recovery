"""Render the completed exploratory control receipt without changing science."""
import json
from pathlib import Path

from revision_r5.run_control import OUT, dump, read, verify_registration, sha


def number(effect, factor=1.):
    point = effect['point'] * factor
    lo, hi = [v * factor for v in effect['ci95']]
    return f'{point:+.6f} [{lo:+.6f}, {hi:+.6f}]'


def main():
    verify_registration()
    data = read(OUT / 'analysis/results.json')
    receipt = read(OUT / 'execution_receipt.json')
    feasibility = read(OUT / 'analysis/feasibility_diagnostic.json')
    assert receipt['status'] == 'PASS' and data['independent_statistics']['status'] == 'PASS'
    lines = ['# R5 ProtectedSubsequence 探索性对照验收报告', '',
             '状态：**R5_EXPLORATORY_CONTROL_PASS**。既有 protocol_v2、确认性结论与 R4 数字保持不变；本轮新增 2,880 个探索性执行，不增加确认性样本。', '',
             '本轮从 P 的祖先封闭性质导出 ProtectedSubsequence（PS）。它固定 B0 完整映射，在各节点保留 healthy running 头，把原 P 子序列稳定移至其余 pending 工作前。方法无需估计未来工作来决定此分区；复用 B0 是为了严格隔离队列顺序干预。', '',
             '完整范围是原 1,440 cases × strict/skip-unready，60 个原环境块、六个固定输入拓扑；paired initial plan、fault、Q/F/P、realized work、reference 与旧研究一致。每个新结果先写完整 gzip 事件日志，再重开文件交给独立事件审计器，依据审计器重建的 starts/finishes 复算 CDI、AWCT 和三个 workflow 完成时间。', '',
             '## 核心结果', '',
             '| Dispatch | CDI | AWCT | PS−PM paired AWCT（%） | PS−BS paired AWCT（%） |',
             '|---|---:|---:|---:|---:|']
    for rule in ('strict', 'skip-unready'):
        d = data['dispatch'][rule]
        s = d['summaries']['ProtectedSubsequence']
        pair = d['contrasts']
        lines.append(f"| {rule} | {s['cdi']['point']:.8f} | {s['awct']['point']:.6f} | {number(pair['ProtectedSubsequence_minus_PoolMinAWCT10']['relative_awct'], 100)} | {number(pair['ProtectedSubsequence_minus_BudgetSelect10']['relative_awct'], 100)} |")
    lines += ['', '括号为原 60 环境 root-block bootstrap 的 95% 区间；每次5000 draws、PCG64 seed83000、各 cell/Mix 等权。AWCT 相对差异按每case比值先计算，再聚合。区间是未调整探索性区间。', '',
              '| Dispatch | workflow p99 vs PM（%） | max（%） | >5% 数量 / 4320 | rate（%） |',
              '|---|---:|---:|---:|---:|']
    for rule in ('strict', 'skip-unready'):
        tail = data['dispatch'][rule]['summaries']['ProtectedSubsequence']['workflow_inflation_vs_PM']
        lines.append(f"| {rule} | {100*tail['p99']:.6f} | {100*tail['max']:.6f} | {tail['above_5pct_count']} / {tail['n']} | {100*tail['above_5pct_rate']:.6f} |")
    lines += ['', '每种 dispatch 的比较对象均为同派发 PM。尾部是 4,320 个 workflow observations 的描述统计，不将这些 observations 当独立拓扑样本。所有旧方法值完整保留。', '',
              '与 PF 相比，PS 在 strict 和 skip 下的 paired AWCT 差异依次为 ' +
              number(data['dispatch']['strict']['contrasts']['ProtectedSubsequence_minus_ProtectedFirst']['relative_awct'], 100) + '% 和 ' +
              number(data['dispatch']['skip-unready']['contrasts']['ProtectedSubsequence_minus_ProtectedFirst']['relative_awct'], 100) + '%；完整 CDI 对比与区间位于结构化统计。', '',
              '## 原阈值下的事后可行性诊断', '',
              f"PS 的 strict exact-work 结果中，{feasibility['overall']['mean_filter_pass']}/1440 满足原 1.05×B2 mean filter，{feasibility['overall']['workflow_filter_pass']}/1440 满足各 workflow≤1.05×PM，两者交集为 {feasibility['overall']['both_pass']}/1440。",
              '其中旧 mean-quality set 非空的1416 cases中，交集为289；旧24 fallback中交集为2。此查询在主研究结果已知、PS执行接近完成后单独登记，然后计算。它是事后描述性阈值检查；PS没有加入BS/PM/WG原候选池，也没有重选出一个新策略，不据此提出优化策略的性能结论。', '',
              '## 命题含义与界限', '',
              '严格队列下 P 没有来自非P pending任务的逻辑前驱；保持原 P 子序列后，其原本的逻辑、输入与 CPU 约束只会保持或提前。因此每个受保护任务不晚于 matched strict no-fault。此命题允许未知工作误差，条件是 paired worlds 使用相同实际工作且不含控制暂停或跨任务传输争用。', '',
              '零 CDI 表示没有正向开始延误；它允许更早开始，也不限制失败锥或 workflow completion 的代价。分析同时保留 protected signed/absolute displacement、p95 delay 和 completion tails。', '',
              'skip-unready 会让非P任务绕过未就绪的 P，消耗随后就绪的 P 所需 CPU；此时严格顺序证明不再适用。独立最小反例和完整 factorial 共同说明这一边界。', '',
              'Stable partition 可在预计算 membership sets 后实现线性复杂度；当前已注册 Python 实现保留原代码，不据此宣称已验证线性总耗时。记录的 fixed-plan execution wall time 也不等于包含 B0 construction 的端到端调度开销。', '',
              '## 执行与完整性验证', '',
              f"- 新执行：{receipt['new_exploratory_executions']:,}；新确认性样本：0；参考记录重用：{receipt['reused_reference_records']:,}。",
              f"- 已保存再重开的独立事件检查：{receipt['independent_persisted_events']:,}；独立复算字段：{receipt['independent_metric_fields']:,}；整数迁移检查：{receipt['budget_checks']:,}。",
              f"- strict protected task start 正向偏移超过 1e−8 的数量：{receipt['strict_protected_task_delays_above_1e_minus_8']}；全部 optional moves 为0。",
              f"- 独立统计复算：{data['independent_statistics']['checks']} checks，最大绝对差 {data['independent_statistics']['max_abs_difference']:.3g}。",
              '- 执行前21项正确性测试通过，包括20个独立生成的DAG以及预测/实际工作不一致条件。',
              '- compact first-case replay：4验证执行，无需旧大型事件档案；其结果与已保存 PS 指标、计划和上下文一致。', '',
              '全部科学日志位于 `revision_r5/events/`；原协议、源输入和执行前控制实现的 SHA256 在 `registration.json`；新汇总在 `analysis/results.json`；可用 `python3 -m revision_r5.replay_control --cases all --output replay.json` 从 compact ledger 重新执行全部PS比较（另加匹配reference）。', '',
              '本轮是针对审稿新发现的探索性机制分析，不能回写成预注册确认性发现。实验覆盖仍为六个固定拓扑、同时到达、单节点永久故障及无跨任务传输争用。公开工件存档、外部复现与实际投稿不由本地 PASS 状态代替。', '']
    (OUT / 'reports').mkdir(exist_ok=True)
    (OUT / 'reports/R5_ProtectedSubsequence_探索性对照验收报告.md').write_text('\n'.join(lines))
    timing_scope = 'Fixed-plan PS intervention execution; excludes B0 construction. No measured end-to-end linear-time claim.'
    dump(OUT / 'reports/receipt_wording_correction.json', {'kind': 'PRESENTATION_ONLY',
         'source_receipt_sha256': sha(OUT / 'execution_receipt.json'),
         'field': 'timing_scope', 'replacement': timing_scope,
         'reason': 'The registered runner described the abstract partition as linear; its Python comprehension repeats a set difference. Registered source and execution receipt are preserved. Counts and scientific outcomes are unchanged.'})
    dump(OUT / 'reports/stage_acceptance.json', {**receipt, 'status': 'R5_EXPLORATORY_CONTROL_PASS',
        'independent_statistics': data['independent_statistics'], 'registered_sources_unchanged': True,
        'new_confirmatory_samples': 0, 'submission_status': 'NOT_SUBMITTED',
        'timing_scope': timing_scope, 'post_hoc_feasibility': feasibility['overall'],
        'analysis_sha256': sha(OUT / 'analysis/results.json'), 'new_exploratory_executions': 2880})
    print('R5 report written')


if __name__ == '__main__': main()
