# PR-02B 验收记录

状态：`SOFTWARE_ADAPTER_PENDING`；真实模型实验在配置可用 API Key 和网络前为
`REAL_LLM_PENDING`。本 PR 只验证编排动作提议，不提供专业设计或性能结论。

## 实现范围

- `LLMPlanner` 使用 OpenAI API 的 `langchain-openai` 可选依赖；默认离线路径仍为 `FakePlanner`。
- 模型只输出 `action` 与 `rationale`。executor、state version、确认标志和结果语义由可信目录及 Runtime 补全。
- 结构化输出使用严格 Pydantic schema，最多一次重试；未知 action、额外字段、非法 JSON、超时和 API 错误均受控失败。
- PlannerContext 只包含状态摘要、动作目录摘要、最近最多三条失败信息和剩余预算。

## 离线证据

`tests/orchestration/test_llm_planner.py` 覆盖合法提案、未知动作、额外字段、空理由、模型失败、权限注入、Runtime 集成和 Guard 阻断；现有 PR-02 全量测试保持不变。

`python examples/pr02b_real_experiment.py [output.jsonl]` 定义 B01–B07 并记录模型配置、提案、Guard 结果、原因码、重试、延迟和 token 字段。本环境没有 API Key，脚本会报告 `REAL_LLM_PENDING` 且不发起调用。

固定场景 B01–B07 的真实实验记录应包含模型 ID、Prompt/schema/catalog 版本、提案、Guard 结果、原因码、延迟和 token 使用量。缺少凭据时不得用 StubModel 宣称真实验证完成。

## 边界

不包含专业 Agent、RAG、ISO 规则、DLAP、真实候选写入或 UI。FakeAgent 结果仍为 `SYNTHETIC_WORKFLOW/DEMO_ONLY`。
