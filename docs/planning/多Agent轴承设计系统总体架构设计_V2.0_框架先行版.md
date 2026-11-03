# 多 Agent 轴承设计系统总体架构设计 V2.0（框架先行版）

> 文档状态：**架构对齐提案，待项目负责人审阅确认**。本文件用于明确总体运行架构和后续开发顺序；在确认前，不替换 V3.3/V3.4 中已经冻结的领域安全契约、规则审批要求和数据可信边界。
>
> 代码基线：GitHub main，提交 `d78507ff445fc6043d00e58d6a6f5746a5c331ce`（2026-11-02）。
>
> 主要依据：仓库中的《10.13 与郑老师讨论总结》、V3.3 正式架构、V3.4 PR 总计划，以及 PR-01～PR-06 当前实现。本文将“讨论确定的目标”“现有代码事实”和“本次架构建议”分开说明。

---

## 0. 本次架构对齐要解决什么问题

项目已经具备领域状态、受控 LangGraph Runtime、真实 LLMPlanner 接口、需求信息提取、知识/规则服务、初步 DesignAgent 和 ValidationAgent。但这些能力还没有组成一个统一、完整、可扩展的运行框架。

本次不推翻 PR-01～PR-06，也不先追求每个 Agent 都有成熟的专业推理能力。先明确一套稳定的总体架构，使后续专业能力可以逐个增强，而不必反复改 Supervisor、状态模型和 Agent 之间的通信方式。

### 0.1 产品目标

建设一个面向设计经验有限人员的**滑动轴承初步设计辅助多 Agent 系统**。用户可以从一句不完整的自然语言需求开始，由系统主动引导其明确设计目标、工况、约束和边界；系统再结合专业知识、审核规则和工程工具，形成可解释、可追溯的候选方案，完成规则预校核，并在必要时进行有限修订和用户确认。

系统不是普通轴承知识聊天机器人，也不是让大模型直接编造全部设计参数的自动设计器。

### 0.2 首版范围

- 首先支持：油润滑圆柱径向动压滑动轴承、单一稳态工况。
- 用户类型：有基础工程背景，但不熟悉完整轴承设计流程的人员。
- 计算软件：本阶段只预留 CalculationAgent / Solver Adapter 接口，不接入 DLAP，不声称已经完成膜厚、温度场或油膜压力性能求解。
- 后续扩展：其他滑动轴承类型、滚动轴承、更多工况、企业知识与计算工具。

### 0.3 本次架构设计的成功标准

1. 新增一个专业 Agent 时，不需要重写 Supervisor 的主循环。
2. 新增一个工程工具时，可以通过受控注册和权限配置提供给指定 Agent。
3. 同一个 Supervisor 能根据当前状态选择不同 Agent/工具，不依赖唯一固定阶段顺序。
4. Agent 之间通过结构化任务和结果交互，不依赖自由聊天或直接互相修改状态。
5. LLM 只提出计划、解释和候选；Guard、StateManager、RuleEngine 和确定性计算工具保留权威。
6. 同一设计的输入、候选、规则、工具结果和用户决策均可追溯、可恢复。
7. 未来增加轴承类型时，主要新增领域配置、知识规则和专业能力，不复制整套框架。

---

## 1. 总体架构原则

### 原则 1：先完成框架，再深化 Agent 专业能力

框架先具备完整的运行机制、扩展接口和状态边界。首版 Agent 可以先使用简单实现，但其输入输出、任务调度、工具访问和状态提交方式必须符合统一协议。

“框架完整”不等于“所有专业能力已完成”。例如，DesignAgent 初期可以只做基础工况分析和部分候选提案，但框架必须允许后续加入 LLM 推理、知识检索、规则调用、公式工具和求解器。

### 原则 2：Supervisor 动态决策，业务流程不写死

不能把“需求 → 分析 → 设计 → 校核 → 计算”写成所有任务唯一可走的固定流水线。

Supervisor 每次读取最新权威状态、用户目标、任务结果、未决问题和预算，再决定下一项合法动作。用户只想查询某项设计依据时，不必强行运行完整设计流程；必要条件齐全时，也不应重复追问。

动态不是无规则。可执行动作、前置条件、权限、输入输出和停止条件仍由受信目录及 Guard 限定。

### 原则 3：Agent 与 Tool 分工

