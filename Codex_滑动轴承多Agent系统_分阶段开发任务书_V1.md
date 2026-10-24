# 交给 Codex 的分阶段开发任务书 V1.0

> 项目：面向初级设计人员的滑动轴承多 Agent 辅助设计系统
> 方案负责人：ChatGPT（架构规划、接口、验收）；开发执行：Codex（代码实现、运行测试、提交报告）
> 最小范围：圆柱径向、油润滑、动压型滑动轴承；先支持单一明确的稳态工况、新设计任务以及当前方案的修改。
> 不做 DLAP：只定义仿真接口，返回 NOT_AVAILABLE，绝不虚构膜厚、温度或压力仿真结果。

## 0. 不得改变的架构约束

1. Python 3.11+；采用 `LangGraph` 编排，专业 Agent 优先采用 LangChain `create_agent` 或简单、可测试的模型调用封装；不要额外引入 Pi Agent、AutoGen、CrewAI 等第二套 Agent 运行时。
2. 本期运行 4 个角色：Supervisor（智能总控）、RequirementAgent（需求）、DesignAgent（方案）、ValidationAgent（预校核）。SimulationAdapter 仅预留接口，不算已实现的计算能力。
3. Supervisor 不是固定四意图路由器：根据当前 `DesignState` 提出 `PlanDecision`，由确定性的 PolicyGuard 审核动作，执行后重新观察状态并可局部重规划。
4. 使用现成 Checkpointer/Store 等框架能力持久化会话；不另造通用记忆系统。**领域设计状态必须结构化保存**，不能单纯保留在聊天历史中。
5. 语言模型负责语义提取、专业解释、候选方案与下一步规划；单位换算、物理公式、硬约束、动作守卫、来源与批准状态由确定性代码处理。
6. 每个专业 Agent 返回结构化 Result/StatePatch，不得直接无限制覆盖共享数据；StateManager 应验证来源、状态版本和写入权限。
7. 无经审核的工程规则时，系统输出 `NEEDS_REVIEW` 或 `INSUFFICIENT_RULES`，而不是编造几何、温度、膜厚、许用比压和润滑油推荐值。
8. 源标准包括 2024 中文草案 07—13 和 SC8-ISO PDF 参考。07（圆柱计算原理）、09（许用运行参数）优先；08（特征值）第二阶段；10—13 暂存。草案 ≠ 已核验现行标准。原文件应只读保存，不把受版权限制的标准正文写入代码仓库。
9. 关键用户确认通过 LangGraph 的 `interrupt()` 和同 `thread_id` 的 `Command(resume=...)` 实现；避免在中断节点重复执行带外部副作用的操作。
10. 禁止自动宣称“轴承合格”：无 DLAP 的版本仅能给出 `PRECHECK_PASS`，性能指标返回 `NOT_EVALUATED`。

## 1. 统一模块合同（各阶段共同遵守）

### 1.1 最小领域数据模型

在 `src/bearing_agents/domain/` 建立 Pydantic v2 数据模型：

