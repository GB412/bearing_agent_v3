# 轴承智能设计系统：多 Agent 职责与自主决策设计

## 1. 设计目标

系统既不能退化为固定表单流程，也不能让多个大模型自由讨论后直接决定工程结果。建议采用：

```text
约束状态机 + 总控 Agent 动态规划 + 专业 Agent 提案 + 确定性服务执行
```

其中：

- **约束状态机**规定当前允许的动作、前置条件和禁止事项；
- **总控 Agent**在允许范围内自主选择下一步、调整任务顺序和决定是否重新规划；
- **专业 Agent**只对自己负责的结构化对象提出提案；
- **确定性服务**负责验证提案、执行计算、比较规则、管理版本和保存证据。

总控 Agent 的自主性体现在任务策略和路径选择中，不体现在修改事实、改变规则或直接宣布工程合格。

## 2. 推荐的总体分层

```text
用户交互层
    ↓
总控决策 Agent
    ↓ 选择下一步动作、调用专业 Agent、决定是否重规划
专业 Agent 层
    ├─ 需求与工况 Agent
    ├─ 轴承方案 Agent
    ├─ 分析策略 Agent
    └─ 结果评审与修订 Agent
    ↓ 提交结构化提案
确定性控制层
    ├─ 工作流与状态服务
    ├─ 提案校验与权限服务
    ├─ 参数、单位与 Schema 服务
    ├─ 规则引擎
    ├─ 知识检索与证据服务
    ├─ 计算编排与求解器适配器
    └─ 版本、依赖与审计服务
    ↓
轴承领域能力插件
    ├─ 滑动轴承能力包
    └─ 后续滚动轴承能力包
```

“滑动轴承能力包”不是一个自由决策的 Agent，而是提供字段、公式、适用性条件、分析能力、规则和求解器适配器。将来增加滚动轴承时，公共 Agent 和工作流可以复用，替换或增加领域能力包即可。

## 3. Agent 之间的核心边界

划分依据不是“谁知道哪些知识”，而是“谁对哪一种结构化结果负责”。每种核心对象只有一个生产者，其他 Agent 只能读取或提出意见，不能直接覆盖。

| Agent | 负责的核心问题 | 唯一主要输出 | 可以做的决策 | 明确不能做的事 |
|---|---|---|---|---|
| 总控决策 Agent | 当前任务下一步应该怎么推进 | `ActionPlan` | 选择路径、排序任务、决定追问/计算/重规划/升级 | 修改事实、改变规则、直接判定合格、绕过确认门 |
| 需求与工况 Agent | 用户到底要设计什么，工况和目标是什么 | `RequirementSpec` | 识别需求、分类工况、发现缺失和矛盾 | 选最终几何、选最终材料、决定求解器开关 |
| 轴承方案 Agent | 形成什么轴承应用方案 | `DesignProposal` | 选择候选轴承路线、几何、材料、润滑和设计变量 | 直接运行计算、声称结果合格、伪造物性参数 |
| 分析策略 Agent | 为判断方案是否合理需要算什么 | `AnalysisPlan` | 选择分析任务、顺序、模型设置和分析深度 | 修改设计参数、改变规则阈值、直接调用求解器 |
| 结果评审与修订 Agent | 结果说明什么，下一轮如何改 | `ReviewResult`、`RevisionProposal` | 解释失败、比较修改方向、提出新方案 | 自行生成阈值、直接改状态、无限重算 |

计算、规则、检索、版本和状态管理不作为自由发挥的 Agent。它们是确定性服务；如果以后需要用模型处理工具故障，可以增加受限的“计算运行监督 Agent”，但它只能选择重试、诊断或请求人工处理，不能擅自改工程参数。

## 4. 总控决策 Agent：自主性如何体现

总控 Agent 不是固定流程的路由器，而是一个受约束的任务规划器。每次运行都执行以下循环：