- **Agent**：负责一类专业任务，需要时可以组合大模型、知识服务、规则服务和多个工具。
- **Tool / Service**：完成边界明确、可复用的工作，例如单位换算、公式计算、规则执行、材料查询、求解器调用。
- **Supervisor**：决定下一步由哪个 Agent 或受控动作处理，不承担具体轴承专业计算。

不是每个计算公式、知识查询或参数管理功能都需要独立 Agent。只有职责独立、需要单独调度或需要独立专业推理的能力，才值得拆成 Agent。

### 原则 4：混合智能，而不是所有模块都调用 LLM

| 工作 | 推荐实现 | 权威边界 |
|---|---|---|
| 理解用户意图、应用场景和自然语言 | LLM | 输出是待核验提案 |
| 规划下一步动作、选择 Agent | LLM Planner | 只能从受信动作目录选择，必须经过 Guard |
| 需求字段提取、问题组织和解释 | LLM + 确定性验证 | 数值、单位、来源、确认状态由程序核验 |
| 工况定量计算 | 确定性工程工具 | 公式、单位、输入版本明确 |
| 设计策略分析和方案权衡 | LLM + 知识库/规则/工具 | 不得凭空产生无依据数值 |
| 参数推荐 | 已审核规则、数表、计算结果；LLM 辅助解释和比较 | 数值推荐必须有来源、适用范围和版本 |
| 标准及硬约束校核 | 确定性 RuleEngine | LLM 不能更改阈值或把 FAIL 改为 PASS |
| 校核问题诊断和修订建议 | LLM + 校核证据 | 只能在允许的设计变量范围内提建议 |
| 专业求解器计算 | 确定性 Solver Adapter | 求解状态、数值结果和工程判定分开 |

---

## 2. 五层总体架构

### 2.1 交互与可信应用层

职责：

- 接收用户自然语言任务、补充信息、纠错、确认、拒绝和取消。
- 保存原始用户消息及消息 ID，支持多轮会话和恢复。
- 将可信用户操作与模型提案区分开。
- 向用户展示追问、当前参数、约束、候选版本、校核结果和执行进度。

当前基础：PR-03 的 InteractionService、UserTurn、证据核验和本地 CLI。

后续扩展：API、Web UI、流式输出和报告界面。UI/API 不能直接伪造 USER 身份或 WriteContext。

### 2.2 智能编排层

核心是一个 Supervisor，基于 LangGraph 实现。

职责：

1. 观察权威设计状态。
2. 形成紧凑的规划上下文。
3. 让 Planner 提出下一步动作。
4. 用 Guard 检查动作、输入、范围、版本、权限和前置条件。
5. 将任务交给注册的 Agent 或工具执行入口。
6. 验证结果并经可信写入边界提交。
7. 重新观察状态，决定继续、追问、等待用户、重规划或终止。

Supervisor 内部应包含清晰职责：

- State Observer：读取权威状态并形成摘要。
- Planner：提出下一步动作和理由。
- Action / Agent Registry：提供允许执行的动作及其元数据。
- Policy Guard：验证动作是否合法。
- Dispatcher：根据受信注册信息找到实际执行者。
- Result Validator / Commit Boundary：校验结果并交由 StateManager 受控提交。
- Checkpoint / Recovery：支持暂停、恢复、幂等和预算控制。

**LangGraph 的图结构可以保持稳定的通用循环；动态性来自每轮规划的动作选择和条件路由，而不是每个用户请求都动态生成一张全新 Graph。**

### 2.3 专业 Agent 层

首版保留四类核心专业 Agent：

| Agent | 核心职责 | 主要输入 | 主要输出 |
|---|---|---|---|
| RequirementsAgent | 任务理解、需求补全、边界识别、追问与确认建议 | 用户消息、当前设计状态、需求规则 | 结构化需求提案、未决项、问题、证据引用 |
| DesignAgent | 工况预分析、风险识别、策略选择、参数推荐、候选方案 | 已核验需求、工况、知识/规则/工具结果 | 分析结果、策略、候选方案及依据 |
| ValidationAgent | 规则校核、问题定位、风险解释、修订建议 | 候选版本、适用规则、计算结果、用户约束 | 确定性校核报告、诊断解释、允许的修订方向 |
| CalculationAgent | 管理专业求解任务、输入准备、求解调用、结果解析 | 已确认的计算配置和候选版本 | 求解状态、结构化计算结果、运行证据 |

材料选型、润滑油选型、报告生成、优化等，首版先作为 DesignAgent 或其他 Agent 内部可调用的能力，不急于拆成更多 Agent。确有独立调度价值时再拆分。