- `DesignState`: `design_id`, `state_version`, `thread_id`, `target_scope`, `user_goal`, `operating_cases`, `parameters`, `constraints`, `assumptions`, `candidate_designs`, `issues`, `task_plan`, `knowledge_rule_set_version`, `confirmations`, `simulation_status`, `event_log_refs`。
- `ParameterRecord`: `parameter_id`, `value`, `unit`, `role`（`FIXED_INPUT|HARD_CONSTRAINT|DESIGN_VARIABLE|DERIVED`）, `status`（`MISSING|PROVIDED|CONFIRMED|SUGGESTED|CONFLICT|UNAVAILABLE|NOT_APPLICABLE`）, `source`, `source_ref`, `applies_to_case`, `confirmed_by`, `revision`。角色和确认状态必须分离。
- `OperatingCase`: 工况 ID、轴径/载荷/转速的引用、载荷方向、稳态属性、说明；即使首版只用 1 个工况也采用列表结构。
- `ConstraintRecord`: `id`, `parameter`, `operator`, `target`, `unit`, `severity`, `origin`, `approved`, `scope`, `rule_ref`；用户硬约束与经验推荐不混为一谈。
- `CandidateDesign`: `candidate_id`, `version`, `parent_candidate_id`, `parameters`, `assumptions`, `source_parameter_revisions`, `rule_refs`, `confirmation_status`, `precheck_status`, `simulation_status`。
- `IssueRecord`: `code`, `severity`, `affected_fields`, `explanation`, `status`, `suggested_actions`, `rule_refs`。
- `TaskRecord`: `id`, `action`, `agent`, `status`, `dependencies`, `input_version`, `output_ref`, `attempt_count`。
- `PlanDecision`: `action`, `selected_agent`, `input_refs`, `rationale`, `expected_result`, `requires_confirmation`, `state_version`。
- `AgentResult`: `task_id`, `status`, `state_patch`, `issues`, `suggested_next_actions`, `evidence_refs`。
- `RuleRecord`: `rule_id`, `source_document`, `section`, `scope`, `inputs`, `operation`, `status`（`DRAFT_EXTRACTED|SOURCE_CHECKED|EXPERT_APPROVED|ACTIVE`）, `version`, `reviewer`, `tests`。

若实现发现以上字段存在合理的重构需求，Codex 需先在 `docs/architecture_decisions.md` 说明，不得默默删除约束/来源/确认相关字段。

### 1.2 工程单位与计算定义

- 必须区分轴颈直径、轴承孔径、**径向间隙**、**直径间隙**及**间隙比**。
- 所有计算使用清晰的单位约定或现成单位库；保留用户原始输入与归一化数值，禁止隐式单位猜测。
- 首批确定性工具：`journal_surface_speed(diameter_mm, speed_rpm)` 返回 m/s；`projected_mean_pressure(load_N, diameter_mm, width_mm)` 返回 Pa（仅在几何和适用条件满足时）。
- `p_m=F/(D*B)` 是径向投影平均比压初算，不等同油膜局部最大压力。
- 错误输入（负直径、未知单位、缺值、冲突）必须报告错误，不得默认为 0。

### 1.3 数据写入和版本

- 单个 Agent **只提出** StatePatch；状态管理器统一校验并提交，提交后 `state_version` 递增。
- 当轴径/载荷/转速/材料/限值改变，使用字段依赖表将受影响派生指标、候选方案、校核结果标记 `STALE`；保留历史而不是删除。
- 所有设计结论记录规则版本和来源引用；禁止未批准的草案规则直接输出正式合格结论。
- 先实现串行提交即可；但必须对旧 `state_version` 的写入产生冲突提示，而不是覆盖新数据。

## 2. 开发任务 PR-01：工程骨架 + 领域状态（立即执行）

**目标**：完全不调用 LLM、没有 API Key，也能运行测试，生成/修改/保存/读取轴承设计任务。

**Codex 需创建：**

```text
pyproject.toml
README.md
.env.example
src/bearing_agents/__init__.py
src/bearing_agents/domain/{enums,parameters,operating_cases,constraints,candidates,state,events,agent_protocols}.py
src/bearing_agents/core/{state_manager,unit_normalizer,dependency_tracker}.py
src/bearing_agents/tools/engineering_calculator.py
src/bearing_agents/infra/state_repository.py
tests/{test_domain_models,test_units,test_dependency_tracker,test_state_manager}.py
docs/{architecture,decision_records,open_questions}.md
```

**必须实现的操作：**

