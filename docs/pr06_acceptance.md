# PR-06 不完整候选生命周期及独立预校核（方案 A）

## 设计决策

V1 允许保存**部分完成**的候选设计，前提是至少已有一个真实的设计变量，系统不会为缺失的宽度、间隙、材料或润滑油伪造默认值。StateManager 在落库时计算并覆盖 `unresolved_parameters` 与 `completeness_status`（PARTIAL / COMPLETE），不信任 Agent 提交的完整性声称。

## 原子写入

生成候选的 LangGraph Task 必须处于 RUNNING，`expected_input_digest`、状态版本及输出引用要匹配。Runtime 只接受自己的 DesignAgent 提交的单一候选新增 patch，检查不得夹带参数、约束、角色、规则集变更；由 SYSTEM 授权的 `StateManager.commit_candidate_task` 在一个 CAS 事务内写入候选与完成任务，并保存操作证据。重复相同意图返回原有收据，冲突意图、旧版本、不匹配依赖必须拒绝。

## 校核流程

`ValidationAgent.evaluate` 是独立、只读的校核计算服务，不属于设计 Agent 自评。根据权威 DesignState 和指定 CandidateDesign：

1. 验证 R2 可信固定输入、单稳态工况及适用轴承类型；
2. 统计设计变量缺项及状态/单位有效性；
3. 对必需覆盖规则逐项检查 `ACTIVE`、适用性、输入与来源版本；规则缺失不能因空列表形成 PASS；
4. 评价已批准的用户硬约束；明确区分软约束；
5. 仅有充分且全部为 PASS 的有效校核证据才允许 PRECHECK_PASS；明确违反硬约束/规则返回 PRECHECK_FAIL，未知与缺失返回 REVIEW_REQUIRED。

校核报告携带规则结果、输入摘要、候选 ID+版本、规则集版本、缺失项、未覆盖规则及来源证据；通过 `StateManager.record_candidate_precheck` 的可信 SYSTEM 写入边界保存，拒绝旧快照、失效候选和不完整但冒充 PASS 的报告。

## 确认门禁

部分完成或校核未通过的候选仍可展示、继续补全或生成后续版本，但确认网关不得将其接受为已完成工程方案。现有任务确认协议依旧不直接把 CandidateDesign 设置为 CONFIRMED；后续正式用户确认需专用 API 和审计。

## 默认数据与工程限制

默认知识库中 GB/T 21466-2024 草案仍是 `DRAFT_EXTRACTED`，没有已激活的专业数值门限。本 PR 的 `RuleCoverageSpec` 是需要具备的能力标签，不声称草案数值经过专家审批。默认结果通常为 REVIEW_REQUIRED，不代表可以完成实际工程验收。没有 DLAP 油膜压力、热平衡、最小膜厚计算。

## 运行验收

```powershell
python -m pytest -q tests/design
python -m pytest -q
python -m ruff check .
python -m pip check
git diff --check
```

测试包含：部分候选入库、缺失变量和版本依赖、伪造 COMPLETE / PASS、旧状态拒绝、来源保护、修改输入后 STALE、Agent 禁止混合写入、LangGraph 原子提交和未校核候选确认拒绝。全量 CI 在 Linux Python 3.11 和 Windows Python 3.14 执行。

## 验收定义

**SOFTWARE_ACCEPTED / DOMAIN_PENDING**：通过 CI 表示规则及候选生命周期机制就绪；真正的专业数值、标准审核、性能求解及工程有效性仍待后续实施和专家验证。