### 2.4 知识与工程能力层

这是 Agent 使用的专业能力，不等同于 Agent 本身。

- 专业知识服务：标准目录、文献摘要、专家经验、材料和润滑油数据。
- 规则服务：规则生命周期、适用性判断、覆盖检查和确定性 RuleEngine。
- 工程计算工具：单位换算、表面速度、投影平均比压及后续经审核的工程公式。
- 求解器适配：未来连接 DLAP 或其他专业软件；本阶段只预留接口。
- 结果解析：把外部程序结果转换成有单位、有来源、有版本的结构化数据。

每项能力都应声明输入输出、版本、适用范围、确定性/副作用属性和来源要求。

### 2.5 领域状态与基础设施层

- DesignState + StateManager + SQLite：工程事实的唯一权威来源。
- StateEvent / CandidateDesign：记录参数、约束、候选版本、校核历史和变更。
- 用户消息仓库：保存不可变原始消息和证据定位。
- LangGraph Checkpoint：保存运行恢复所需的编排状态，不替代工程状态。
- 日志与审计：保存计划、Guard 结果、任务、Agent 结果、工具调用、用户决策和版本引用。

不要让每个 Agent 各自保存一份可修改的参数表或设计状态。也不要把 GraphState 当成第二个 DesignState。

---

## 3. 动态调度与扩展机制

### 3.1 运行时动作循环

每轮按以下逻辑运行，但具体业务动作不固定：

**观察状态 → 规划动作 → Guard 校验 → 执行 Agent/工具 → 校验结果 → 可信提交 → 重新观察状态**

可能的动作包括：

- 澄清轴承类型或应用场景；
- 询问缺少的轴径、载荷、转速、工况或边界；
- 解释某个参数或规则的含义；
- 进行工况预分析；
- 检索材料、润滑油或设计依据；
- 生成或补充候选方案；
- 运行规则预校核；
- 解释校核失败原因；
- 请求用户确认；
- 等待专业计算；
- 对允许修改的候选变量生成新版本；
- 输出阶段性摘要或报告。

Planner 可以提出动作，但动作是否存在、由谁执行、需要什么输入、是否允许写入、是否需要用户确认，均由受信目录和 Guard 决定。

### 3.2 Agent Registry / Action Catalog

现有 ActionSpec 和 CATALOG 是这一机制的初始版本，不需要推倒重写。

建议在后续框架整合 PR 中将其完善为一个受信 Agent/Action Registry。每个动作至少声明：

- action_id：稳定的动作标识；
- executor_id：受信执行者标识；
- input_schema_id / output_schema_id：输入输出协议；
- supported_scope：适用轴承范围；
- readiness_gate：前置条件；
- effect_class：只读、建议、领域写入、外部计算或人工决策；
- allowed_capabilities：执行者可用的工具范围；
- version：动作规格版本；
- idempotency / retry policy：副作用及重试约束。

模型不能自行创建 executor，也不能通过输出字段提高动作权限。

### 3.3 Tool Registry

工具注册机制应比 Agent Registry 更轻量。工具至少声明：

- tool_id 和版本；
- 输入输出 schema；
- 允许调用的 Agent；
- 是否确定性；
- 是否有外部副作用；
- 是否需要用户确认；
- 超时、错误分类和幂等要求。

工具默认由专业 Agent 调用。只有确有跨 Agent 复用或需要 Supervisor 直接编排的能力，才提升为独立调度动作。不要把每个小公式都暴露成 Supervisor 的动作。

### 3.4 Agent 统一执行契约

当前 Agent 基本通过 run(state, task) 接收完整状态和任务，AgentResult 返回结构化结果。后续应逐步形成稳定的 AgentRequest / AgentResult 边界：

- Request：design_id、task_id、action、目标、只读状态视图、输入引用、允许工具和版本信息。
- Result：任务状态、结构化输出、问题/诊断、证据引用、候选提案或受限 StatePatch、建议后续动作。

Agent 不得接收或构造 USER / SYSTEM WriteContext；不得直接操作 Repository；不得通过普通 AgentResult 直接写入工程事实。所有领域副作用必须经过可信应用服务和 StateManager。

不为此建立第二套业务状态模型。新协议只作为调用信封和结果契约。

### 3.5 扩展新能力的方式

**新增 Agent：**

