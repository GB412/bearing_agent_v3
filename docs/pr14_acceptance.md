# PR-14：引导式交互与可信校核配置一致性

## 目标与审查

基于现有 PR-11～PR-13 实现做最小修复，不新增 Supervisor、Agent、数据库、工作流引擎或 DLAP。工程软件的成功不得冒充真实油膜/温度求解或领域专家验收。

### 修复内容

1. `open_application()` 统一向 Runtime 和 `ValidationService` 注入同一个受信 `ValidationAgent`，避免自定义 KnowledgeBase、规则覆盖配置与结果写入时错位。直接提交外部伪造 PASS 仍需受信二次评估。
2. `observe_state()` 增加**只读、有限长度、非权威**的场景、用户目标和最近自然语言请求提示；Runtime 使用该设计最近已持久化的用户消息，由 LLMPlanner 的结构化请求获得这些提示。大模型只能在 ActionCatalog 中选动作，不能批准约束或改变工程事实。
3. 原有中文 CLI 增加 `:approve 编号` / `:confirm 编号`，映射到用户已经看到的具体对象和版本；提问显示为什么需要，显示至多两个重点问题。保留原有 `:approve ID 版本`、`:confirm 字段 版本` 专家操作；版本被其他写入改变时禁止应用旧编号。

### 质量审查

- Agent 边界不变：Supervisor 规划，RequirementsAgent 提问，DesignAgent 提案，ValidationAgent 校核，StateManager 唯一权威提交。
- **没有**独立偏好数据库、意图记忆引擎、多 Agent 聊天协议、额外状态机、Web 页面、新的专业阈值。
- 当前用户偏好为 `UNVERIFIED_HINT`，不具备 User Confirmation 的工程约束效力。
- 强调真实 API 兼容性仍需用户提供密钥做 PR-15 实际端到端测试；本 PR 不将离线 Stub/单元测试当作真实 LLM 验收。
- 默认 DLAP 不可用，报告仍是 `ENGINEERING_DOMAIN_PENDING`。

### 运行与验收

```powershell
python -m pytest -q tests/application/test_pr14_guided_integration.py
python -m pytest -q
python -m ruff check .
python -m pip check
python examples/interactive_design.py --db .venv/pr14-demo.sqlite
```

CLI 示例：输入“我要设计圆柱径向动压滑动轴承，单一稳态，轴径100mm，载荷12kN，转速1500rpm，轴承宽度60mm”，再输入“轴承宽度不能超过70mm”。输出的 `:approve 1` 允许批准相应待确认约束；`:confirm 1` 确认当前第一条可确认参数。展示中应说明“工程校核尚待专业规则与 DLAP”。

### PR 范围审查

- 此 PR 只解决交互与配置可信一致性，不做自动优化、更多 Agent 或完整专业规则开发。
- 动态规划的更复杂多路径能力在已有 PR-12 单元测试中已有部分证据，真实 LLM 全流程的系统级验收留给经用户授权的 PR-15。