1. `create_design()`：创建空设计，目标结构默认标记 `cylindrical_radial_hydrodynamic`，不自动填任何载荷、直径或工况数值。
2. `apply_patch(design_id, expected_version, patch)`：写入新参数/修改状态，记录来源、确认信息、时间及状态版本；拒绝未授权修改固定输入。
3. `get_design(design_id)`：读取权威设计状态。
4. `list_missing_for(stage)`：针对当前设计分支返回待解决的缺失项及理由；不要硬编码成所有字段必填。
5. `invalidate_dependents(changed_fields)`：返回并标记受影响对象；最低覆盖 `D,n -> surface_speed`、`D,B,F -> mean_pressure`、候选和校核结果。
6. `journal_surface_speed`、`projected_mean_pressure` 有正常/边界/非法输入测试。
7. 提供本地 JSON/SQLite 简单持久化（任选一种且文档明确）；此业务数据存储不是重做 LangGraph 的通用记忆。

**验收测试：**

- 100 mm、1500 rpm 的轴颈线速度约 7.85398 m/s；载荷 12000 N、D=100 mm、B=60 mm 的平均比压为 2e6 Pa（仅作为测试算术，不代表工程设计建议）。
- 未知轴径保持 `MISSING`，不能隐式变成 0。
- 宽度作为 `DESIGN_VARIABLE` 且状态 `SUGGESTED`，确认后仍是 `DESIGN_VARIABLE`，状态改 `CONFIRMED`。
- 修改轴径使线速度及使用旧轴径的方案/校核标记失效；无关材料企业约束保持不变。
- 错误单位、负直径、旧版本 StatePatch、未授权固定输入改写均被拒绝。
- `pytest` 全通过，`ruff check .` 通过。README 提供安装和运行方法。

**本任务不要做：** LangGraph 多 Agent 运行、ISO 草案自动解析、规则库数值填充、RAG、正式设计推荐、前端、DLAP、优化器。

**PR 结束提交：** 文件树、技术决策、运行命令、测试结果、剩余问题。

## 3. 开发任务 PR-02：LangGraph 智能总控骨架 + 假 Agent

**前置**：PR-01 验收通过。

**目标**：实现可运行的“观察状态→智能计划→确定性守卫→执行→更新→重规划”闭环。此阶段专门使用 FakePlanner 和 FakeAgent 测试，不依赖在线模型。

**新增目录：**

```text
src/bearing_agents/orchestration/{graph,planner,action_registry,policy_guard,dispatcher,commit,invalidation,approval}.py
src/bearing_agents/agents/{requirement_stub,design_stub,validation_stub}.py
tests/{test_graph_routing,test_guard,test_interrupt_resume,test_replanning}.py
```

**任务要求：**

1. LangGraph StateGraph 至少具有：`observe`, `plan`, `guard`, `dispatch`, `commit`, `approval`, `finish` 节点；允许 `dispatch` 按注册动作路由到专业 Agent 能力，不能只建固定 `Requirement→Design→Validation` 边。
2. `Planner` 用协议抽象，提供 `FakePlanner` 和可替换的 `LLMPlanner` 插槽；LLM 输出严格匹配 `PlanDecision`。
3. ActionRegistry 首批动作：`clarify_requirement`, `analyze_conditions`, `recommend_parameters`, `generate_candidate`, `precheck_candidate`, `revise_candidate`, `request_confirmation`, `generate_report`；`run_simulation` 注册为 `DISABLED`。
4. `PolicyGuard` 验证动作合法、所需输入/权限/版本、规则状态、人工批准是否需要；不通过返回结构化理由，由 Planner 重新规划或向用户请求确认。
5. `interrupt()` 暂停确认，`Command(resume=...)` 从同 `thread_id` 恢复，避免中断节点重复提交修改。测试可用 `InMemorySaver`；实际本地演示改用可持久化后端。
6. `AgentResult` 写回前校验；同样设计状态下重复调用不能无边界循环，支持步骤上限和无进展检测。
7. 显示每次总控选动作的简短原因、当时参数/规则版本及执行结果。

**验收场景：**