1. 实现统一 Agent 执行接口。
2. 声明它负责的 action 和输入输出 schema。
3. 在受信 Registry 中注册 executor、范围、门槛和权限。
4. 为其能力增加专项测试和至少一个 Guard 正反例。
5. Supervisor 通用循环不需要增加专门节点或硬编码类型分支。

**新增 Tool：**

1. 实现带明确输入输出的工具适配器。
2. 声明确定性、版本、风险和调用权限。
3. 只授权给需要该工具的 Agent。
4. 记录输入版本、工具版本、结果引用和错误。

**新增轴承类型：**

为新类型增加领域 Profile，包含参数 schema、输入就绪规则、适用工况、知识/规则集合、专业 Agent 策略和计算适配器。公共 Supervisor、任务机制、审计和用户交互保持复用。

第一阶段只注册圆柱径向动压滑动轴承 Profile。滚动轴承仅预留扩展方式，不提前开发其专业参数与计算规则。

**动态扩展的边界：** 首版采用代码级受信注册和依赖注入，不做任意 Python 代码热加载、在线插件市场、远程 Agent 沙箱或微服务注册中心。

---

## 4. 四类 Agent 的职责和智能边界

### 4.1 RequirementsAgent

目标：帮助不熟悉设计流程的用户理解需要提供什么，而不是只把用户输入转换成参数表。

应逐步具备：

1. 识别设备用途、轴承类型、设计/改造任务和用户目标。
2. 把信息分成必须确认、可选输入、系统可推定/推荐三类。
3. 识别明确事实、估计值、假设、否定信息和冲突。
4. 根据当前工况和已有证据，动态决定下一项最有价值的问题。
5. 解释为什么需要这个条件，以及不提供会影响哪个分析或校核。
6. 用户不懂某个参数时，解释概念并给出可回答的替代问法。
7. 将提取结果作为提案提交；证据核验、单位检查、可信来源和 R2 就绪仍由确定性程序判断。

LLM 可以参与语义理解、问题组织和自然语言解释；不能因为模型认为信息“看起来合理”就把关键条件标为已确认。

### 4.2 DesignAgent

目标：像初步设计工程师一样分析和提出方案，而不是只运行几个固定公式。

应逐步具备：

1. 解读已核验工况并识别设计关注点。
2. 根据工况、知识和规则提出分析策略候选，并解释选择依据。
3. 识别需要哪些输入、规则、表格或计算工具。
4. 对宽度、间隙、材料、润滑油等设计变量提出有来源的候选。
5. 对多个候选进行可解释比较，区分硬约束和用户软偏好。
6. 资料不足时明确指出缺什么，不编造参数。
7. 将策略和候选作为提案交给 StateManager / ValidationAgent 的受控流程。

LLM 适合做策略推理、知识综合、方案解释和候选比较；数值计算和数值推荐必须来自确定性工具、审核规则/数表、经确认用户输入或有证据的计算结果。

### 4.3 ValidationAgent

目标：独立判断候选是否满足当前适用的要求，并帮助定位问题。

分为两层：

- **确定性校核层**：RuleEngine 对审核规则、用户硬约束、单位、适用范围和覆盖情况给出 PASS / FAIL / REVIEW_REQUIRED / INVALID 等明确结果。这一层是判定权威。
- **智能诊断层**：LLM 根据校核证据解释失败原因、指出缺失数据、列出允许调整的设计变量和建议检查方向。它不能改写规则、修改原始结果或伪造 PASS。

ValidationAgent 不负责代替 DLAP 计算膜厚或温度。真实性能结果由 CalculationAgent 及求解器提供，再交给规则层校核。

### 4.4 CalculationAgent

本阶段只定义职责和接口边界：

- 接收已确认的候选版本和计算配置；
- 检查求解器能力与输入 schema；
- 生成受控输入并调用求解器；
- 记录软件版本、配置、运行参数、日志和输出文件引用；
- 解析并校验结果的单位、字段和完整性；
- 区分 NOT_AVAILABLE、NOT_CONVERGED、EXECUTION_FAILED、SOLVED 和工程校核状态。

本阶段不实现 DLAP 进程调用，不生成虚拟膜厚/温度结果，不把“求解成功”等同于“工程合格”。

---

## 5. 状态、上下文、记忆和证据

### 5.1 唯一工程事实来源