```text
读取当前状态和证据
    ↓
获得当前允许动作集合
    ↓
评估各动作对目标、风险、成本和信息增益的影响
    ↓
生成并排序 ActionPlan
    ↓
由策略校验器检查合法性
    ↓
执行动作或请求用户确认
    ↓
写入事件和新版本
    ↓
根据新证据重新规划
```

### 4.1 总控 Agent 可以自主决定的内容

1. **信息获取策略**：多个信息缺失时，先问哪一个问题；一次问一个还是组合问几个。
2. **任务顺序**：先做快速适用性检查、方案比较，还是直接进入基础分析。
3. **分析深度**：简单工况采用基础稳态分析，发现热风险后追加热平衡或温度分析。
4. **失败分流**：输入矛盾回需求 Agent，模型不适用回分析策略 Agent，指标失败回方案 Agent，工具失败回计算服务。
5. **方案数量**：生成单方案、两个候选方案，还是先停止扩展方案以控制计算量。
6. **是否请求确认**：低风险默认建议，高风险模型、企业规则冲突和关键参数修改必须确认。
7. **停止或升级**：目标满足、连续迭代无改善、证据不足、超出能力范围时停止自动推进或请求专家介入。

### 4.2 总控 Agent 不可以自主决定的内容

- 把未知参数写成事实；
- 修改用户已经确认的设计参数；
- 修改规则阈值、单位或来源；
- 把 `unknown` 改成 `passed`；
- 绕过用户确认执行高风险计算；
- 把求解器失败包装成设计成功；
- 直接写入 `DesignState`。

### 4.3 总控 Agent 的输入和输出

输入：

```text
DesignState
当前阶段允许动作
RequirementSpec / DesignProposal / AnalysisPlan / CalculationResult / RuleEvaluation
用户目标和偏好
历史版本和失败记录
工具能力、规则和证据状态
```

输出必须是结构化 `ActionPlan`，例如：

```json
{
  "plan_id": "AP-0007",
  "goal": "获得可计算且优先控制温升的滑动轴承方案",
  "selected_actions": [
    {
      "type": "ask_user",
      "target": "supply_temperature",
      "reason": "当前温度缺失，无法可靠估算黏度和热平衡"
    }
  ],
  "alternative_actions": [
    {
      "type": "run_precheck",
      "condition": "用户暂时无法提供供油温度",
      "risk": "只能得到低证据等级的初步结果"
    }
  ],
  "expected_information_gain": "high",
  "estimated_cost": "low",
  "requires_user_confirmation": false,
  "stop_condition": null,
  "escalation_condition": "连续两次无法获得供油温度且热模型不可用"
}
```

这里的 `ActionPlan` 是提案，不是状态修改命令。工作流服务和策略校验器通过后，才能执行。

## 5. 各专业 Agent 的详细职责

### 5.1 需求与工况 Agent

#### 负责

- 从自然语言提取用户事实；
- 识别设备、轴段、轴承用途和任务类型；
- 建立载荷、转速、温度、润滑和环境工况；
- 区分事实、假设、派生值、建议、未知和矛盾；
- 识别低速/高速、轻载/重载、稳态/变化工况等类别；
- 提出当前最有价值的补充问题。

#### 输出

```text
RequirementSpec
    ├─ task_context
    ├─ operating_conditions
    ├─ user_constraints
    ├─ objectives_and_priorities
    ├─ known_facts
    ├─ assumptions
    ├─ unknowns
    ├─ contradictions
    └─ candidate_questions
```

#### 边界

它可以说“当前工况可能属于高速连续运行”，但不能据此直接选择某一材料、间隙或热模型。它提供工况标签和风险线索，最终方案由轴承方案 Agent 提出，分析设置由分析策略 Agent 提出。

### 5.2 轴承方案 Agent

#### 负责

- 根据需求和领域能力包选择轴承路线候选；
- 组织几何、材料、润滑和供油方案；
- 提出设计变量、上下界和候选初值；
- 读取企业约束、材料库和润滑剂库；
- 明确每个参数的来源和假设；
- 根据评审结果提出修改方案。

