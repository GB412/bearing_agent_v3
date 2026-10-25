# Codex PR-02B 启动指令（复制文本内容给 Codex）

## 第一条：Plan 模式，只做核验与简短计划

```text
请进入 Plan 模式，当前只规划 PR-02B：真实 LLMPlanner 的最小可靠性验证，不修改文件。

仓库：GB412/bearing_agent_v3。PR #5 已合并，但必须重新核对实际 main HEAD、工作区状态和最新 PR。

请阅读：
1. docs/planning/PR-02B_真实LLMPlanner实施与验收规格_V1.0.md
2. docs/planning/滑动轴承多Agent系统_全阶段PR实施总计划_V3.4.md（第 5 章 PR-02B，及通用安全契约）
3. docs/protocols/orchestration_contract_v1.md
4. docs/pr02_acceptance.md
5. src/bearing_agents/orchestration/contracts.py、workflow.py
6. src/bearing_agents/domain/agent_protocols.py、pyproject.toml、现有 tests/orchestration/

不要重新实现 LangGraph、Guard、StateManager、任务数据库或检查点恢复机制。

请输出一页以内的 PR-02B 计划：
- 选择一个模型提供方/接入方式及需要的环境变量（不要求提供密钥内容）
- 最小新增/修改文件和代码路径
- 模型只输出动作提案，可信代码补成 PlanDecision 后进入原 Guard 的方式
- StateSummary 尚无 recent failures/budget 时的最小兼容处理
- B01–B07 固定 fixture、外部动作 oracle、离线异常/越权测试
- 真实模型试验的记录方法与无 Key 时的明确未完成状态
- 按 C0→C1→C2 的验收步骤及不做事项

完成 Plan 后停止，不要自动实施。
```

## 第二条：正常 Agent 模式，Plan 审阅后执行

```text
PR-02B 的实施 Plan 已确认。请切换到正常 Agent 执行模式，基于最新 main 创建 feat/pr02b-llm-planner 分支，只实施 docs/planning/PR-02B_真实LLMPlanner实施与验收规格_V1.0.md。

必须遵循：
1. 优先复用 Runtime(planner=...)、PlanDecision、CATALOG、policy_guard、FakeAgent 和已有 SQLite/checkpoint；不建新图、不重写受信状态入口。
2. 只实现一个真实模型接入路径 + 最小结构化 PlannerProposal + LLMPlanner。保留 FakePlanner 和全部离线测试。
3. 模型不能提交 USER 权限或工程 patch。非法 action/schema/超时/注入明确失败；不得静默回退 FakePlanner 假装真实模型成功。
4. 当前不实现真实 RequirementsAgent、DesignAgent、ValidationAgent、ISO 规则、RAG、DLAP、候选值生成或 UI。
5. 对 B01–B07 建立固定离线 fixtures 和独立 oracle；注入 StubModel 测错误输出、恶意动作、R2 阻断和模型调用失败。
6. 给出 Prompt 哈希、模型 ID、动作目录版本、重试策略、Guard 结果与少量脱敏 trace。凭据只能从环境变量读，不能写入仓库或日志。
7. 如果当前环境具有可用的模型 API 访问权限，按预定 fixture 运行受控真模型试验并保存元数据；如果没有，明确 REAL_LLM_PENDING，不要凭空宣称完成，也不要要求把密钥粘贴到聊天中。
8. 运行全量 pytest、ruff、pip check、git diff --check；确认远端 Linux 3.11 / Windows 3.14 CI 通过。
9. 新建独立 PR，附 docs/pr02b_acceptance.md、代码变更、失败案例、准确的真实试验状态与使用说明；停在审阅，不自动合并，不继续 PR-03。

请先报告确认后的拟改文件和不会做的事项，再直接实施。遇到阻断或确需改变核心协议时，在 PR 报告中明确说明，不要擅自扩大范围。
```

## 给项目负责人：运行前两项准备

- 先把 `PR-02B_真实LLMPlanner实施与验收规格_V1.0.md` 放进仓库 `docs/planning/`，只需这一份新的 PR 专项规格；旧 PR-02 规格保留作为历史记录，不必删除。
- 确定能实际调用的**一个** LLM 服务（如 OpenAI API 或你已有权限的兼容服务），并在本地受控环境配置凭据。**Codex 登录或 ChatGPT 订阅不代表已具备模型 API 凭据/额度**。若暂无 API 访问，先完成离线适配与测试，随后补真模型实验，不应宣布 Gate B 完成。