- DesignState 保存当前工程事实。
- StateManager 是受信工程状态写入入口。
- SQLite Repository 负责持久化和 CAS。
- CandidateDesign 保存候选版本，不覆盖历史候选。
- StateEvent 保存受信变更记录。
- LangGraph GraphState 只保存运行引用、动作、预算、短 trace、等待状态等编排信息。

### 5.2 对话上下文不等于工程状态

原始用户消息应保存为可核验的证据。Planner 和 Agent 每次只接收完成任务所需的摘要、参数视图、相关历史和证据引用，不应把无限增长的聊天全文塞进每次提示词。

优先复用 LangGraph checkpoint、现有 SQLite 消息记录和成熟模型库的上下文管理能力。当前阶段不自研通用长期记忆系统，不引入第二个可写参数缓存。

### 5.3 结果可追溯

每个关键决策和结果应尽可能记录：

- design_id、state_version、task_id、operation_id；
- action、executor、Agent 版本；
- 模型提供方、模型 ID、Prompt 版本/哈希、结构化输出 schema 版本；
- Guard 决策和原因码；
- 实际消费的参数、约束、工况和候选版本；
- 知识条目、规则集、数表和来源版本；
- 工具/求解器版本、输入摘要、输出引用和错误；
- 用户确认/拒绝的目标版本及依赖摘要。

精确 consumed_input_refs 目前尚未实现，按既有 V3.4 规划在后续动态重规划工作中完成。在精确依赖尚未建立前，允许保守 STALE，不允许旧结果被错误地当作新输入下的有效结果。

### 5.4 可复现性边界

确定性公式、单位转换、RuleEngine、输入快照和候选版本在相同版本输入下应可复现。LLM 规划和自然语言输出不承诺逐字一致；需要记录模型配置、Prompt、目录版本、原始结构化提案和 Guard 结果，以便审计与对照实验。

---

## 6. 当前 GitHub 代码的实际状态（以 main 提交 d78507f 为准）

| 模块 | 已实现 | 仍缺少 | 当前判断 |
|---|---|---|---|
| PR-01 领域底座 | DesignState、参数/约束/工况、StateManager、SQLite、CAS、写入保护、Readiness | 更丰富的领域 Profile | 基础已完成 |
| PR-02 LangGraph Runtime | Observer/Planner/Guard/Prepare/Execute/Wait、checkpoint、任务状态、恢复与预算 | 通用扩展注册和完整真实 Agent 组合 | 执行骨架已完成 |
| PR-02B LLMPlanner | 可选真实模型；只提出 action/rationale；输出经结构化解析并由 Guard 检查 | 动作目录仍小且静态；默认 Runtime 仍使用 FakePlanner | 真实规划接口已完成，未成为默认运行方式 |
| PR-03 Requirements | 多轮消息保存、参数提案、证据核验、纠错/确认/约束审批；可选 LLMExtractor | Questions 仍由确定性模板生成；RequirementsAgent 只是构建 view 并返回问题；CLI 与 Runtime 未形成统一端到端交互 | 可信需求采集已完成，智能引导未完成 |
| PR-04 Knowledge / Rules | 来源目录、规则/表格仓库、规则生命周期、确定性 RuleEngine、词法检索 | 没有经专家批准的完整工程数值规则/表；当前检索不是向量 RAG | 软件基础完成，领域审核待办 |
| PR-05 DesignAgent | 表面速度、已知宽度时的投影平均比压、知识检索、策略摘要、ACTIVE 表格候选提案 | 没有 LLM 工况推理、动态策略选择和多方案比较；默认资料不能提供正式数值推荐 | 确定性初版完成，专业智能能力未完成 |
| PR-06 ValidationAgent | 独立确定性预校核、规则覆盖、用户硬约束、候选版本和可信结果写入 | 没有 LLM 诊断解释；默认规则覆盖不足时正确返回 REVIEW_REQUIRED | 软件预校核完成，领域校核待审核规则和性能结果 |
| CalculationAgent | 尚未实现；动作目录明确把 run_simulation 标为 unsupported | 求解器接口、输入输出 schema、结果解析 | 仅预留方向 |
| PR-07 动态反馈 | 现有 Runtime 有有限状态循环、预算和重试 | 精确输入依赖、校核反馈、受限修订、新候选比较和局部重规划 | 完整闭环未完成 |
| API / UI / 报告 | 当前以 CLI 和示例脚本为主 | 面向初学者的正式交互界面、报告 | 未完成 |
| 科研评价 | 已有 Planner 小样本真实 API 实验脚本 | 完整系统对照实验、留出集和统计分析 | 未完成 |

