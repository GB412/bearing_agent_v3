# PR-02B 验收记录

状态：`SOFTWARE_ADAPTER_IMPLEMENTED`。代码、离线回归及 CI 已通过；真实 API
接入曾由用户手动验证，但**预算修复后的 B01–B07 真实模型实验仍待重新运行**。
本阶段只验证调度决策，不提供轴承工程计算正确性或设计合格证明。

## 已实现

- 实际调用需要 `BEARING_LLM_ENABLED=true`、`BEARING_LLM_API_KEY`、`BEARING_LLM_BASE_URL`、`BEARING_PLANNER_MODEL`；默认保留 FakePlanner 离线模式。
- 模型仅能提交 `action` 和 `rationale`；可信目录补全执行者、版本及确认标志，仍由 PolicyGuard 独立裁决。
- `json_mode` + Pydantic 严格校验，最多一次 Planner 重试；SDK 内部重试为零，单次请求超时 120 秒。未知动作、权限注入及解析失败均受控处理。
- PlannerContext 只承载摘要、目录、近期失败及预算；缺省预算为 `null`，不能误判为零。
- 模型原始消息仅用于提取 token usage，逐轮 trace 只存放许可的非敏感审计字段；无法取得的 usage 明确标为 `unknown`。

## 可核对的离线证据

`pytest`、`ruff check .`、`pip check` 在 GitHub Actions 的 Linux 3.11、Windows 3.14 上执行。单测覆盖结构化输出、无效动作、错误恢复、权限/版本守卫、Runtime、实验预算 12/3、计量及逐轮审计。

## 历史真实模型实验（预算缺陷修复之前）

用户在 2026-10-25 手动调用 DeepSeek 的 `deepseek-v4-pro`：
- API 连接与单次真实 LLMPlanner 测试成功，缺载荷时正确选择 `clarify_requirement`。
- LangGraph 演示包含多次动作规划、一次 `MISSING_CONFIRMATION_TARGET` Guard 阻断，最终 `GOAL_REACHED` **仅代表 DEMO_ONLY 摘要完成**。
- 当时 B01–B07 返回 7/7 合法提案、6/7 符合 oracle、6 次 ALLOW 与 1 次 NEEDS_USER；B03 的输入上下文意外传入零预算，因此**该匹配率不是修复后的模型质量结论**。
- 用户另用中转站模型做了 B03 小样本尝试；该尝试不足以建立供应商模型能力排名。

## 最新代码的真实模型验收：待补证据

`examples/pr02b_real_experiment.py` 现在为每个独立 fixture 明确传递 `remaining_steps=12`、`remaining_errors=3`，并记录动作、oracle 匹配、Guard 裁决、拒绝计数、规划匹配率和 `planning_acceptance`。
本仓库没有附上修改后、可独立核对的真实 API 请求输出，故不宣称最新版本达到 7/7 或稳定性标准。

手动执行：

```powershell
python examples/pr02b_real_experiment.py ".venv/pr02b_real_retest.jsonl"
```

须检查 JSONL 的 `planner_oracle_match_rate`（输出 summary 中字段名为
`planner_oracle_match_rate`）、`planning_acceptance` 与每轮 `guard_verdict`。
`REAL_LLM_VALIDATED` 仅表示 API/结构化提案通过，`planning_acceptance` 才表示
独立的 **≥85% 小样本研究原型参考线**；两者都不能替代专业设计审查。
如有真实结果，先脱敏审核后再把实验摘要与使用的 Prompt SHA、模型 ID、
动作目录哈希写入记录，禁止上传密钥或原始敏感数据。

## 边界与下一阶段

PR-02B 不包含专业 RequirementsAgent、RAG/ISO 规则、DLAP、真实候选写入或 UI。
FakeAgent 输出保持 `SYNTHETIC_WORKFLOW/DEMO_ONLY`；真实需求澄清由 PR-03 开发。