#### 输出

```text
DesignProposal
    ├─ bearing_type
    ├─ geometry
    ├─ material_and_surface
    ├─ lubrication_and_supply
    ├─ design_variables
    ├─ hard_constraints
    ├─ soft_objectives
    ├─ assumptions
    ├─ evidence_refs
    └─ unresolved_items
```

#### 边界

它可以提出“提高黏度可能有利于增大油膜”，但不能声称已经满足油膜规则。所有候选参数必须有来源、范围或明确标记为假设，不能凭空生成材料或润滑油物性。

### 5.3 分析策略 Agent

#### 负责

- 将设计目标转换为分析任务；
- 根据工况、设计方案和能力矩阵选择分析深度；
- 设置分析顺序、依赖和模型开关；
- 指定输入字段、前置条件、收敛标准和结果质量等级；
- 说明每个设置的依据和是否需要用户确认；
- 发现分析任务超出工具能力时阻止执行并报告原因。

#### 输出

```text
AnalysisPlan
    ├─ tasks
    ├─ execution_order
    ├─ dependencies
    ├─ required_inputs
    ├─ applicability_conditions
    ├─ model_settings
    ├─ convergence_requirements
    ├─ expected_outputs
    ├─ quality_level
    └─ confirmation_items
```

#### 边界

它可以决定需要热平衡分析，但不能把供油温度改成 40℃；可以提出调整分析设置，但不能改变用户已经确认的方案参数。

### 5.4 结果评审与修订 Agent

#### 负责

- 读取计算结果和规则引擎结果；
- 区分设计指标失败、模型不适用、工具失败和证据不足；
- 用工程语言解释结果和风险；
- 根据目标优先级提出一到三个修改方向；
- 评估每种修改可能改善什么、恶化什么；
- 生成新的 `RevisionProposal`，供用户选择或总控 Agent 继续规划。

#### 输出

```text
ReviewResult
RevisionProposal
    ├─ changed_variables
    ├─ old_values
    ├─ proposed_values_or_ranges
    ├─ expected_improvements
    ├─ possible_side_effects
    ├─ affected_analysis_tasks
    ├─ evidence_refs
    ├─ confirmation_required
    └─ iteration_budget
```

#### 边界

规则引擎决定 `passed / failed / unknown`，评审 Agent 只能解释和提出修改。它不能自行生成阈值，也不能直接把修改写入当前版本。

## 6. 确定性服务的职责

### 6.1 工作流与状态服务

- 保存当前状态和允许动作；
- 检查确认门和前置条件；
- 执行 ActionPlan；
- 控制重试、超时、取消和人工接管；
- 防止 Agent 越权和循环调用。

### 6.2 提案校验服务

对所有 Agent 输出执行：

- Schema 校验；
- 参数和单位校验；
- 权限校验；
- 引用和证据校验；
- 领域能力范围校验；
- 与当前版本的一致性校验。

### 6.3 规则引擎

只执行已发布的结构化规则，输出：

```text
RuleEvaluation
    ├─ rule_id
    ├─ actual_value
    ├─ expected_value
    ├─ status: passed / failed / unknown
    ├─ applicability
    ├─ evidence_refs
    └─ explanation_data
```

### 6.4 计算服务

- 将统一输入转换成求解器输入；
- 执行求解器；
- 保存输入、日志和原始输出；
- 检查退出状态、收敛和结果完整性；
- 解析成统一的 `CalculationResult`；
- 不解释工程是否合格。

### 6.5 版本和依赖服务

- 每次用户确认或参数修改创建新版本；
- 记录修改原因和来源；
- 根据依赖图标记受影响结果失效；
- 支持方案比较和结果复现；
- 保存模型、规则、知识库和求解器版本。

## 7. Agent 之间的交接协议

推荐固定为：

```text
RequirementSpec
    ↓
DesignProposal
    ↓
AnalysisPlan
    ↓
CalculationRequest
    ↓
CalculationResult
    ↓
RuleEvaluation
    ↓
ReviewResult
    ↓
RevisionProposal
    ↓
ActionPlan
```

