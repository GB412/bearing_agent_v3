# 给 Codex 的项目执行指令（复制本文件内容即可）

你现在是 `GB412/bearing_agent_v3` 仓库的**分 PR 实施工程师**。当前项目是“面向圆柱径向动压滑动轴承的初步方案生成、规则预校核与可追溯交互系统”，不是已完成性能验证的自动设计系统。所有工作按已确认的 **V3.4 全阶段 PR 计划**执行。

## 先读取这些资料

1. `docs/planning/滑动轴承多Agent系统_全阶段PR实施总计划_V3.4.md`（或者我放入仓库的同名文件）——本次最高优先级的具体实施与验收总计划。
2. `docs/planning/滑动轴承多Agent系统_正式架构与实施方案_V3.3.md`——总体架构和工程 S0–S8 业务边界。
3. `docs/planning/V3.3_四类核心协议冻结与迁移规范.md`——四类协议语义。
4. `docs/planning/V3.3_PR-02_Codex执行规格.md`——原 PR-02 技术规格；如有冲突，以 V3.4 明确的修改和已批准的现有工程契约为准。
5. 仓库中已有 `docs/architecture_decisions.md`、PR-01 模型和回归测试。

如上述文件不在当前工作目录，请先清楚报告哪些文件缺失，并使用用户提供的文件或要求其放入工作目录；**不要声称已经读过不存在的文件，更不要根据文件名猜测内容**。本指令和总计划是开发规格，不是已实现代码。

## 本次只能实施 PR-02（不要提前写 PR-02B~PR-09）

目标：在 PR-01 的 `DesignState/StateManager/SQLite` 基础上，建设 **可恢复、具备状态感知和执行守卫的 LangGraph FakePlanner 执行骨架**。禁止实现真实 LLMPlanner、真实专业 Agent、ISO 规则抽取、几何设计推荐、DLAP、正式 UI 或完整长期记忆。

### 第 0 步：先审查，不要直接改代码

- `git fetch origin`，确认 `main` 的当前 HEAD SHA、开放 PR 和现有工作树改动。不能自动覆盖我已有未提交文件。
- 核对 `pyproject.toml`、`domain/agent_protocols.py`、`domain/state.py`、`domain/proposals.py`、`domain/enums.py`、`domain/write_context.py`、`core/state_manager.py`、`core/dependency_tracker.py`、实际 SQLite repository 代码和现有单元测试。
- 给出 **1 页以内**的执行计划：要修改的文件、要复用的类、协议冲突、LangGraph/checkpointer 选型及锁定版本、F01–F12 的测试入口。重点核实：
  1. `TaskRecord.dependencies` 当前被当作字段依赖，而任务拓扑必须另用 `depends_on_task_ids`；数据消费另用 `consumed_input_refs`。
  2. `DesignState.task_plan` 已存在，但 `StatePatch` 当前没有受信任务状态写入入口；需要最小兼容地补齐，严禁跳过 StateManager 直接写 repository。
  3. 用户确认与状态来源不能由 Agent 自报 `USER/CONFIRMED` 获得权限。
- 发现与 V3.4 不一致的仓库事实，请先列出；优先以当前已通过测试的领域契约为基础做最小兼容变更。

### 第 1 步：按三个检查点逐步编码、逐步运行测试

**02-C0：协议冻结/依赖迁移/受信任务生命周期**
- 兼容原 `PlanDecision/AgentResult/TaskRecord/StatePatch`；需要才新增 `ActionSpec/GuardDecision`。
- 明确任务前置依赖与输入数据版本依赖，旧 `dependencies` 保守兼容，不发生错误失效。
- 增加任务创建、任务状态变化、计划修订的受信 StateManager 写入通道；保证 CAS、审计、操作幂等。
- 固定六类可信用户事件的语义，但本 PR 不开发真实聊天/UI。
- 跑全部 PR-01 回归；若失败，先修复 C0 再向下开发。

**02-RUNTIME：真实 LangGraph 图 + 状态驱动 FakePlanner**
- `GraphState` 只保存 design/task/version 等编排引用；持有真实工程事实的仍是 `DesignState`。
- Implement `StateObserver → FakePlanner → PolicyGuard → Dispatcher(FakeAgent) → ResultValidator → TrustedCommitter → Observe/Wait/Stop`。
- FakePlanner 至少对缺 F、R2 已就绪、已有候选、等待确认、请求仿真等返回有差异且合法的动作。
- 不允许 FakeAgent 把 `AgentResult.SUCCESS`、模型声称的 `source=user` 解释为工程通过或用户批准。
- 实现有界重试、无进展停止和结构化 action/guard/commit trace。

**02-RECOVERY：checkpoint、中断恢复与业务效果幂等**
- 使用实际持久 LangGraph checkpointer；InMemorySaver 只能用于单进程单测。
- 受信 Domain SQLite 同一业务事务内保存 operation 去重记录、领域状态修改和事件；重复 operation_id 不再次修改工程状态。
- 测试：DB 已写但 Graph checkpoint 未写时恢复、**使用 PR-01 已有参数确认接口或受信任务命令**验证重复 resume 的领域效果幂等、等待期间目标版本变更后旧确认过期。**不要在 PR-02 实现正式候选确认领域命令；PR-02 只冻结候选确认的语义、版本和过期守卫，PR-07/08 再实现正式接受/拒绝。**
- 至少提供一个真正**跨 Python 进程**的恢复集成测试。

### 第 2 步：严格的 PR-02 验收

按 V3.4 第 4 节 **F01–F12** 每个场景运行测试并记录 trace。至少包括：空任务、缺 F、R2 已就绪的动态路线、Agent 伪造 CONFIRMED 和 USER 硬约束、非法动作/执行者、旧版本、依赖语义兼容、过期确认、重复批准、业务写入已提交而 checkpoint 失败、无进展/未接入仿真。

运行整个仓库的 `python -m pytest -q` 和 `ruff check .`（如仓库约定不同，记录实际等价命令），确保 PR-01 权限/来源/版本测试全通过。不能跳过失败测试来获得绿色结果。

### 第 3 步：提交 PR，并在审阅点停止

- 推荐分支：`feat/pr02-langgraph-runtime`。按 C0/RUNTIME/RECOVERY 形成三个可审查的 commit（实际拆分可依实现合理调整）。
- 提交当前 PR 的 diff、运行命令、F01–F12 逐项通过/失败表、两个独立进程恢复证明、幂等结果、最新 main 和当前提交 SHA、已知限制。
- 若有权限，创建 PR；否则提交分支并提供明确的变更和 PR 文案。**不要自动合并 PR；不要自动开始 PR-02B 或之后任务。**
- 如果某个范围内的关键难点不能完成，明确 `BLOCKED`，保留测试和问题说明，不将未实现能力写作完成。

## 后续路线（不是当前执行指令）

PR-02 审核通过后才实施 PR-02B：真实 LLMPlanner；然后 PR-03：多轮需求引导；PR-04：标准/规则/工程表；PR-05：初步方案；PR-06：受信预校核；PR-07：动态修订；PR-08：UI/报告；PR-09：实验评估。D0 专业资料核对和合成案例可以并行，由用户联系组内审核者。完整范围、准入/退出、测试场景和双轨验收全部在 V3.4 主计划中。

**最终声明**：PR-02 完成只意味着可靠的 FakePlanner 执行骨架已实现；不意味着总控真实智能性、ISO 已审规则、真实初步推荐或 DLAP 性能验证已实现。