- 初始信息缺失 → 总控选 `clarify_requirement`；补齐后可选 `generate_candidate`，无需重新问已确定条件。
- 未经确认的固定条件 → Guard 阻止执行受限任务并触发确认。
- 用户在方案后修改转速 → 旧工况派生值与相关方案预校核标记 `STALE`；总控只重新调度相关动作。
- 禁用的仿真接口 → `NOT_AVAILABLE`，不生成虚构结果。
- 连续无进展 → 有界停止，输出阻断原因。

**本任务不要做**真实专业设计 Agent、RAG 或复杂前端。

## 4. 开发任务 PR-03：需求引导 Agent

**前置**：PR-02 验收通过。

**目标**：用户输入一句模糊需求，系统主动追问直到具备初步方案条件 R2，并保存结构化需求规格 `RequirementSpec`。

**新文件**：`agents/requirement_agent.py`, `domain/requirement_spec.py`, `tools/requirement_checker.py`, `knowledge/parameter_templates.py`, `prompts/requirement.md`, `tests/test_requirement_agent.py`。

**功能：**

- LLM 只做参数语义提取、问题解释、提问措辞；参数单位/冲突/必需项由程序检查。使用结构化输出 schema，不依赖裸文本 JSON 正则解析。
- 建立三级模板：滑动轴承通用 → 径向轴承 → 圆柱径向动压轴承。
- 支持 `R1` 基础工况预分析、`R2` 可生成方案、`R3` 仿真输入完整度（R3 规则当前可标记 `UNSPECIFIED_BY_ADAPTER`，不自行虚构）。
- 问题优先级：P0 冲突，P1 关键外部工况，P2 硬约束，P3 可由设计 Agent 推荐参数，P4 用户偏好。每轮推荐不超过 3 个相互关联的问题。
- 区分：已提供但未确认、已确认、设计变量、未知、无法获得、假设。缺载荷时不可直接猜数值进行正式设计。
- 形成 `RequirementSpec` 和人可读设计条件汇总；关键条件先让用户确认。

**测试：** 用户只说“我要设计齿轮箱滑动轴承”能主动澄清；用户已给轴径/转速不重复追问；宽度未知但有安装上限时转交推荐；关键径向载荷缺失触发追问；动态载荷超出现阶段范围触发说明；用户中途更正轴径能覆盖旧信息并触发版本变化。

## 5. 开发任务 PR-04：标准资料 → 知识/规则/表格的入库流程

**前置**：PR-01 的 RuleRecord 和持久化接口已可用。可与 PR-03 独立实施，但不要同时改同一组模型。

**目标**：建立 ISO 草案的来源追溯和审核管线。不得自动把 PDF/DOCX 的所有内容转成有效规则。

**新增目录：**

```text
src/bearing_agents/knowledge/{source_catalog,clause_index,retrieval,rule_repository,engineering_table_repository}.py
src/bearing_agents/rules/{rule_engine,applicability,precheck}.py
knowledge_sources/README.md
knowledge_sources/metadata/sources.yaml
data/rules/drafts/
data/rules/approved/
data/engineering_tables/pending_review/
tests/{test_rule_lifecycle,test_rule_engine,test_knowledge_provenance}.py
```

**规范：**

1. 建立 07、08、09、10、11、12、13 和 ISO PDF 的元数据清单，原文件请用户手工复制到私有 `knowledge_sources/raw/`，默认不提交到公开 Git。
2. 首批只人工提取 07 草案 §1 范围/稳态适用性、§5 关键假设、§7 参数定义，以及 09 草案 §6 表3、§8 表5 的候选数据；最小膜厚/温度先保存 `deferred_simulation`。文件位置和条款定位必须可追踪。
3. 未审核规则状态 `DRAFT_EXTRACTED`，手工核对原图与对应 ISO 后进入 `SOURCE_CHECKED`，轴承专家审核后进入 `EXPERT_APPROVED`，由明确的发布操作进入 `ACTIVE`；不允许程序无审核直接晋级。
4. 表 5 应制作二维查表仓储，保留轴径/速度分档、区间开闭、比值单位 ‰、来源和例外条件。默认 `pending_review` 时不能用于正式参数推荐，只能进行标注为演示数据的测试。
5. 不要把平均比压阈值错用于油膜局部最大压力；括号中特殊限值不得自动启用。
6. 08、11、12 数值密集表，10—13 非本期轴承类型：只做元数据，不做数值库开发。
7. 对知识段落建立最简关键词 + 章节元数据检索（先不强制向量数据库），输出引用 ID；RAG 返回知识解释，规则引擎返回可执行判断。