### 6.1 当前代码中的关键事实

1. Runtime 的 CATALOG 是固定的小型动作字典；ActionSpec 可通过构造参数注入，但还没有独立、完整的 Agent/Tool Registry。
2. Runtime 默认使用 FakePlanner，并为只读动作建立 FakeAgent；真实实现需要调用方显式注入。
3. Runtime 已使用通用的 observe/plan/guard/prepare/execute/wait_user 循环，但执行器分派仍依赖 executor 字典，候选提交路径还存在对 DesignAgent 类型的特殊判断。
4. LLMPlanner 只从受信动作目录中提出下一步 action 和 rationale；它不是可任意创建 Agent 或直接调用任意 Python 工具的自治系统。
5. PR-03 的 LLMExtractor 只负责从一条用户消息提取不可信结构化提案。问题文本和问题排序仍主要由 requirements/questions.py 中的确定性逻辑决定。
6. PR-03 CLI 通过 InteractionService 工作；它没有自动把真实 LLMPlanner、RequirementsAgent、DesignAgent 和 ValidationAgent 串成一个完整交互 Runtime。
7. DesignAgent 当前不调用 LLM；ValidationAgent 当前不调用 LLM，且这是可以保留的确定性校核设计。
8. 当前默认知识库没有可用于完整工程推荐的 ACTIVE 数值表和完整专家审核规则；默认预校核返回 REVIEW_REQUIRED 是诚实行为，不是系统故障。
9. CalculationAgent 和 DLAP 尚未接入。

### 6.2 当前 CI 说明

main 的最新 Tests 工作流在 Ubuntu Python 3.11 和 Windows Python 3.14 均通过 pytest、Ruff、pip check 和 git diff 检查。该结果证明当前软件回归通过，不证明真实 API 的系统级联调、规则专业有效性或 DLAP 性能正确性。

---

## 7. 后续开发路线建议：框架先行，再深化 Agent

V3.4 原计划把动态反馈闭环集中在 PR-07，并把 UI/实验安排为 PR-08/09。本提案建议先把“完整框架整合”单独放在最前面，再做 Agent 智能能力和反馈闭环。**以下是待确认的新顺序，不自动修改 V3.4 已有 PR 规格。**

| 建议顺序 | PR / 工作包 | 核心目标 | 主要交付 | 明确不做 |
|---|---|---|---|---|
| 0 | 本架构对齐 | 明确分层、边界、扩展方式和实际缺口 | 本文档、差异清单、下一 PR 验收边界 | 不改业务代码 |
| 1 | PR-07 框架整合与扩展机制 | 让已有模块通过统一 Runtime 和受信注册机制运行 | Agent/Action Registry、最小 Tool Registry、Runtime composition root、统一交互入口、通用执行契约 | 不实现复杂 Agent 推理，不接 DLAP，不做 UI |
| 2 | PR-08 RequirementsAgent 深化 | 从参数收集升级为真正的需求引导 | 场景理解、必须/可选/可建议分类、动态问题建议、解释原因、冲突与不确定性处理 | 不允许 LLM 确认工程事实 |
| 3 | PR-09 DesignAgent 深化 | 从固定公式/查表升级为专业策略辅助 | LLM 工况解释、风险与模型策略候选、知识/工具选择、候选比较和来源说明 | 不允许 LLM 编造数值或绕过规则 |
| 4 | PR-10 ValidationAgent 诊断深化 | 保留确定性判定，增加专业解释 | 失败原因解释、证据关联、允许修改变量和修订建议 | LLM 不得改判 PASS/FAIL |
| 5 | PR-11 动态反馈与局部重规划 | 形成有限、可追溯的设计迭代闭环 | consumed_input_refs、局部失效、修订状态机、候选版本比较、无进展停止、用户确认 | 不做无边界自治和多目标性能优化 |
| 6 | PR-12 CalculationAgent 接口骨架 | 统一外部求解器调用契约 | Solver Adapter 协议、输入/输出 schema、NOT_AVAILABLE/执行失败状态 | 不接真实 DLAP、不伪造计算结果 |
| 7 | PR-13 API、UI 与初步报告 | 让初学者可以使用完整的软件闭环 | 对话、参数、计划轨迹、候选校核、报告 | 不做复杂 CAD 和企业级 IAM |
| 8 | PR-14 系统评价 | 验证多 Agent 框架的实际价值 | 多轮案例集、固定流程/单 Agent/动态 Supervisor 对照、准确性和成本统计 | 不把合成案例说成真实企业验证 |
| 后续 V2 | DLAP 接入与专业性能验证 | 真实求解和性能校核 | DLAP Adapter、标准算例复核、结果映射、膜厚/温度等规则评价 | 未完成授权和算例核验前不启动 |