每个对象必须带有：

- `schema_version`；
- `task_id` 和 `design_version`；
- `producer`；
- `created_at`；
- `status`；
- `evidence_refs`；
- `assumptions`；
- `unresolved_items`。

Agent 之间不能把长篇自然语言当作工程事实传递。自然语言只用于解释，事实必须在结构化对象中保存。

## 8. 自主决策的约束机制

总控 Agent 的行动应经过三道门：

```text
总控 Agent 提出 ActionPlan
        ↓
策略校验器：当前阶段是否允许？
        ↓
领域校验器：参数、规则和能力是否满足？
        ↓
确认门：是否需要用户确认？
        ↓
执行并记录
```

策略校验器不评价 Agent 的语言是否漂亮，只检查：

- 是否满足前置条件；
- 是否超出权限；
- 是否需要确认；
- 是否会造成循环；
- 是否超过计算预算或迭代预算；
- 是否使用了过期结果。

## 9. 一个具体的自主规划例子

用户说：“设计一个压缩机用的低速重载滑动轴承。”

系统可能动态形成如下路径：

```text
需求 Agent：识别压缩机、低速重载、滑动轴承；缺少载荷方向、转速、轴径和供油方式
        ↓
总控 Agent：优先询问载荷和转速，因为它们决定工况等级和后续分析路径
        ↓
需求 Agent：得到载荷、转速和轴径；供油温度未知
        ↓
总控 Agent：先让方案 Agent 生成候选，同时让知识服务查询可用润滑油
        ↓
方案 Agent：提出两个候选方案，并标出温度和流量差异
        ↓
总控 Agent：发现用户优先控制温度，选择高温裕度方案进入分析规划
        ↓
分析策略 Agent：安排油膜、压力、温度和流量分析；指出供油温度仍是热分析阻断项
        ↓
总控 Agent：向用户解释影响，并请求供油温度；用户允许采用范围假设
        ↓
计算服务：执行基础分析
        ↓
规则引擎：油膜通过，温度超限，结果有效
        ↓
评审 Agent：提出降低供油温度假设、调整流量和改变间隙三个方案
        ↓
总控 Agent：根据用户的温度优先级和约束，选择先调整流量，再重算
        ↓
版本服务：创建 V2，旧结果标记为受影响；重新规划和计算
```

这里的路径不是预先写死的，但每一步都受到状态、能力、规则、确认和版本约束。

## 10. 首版建议

首版不建议实现大量互相对话的独立 Agent。建议实现：

```text
4 个专业 Agent + 1 个总控 Agent

1. 总控决策 Agent
2. 需求与工况 Agent
3. 轴承方案 Agent
4. 分析策略 Agent
5. 结果评审与修订 Agent

配套确定性服务：

1. 工作流与状态
2. 提案校验
3. 单位和参数
4. 知识与证据
5. 规则引擎
6. 计算适配
7. 版本与审计
```

这五个 Agent 已足以体现自主规划。后续只有在确实需要时再增加：

- 多方案优化 Agent；
- 多工况任务分解 Agent；
- 失效诊断 Agent；
- 滑动轴承或滚动轴承领域专家 Agent。

领域专家优先作为能力包和工具服务提供，而不是一开始就增加一个可以自由决策的 Agent。

## 11. 设计判断

最终的职责关系可以概括为：

```text
总控 Agent：决定“下一步做什么”
需求 Agent：说明“用户要什么”
方案 Agent：提出“设计成什么样”
分析 Agent：说明“需要算什么”
计算服务：执行“怎么算”
规则引擎：判断“是否满足规则”
评审 Agent：解释“为什么，以及下一步怎么改”
工作流服务：保证“所有动作合法、可追溯、可复现”
```

这样既保留总控 Agent 的自主决策，也避免让它成为一个可以随意修改工程事实和规则的“超级 Agent”。