**验收**：未审核表不能作为有效设计值；条款查询返回文档编号、版本、章节；规则适用性按轴承类型过滤；100mm/1m/s 等分档边界测试在审核通过的 fixture 上正确；没有检索结果时明确提示来源不足。

## 6. 开发任务 PR-05：方案设计 Agent

**前置**：PR-03 和 PR-04 验收通过。

**目标**：基于确认过的工况和已审核的规则生成候选设计，不直接幻觉出未经证实的几何或润滑参数。

**新文件**：`agents/design_agent.py`, `tools/parameter_recommender.py`, `tools/engineering_table_lookup.py`, `prompts/design.md`, `tests/test_design_agent.py`。

**行为：**

1. 接收 `RequirementSpec`、设计变量权限、可用知识与规则引用。
2. 调用确定性工具计算圆周速度；在候选宽度确定后再计算平均比压。
3. 只调用已 `ACTIVE` 的规则/数据表推荐间隙比、宽度、材料候选；若缺可靠规则，输出缺口清单和待确认假设，不能冒充工程值。
4. 至少支持 `generate_candidate` 和 `revise_candidate`；方案中记录每一项参数的来源、假设、硬约束、父版本及与输入参数的版本关联。
5. 初期生成 1 套主方案，可接受用户请求额外生成比较方案。
6. 可建议但不能自动更改用户指定载荷、轴径、转速、安装限制和限定材料集合。

**验收**：给定工况能正确调用速度工具；限制铜合金时不推荐违背硬约束的材料；间隙比经验值若尚未批准只能显示“尚待审核”，不能成为正式设计依据；方案版本和来源可追溯。

## 7. 开发任务 PR-06：预校核 Agent + 反馈闭环

**前置**：PR-05 验收通过。

**目标**：让系统能检查初步设计条件并引导修改，但不宣称完成真实油膜/热性能仿真。

**新文件**：`agents/validation_agent.py`, `rules/validation_engine.py`, `tools/issue_diagnoser.py`, `tests/test_validation_loop.py`。

**行为：**

1. `precheck_candidate` 输出：`PRECHECK_PASS|PRECHECK_FAIL|REVIEW_REQUIRED|INVALID`；独立记录膜厚/最高温度/局部最大压力 `NOT_EVALUATED`。
2. 首批可靠执行的规则：已确认轴承宽度 ≤ 已确认最大安装宽度；轴承类型适用性；用户允许材料集合；合法几何及必要参数完整性。
3. 其他依据草案的数值阈值必须经过第 04 阶段审核再启用。
4. 结构化输出 `IssueRecord`、相关参数、规则引用、可调整变量、修改建议；将建议交给 DesignAgent 产生新方案并重新预校核。
5. 改动硬约束先求用户确认；可调整变量允许有限自动改动。连续无进展触发停止/人工复核。
6. 输出报告时明确："这是初步设计预校核，不包含 DLAP 仿真性能校核"。

**验收**：宽度超限→提出修改→经允许调整→通过预校核；材料不在允许集合→不能通过；仅预校核通过不能标为 `ENGINEERING_PASS`；参数修改引发的校核重跑是局部的。

## 8. 开发任务 PR-07：前端、报告、演示与对照测试

**前置**：PR-06 验收通过。

