# PR-05 工况分析与初步设计 Agent

## 目标

在既有 Supervisor / LangGraph Runtime 中注入确定性的 DesignAgent，完成首版滑动轴承的工况信息整理、基础派生量计算、专业知识检索、设计策略整理，以及基于 ACTIVE 数表的候选参数提案。

## 已实现能力

- `analyze_conditions`：复用 R2 权威 readiness；仅对当前支持的油润滑圆柱径向动压滑动轴承分析；计算轴颈表面速度；只有宽度已提供时才计算平均投影比压。
- 每个派生量都携带单位和物理含义说明。平均投影比压明确不等于局部最大油膜压力。
- 从 PR-04 知识仓库检索计算方法、模型假设、流态、不确定性和许用参数的资料摘要，并保留文献编号、版本、章节引用。
- `build_strategy`：列出设计变量、已激活规则、未激活规则和所需依据。
- `propose_candidate`：只消费 ACTIVE 规则及经过来源版本核对的 ACTIVE 表格；没有有效表格命中时返回 INSUFFICIENT_RULES，不编造参数。
- Runtime 通过现有 `conditions_fake` / `design_fake` 注入点执行 DesignAgent，并将结构化输出暴露给调用方。
- NEEDS_REVIEW / INSUFFICIENT_RULES 是可解释的业务结果，不作为 Agent 崩溃处理。

## 明确边界

- 不自动启用 GB/T 21466 草案数值；当前默认知识库无 ACTIVE 数值表，因此默认会得到 INSUFFICIENT_RULES。
- 不生成或持久化正式 CandidateDesign；本 PR 输出的是候选提案，尚未达到可确认的正式候选状态。
- 不修改用户固定输入、约束或 DesignState；不绕过 StateManager。
- 不做油膜压力分布、最小膜厚、温度场、热平衡求解，不调用 DLAP。
- 不把表面速度、平均投影比压单独用作 PASS/FAIL 工程阈值。

## 验收场景

1. R2 不就绪时返回 NEEDS_REVIEW，并明确列出缺失项。
2. R2 就绪时计算表面速度，单位为 m/s。
3. 未提供宽度时不计算平均投影比压。
4. 提供宽度后，计算 F/(D*B)，并明确其不是局部最大油膜压力。
5. 默认知识库中的草案规则/表格不能产生数值推荐。
6. 没有 ACTIVE 表格命中时返回 INSUFFICIENT_RULES 和未解决设计变量。
7. DesignAgent 可通过既有 LangGraph Runtime 注入执行，结果可在 Runtime 输出中读取。
8. PR-01～PR-04 全量回归、Ruff、pip check 和 git diff --check 通过。

## 执行命令

```powershell
python -m pytest -q tests/design tests/orchestration
python -m pytest -q
python -m ruff check .
python -m pip check
git diff --check
```

## 验收声明

PR-05 通过表示确定性工况分析与基于审核数据的候选提案机制已接入现有 Supervisor。它不表示当前默认资料已足以给出完整工程设计方案；默认草案数据全部未激活，因此必须如实返回 INSUFFICIENT_RULES。正式 CandidateDesign 创建和用户确认仍需在后续阶段通过受控写入边界完成。