### 7.1 PR-07 的准入与验收重点

PR-07 是下一项唯一编码任务，先把框架真正连起来。

必须证明：

- 同一 Runtime 能注入 FakePlanner / LLMPlanner，以及 RequirementsAgent、DesignAgent、ValidationAgent 的当前实现。
- 用户消息处理、需求提取、需求追问和 Supervisor 任务调度有统一应用入口；不再要求使用者手动调用多个互不关联的 demo。
- 新增一个测试 Agent，只通过注册 ActionSpec/执行器就能被 Supervisor 调用，不需要修改 workflow 主循环。
- 新增一个测试 Tool，只授权给指定 Agent；未授权 Agent 无法调用。
- Agent 不能直接写 Repository，不能构造 USER/SYSTEM WriteContext。
- 候选写入不再依赖对某个具体 Agent Python 类型的特殊判断，而由受信 action/effect contract 和专用提交服务控制。
- Planner 只能选择已注册动作；伪造 action、executor、schema 或权限均被 Guard 拒绝。
- 离线 Fake 测试完整保留；真实 LLMPlanner 可选启用，API 失败不能静默回退并冒充真实模型成功。
- 当前单一圆柱径向动压领域 Profile 可运行；测试 Profile 可以证明新增领域配置不需要修改 Supervisor 核心。
- 任务、输入、结果、工具版本、Guard 和重规划原因可追踪；恢复不重复产生领域副作用。

PR-07 不要求 RequirementsAgent 已经很聪明，也不要求 DesignAgent 已经能给出正式工程方案。它要证明的是：框架已经为这些能力准备好了稳定的运行和扩展位置。

### 7.2 PR-08～PR-10 的共同原则

每个专业 Agent 分开增强，避免一次性重写整个 Runtime：

- 先定义可测的输入输出和能力边界；
- LLM 输出始终是非受信提案；
- 确定性校验、专业规则和 StateManager 保留权威；
- 用固定案例、反例和真实 API 实验分别验证模型接口与专业行为；
- 未经专家审核的知识不能变成 ACTIVE 规则；
- 无依据的数值只能输出缺失依据或 REVIEW_REQUIRED，不能为了演示而编造。

### 7.3 PR-11 动态闭环的核心原则

- Supervisor 根据最新状态重新规划，不强制从头执行。
- 只自动修改用户允许范围内、尚未确认的 DESIGN_VARIABLE。
- 固定输入、用户硬约束、已确认参数和审核规则阈值不能被自动修改。
- 每次修改生成新候选版本，不覆盖历史版本。
- 对新旧候选使用相同且有效的规则覆盖集合进行比较。
- 没有客观可比较的证据，不得声称“方案优化了”。
- 自动修订有次数、总步数和无进展预算；到限后询问用户或停止。
- 输入依赖尚不明确时保守失效，不能继续使用过期预校核结果。

---

## 8. 明确不做的过度设计

为保持框架简洁，本阶段不引入：

1. 微服务拆分、分布式消息队列和多机 Agent 集群。
2. 任意 Python 动态插件热加载、在线插件市场和远程代码执行。
3. 自研通用长期记忆系统或第二套对话数据库。
4. Agent 之间无限制自由聊天或互相写共享状态。
5. 每个公式、参数或知识条目都拆成一个 Agent。
6. 为了“动态”而每次运行都重新生成 LangGraph 图结构。
7. 复杂多目标优化、并行候选搜索和长期后台自治。
8. 在没有领域授权和复核算例时提前接入并宣称 DLAP 结果有效。

首版采用一个 Supervisor、少量专业 Agent、一个受信动作注册表、轻量工具注册机制、统一状态和明确权限边界即可。

---

## 9. 架构验收清单

### 框架能力

- [ ] Supervisor 只依赖受信动作/Agent 注册接口，不硬编码具体专业 Agent 类型。
- [ ] 同一通用执行循环可调度不同 Agent。
- [ ] 动作注册包含 schema、适用范围、前置条件、effect class 和版本。
- [ ] 工具注册可限定允许调用的 Agent，并能记录工具版本和结果。
- [ ] 新增测试 Agent 不需要修改 Supervisor 主循环。
- [ ] 新增测试轴承 Profile 不需要修改 Supervisor 主循环。