**目标**：完整可操作原型，支持暂停/恢复、方案版本、动态总控日志、预校核结果及缺失条件。

**建议**：FastAPI 提供任务/消息/确认/方案/事件 API；首版用 Streamlit 做界面（或前后端已另有现成基础则沿用）。界面至少有聊天、当前参数/约束、总控任务计划、候选方案、预校核、历史版本六块信息。

**示范案例**：

- 案例 A：只给“设计一个齿轮箱滑动轴承”，Agent 主动追问，最终形成有确认状态的需求规格。
- 案例 B：用户给轴径/转速/载荷及宽度上限、材料约束；生成初步方案，发现违反用户约束，给出修正。
- 案例 C：完成方案后用户修改转速；总控重新计算相关派生值，废弃旧方案校核状态，避免重复收集无关条件。

**指标与记录**：按案例保存是否完成目标、关键条件缺失识别、硬约束违规数、重复动作次数、无进展轮数、每次规划的动作和耗时。待稳定后再和固定流程/单Agent 基线比较。

## 9. 通用 Codex 工作要求（每个 PR 都附上）

- 实施前先读 `README.md`、`docs/architecture.md` 和现有模型；列出本 PR 要改的文件与风险。
- 仅实现当前 PR，禁止私自扩展到滚动轴承、静压、多瓦块、可倾瓦、多目标优化和 DLAP。
- 当前 PR 的代码必须在无 API Key 的测试环境下可运行（必要时采用 FakePlanner/FakeModel），不允许把测试建立在真实模型输出的随机性上。
- 所有 schema 输入输出必须类型化，新增行为配 pytest；`ruff check .` 通过。
- 按常规工程约定保证错误可观察，状态变化可追踪，任何失败都不能默认假定通过。
- 执行完成输出：新增/修改文件清单、主要接口、示例运行步骤、完整测试结果、未解决问题、是否达到验收标准。

## 10. 可以直接复制给 Codex 的第一条任务（PR-01）

请为我从零建立“滑动轴承多 Agent 智能设计系统”的 Python 项目，并且**仅完成 PR-01：工程骨架、领域状态、最小工程计算和测试**。不要提前写 Agent Prompt、LangGraph 总控、RAG、UI、DLAP 或自动优化。

研究范围固定：**圆柱径向、油润滑、动压型滑动轴承；先支持单一稳态工况；面向初级设计人员的新设计。** 技术栈 Python 3.11+、Pydantic v2、pytest、ruff，项目使用 src-layout，依赖放在 pyproject.toml 中并锁定兼容版本。

先阅读此任务书第 0、1、2、9 节，严格按说明建立领域模型：DesignState、ParameterRecord、OperatingCase、ConstraintRecord、CandidateDesign、IssueRecord、TaskRecord、PlanDecision、AgentResult、RuleRecord。实现 create_design/get_design/apply_patch/list_missing_for/invalidate_dependents、状态版本控制、来源/确认记录、简单本地持久化，以及 journal_surface_speed 和 projected_mean_pressure 两个确定性计算工具。特别要区分参数的工程角色和确认状态、径向间隙与直径间隙、平均比压与油膜最大压力。单位不明、输入缺失、负值、不合法覆盖等必须返回错误，不能自动猜测。

实现测试：D=100 mm,n=1500 rpm 时 v≈7.85398m/s；F=12000 N,D=100mm,B=60mm 时 p_m=2e6Pa；单位和非法数值校验；确认状态变化；修改轴径触发相关派生值和候选方案失效；旧版本写入被拒绝。测试必须完全离线且不依赖模型 API Key。

完成后运行 `pytest`、`ruff check .`，给出项目文件树、接口说明、示例调用、全部测试结果、你作出的实现选择和剩余不确定问题。如发现领域模型需要修改，请先写入 `docs/architecture_decisions.md` 并说明理由，不能悄悄改变核心合同。

**完成 PR-01 后停止，不要继续 PR-02，等待我验收。**