### 动态能力

- [ ] 相同用户目标在不同 DesignState 下能选择不同动作。
- [ ] 用户只查询一个设计问题时，不强制跑完整流程。
- [ ] 缺少必要条件时追问；条件齐全时不重复询问。
- [ ] Agent/工具结果变化后，Supervisor 重新观察并规划。
- [ ] Guard 能拒绝未注册动作、越权动作、过期输入和不支持范围。
- [ ] 有明确预算、无进展检测、暂停和恢复机制。

### 可信与可追溯

- [ ] LLM/Agent 不能伪造 USER、SYSTEM、CONFIRMED 或 ACTIVE。
- [ ] Agent 不直接写数据库。
- [ ] 每个结果能追溯输入版本、Agent/模型版本、工具/规则版本和证据。
- [ ] 候选和校核历史不被覆盖。
- [ ] 重试和恢复不会重复产生工程副作用。
- [ ] 软件验收与专业领域验收分开记录。

### 可运行性

- [ ] 有一个统一离线端到端 CLI / harness。
- [ ] 有一个真实 LLMPlanner 可选运行的端到端路径。
- [ ] RequirementsAgent、DesignAgent、ValidationAgent 能在同一 Runtime 中被调用。
- [ ] 真实模型不可用时明确报错或按显式策略降级，不冒充真实调用成功。
- [ ] 所有新增接口有单测、集成测试和失败场景。

---

## 10. 需要继续遵守的既有工程约束

本文不修改以下既有决定：

- StateManager 是唯一受信工程状态写入入口。
- Agent/LLM/检索内容均为非受信输入。
- 用户确认必须绑定目标版本和依赖摘要。
- R2 输入就绪不等于设计方案就绪或工程校核通过。
- 未审核的标准草案不能激活为工程规则。
- 确定性校核缺少规则覆盖时不得 PASS。
- 软件任务成功不等于工程性能合格。
- 没有真实求解器结果时，SimulationStatus 必须明确为 NOT_AVAILABLE / NOT_EVALUATED。
- 所有开发按独立 PR 进行，一次只实现一个明确 PR；CI 通过不替代专业审核。
- PR 不自动合并；完成后停在审阅点。

---

## 11. 相关仓库资料与代码入口

### 已有架构与规划文件

- `10.13郑老师讨论总结_滑动轴承智能设计系统框架.md`
- `docs/planning/滑动轴承多Agent系统_正式架构与实施方案_V3.3.md`
- `docs/planning/滑动轴承多Agent系统_全阶段PR实施总计划_V3.4.md`
- `docs/architecture_decisions.md`
- `docs/protocols/orchestration_contract_v1.md`

### 当前关键实现

- 领域状态与可信写入：`src/bearing_agents/domain/state.py`、`src/bearing_agents/core/state_manager.py`
- Supervisor / LangGraph Runtime：`src/bearing_agents/orchestration/contracts.py`、`src/bearing_agents/orchestration/workflow.py`
- 真实 LLMPlanner：`src/bearing_agents/orchestration/llm_planner.py`
- 需求引导与交互：`src/bearing_agents/requirements/agent.py`、`interaction.py`、`extraction.py`、`questions.py`
- 知识与规则：`src/bearing_agents/knowledge/`、`src/bearing_agents/rules/engine.py`
- 初步设计：`src/bearing_agents/design/agent.py`
- 确定性预校核：`src/bearing_agents/validation/agent.py`、`service.py`
- 工程计算工具：`src/bearing_agents/tools/engineering_calculator.py`

---

## 12. 本文档的生效方式

本文是对总体运行架构和开发顺序的对齐提案，不是自动生效的代码重构授权。

审阅确认后：

1. 将本文作为后续 PR 的总体架构基线。
2. 再根据本文与 V3.4 的差异，更新 PR 顺序和验收矩阵；保留原有安全契约和领域审核要求。
3. 启动 PR-07 框架整合与扩展机制开发。
4. PR-07 通过审查后，再分别深化 RequirementsAgent、DesignAgent、ValidationAgent 和动态反馈闭环。

在本文审阅确认前，不修改 PR-01～PR-06 既有实现，不启动 PR-07 代码开发，也不将本提案描述为已经合并生效的正式架构。
