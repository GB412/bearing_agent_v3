# PR-03 需求引导 Agent：实现与验收记录

## 范围与工程边界

本 PR 建立 **可信本地交互 → 结构化抽取 → 来源证据核验 → StateManager
状态提交 → R2 驱动追问** 的多轮基础功能。已有 LangGraph Runtime
仍是唯一总控；现有 `clarify_requirement` / `requirements_fake` 动作通过
可注入 `RequirementsAgent` 输出 `questions`。不生成任何正式方案、工程校核或 DLAP 结果。

当前 V1 只针对油润滑、圆柱径向动压、单一稳态滑动轴承。
PR-03 新建语言会话以 `target_scope="unknown"` 开始；
旧 `StateManager.create_design()` 默认值不变（PR-01/02 向后兼容）。
范围不明确、滚动/静压/可倾瓦或多工况都不能因为默认字段而进入正式 R2。

## 文件与最小模块

- `requirements/contracts.py`：`UserTurn`、`RequirementProposal`、
  `VerifiedRequirement`、`RequirementSpecView`、`InteractionReceipt`。
- `requirements/extraction.py`：确定性离线抽取与显式 opt-in 的
  `LLMExtractor`。仅产出提案，无任何确认和写入权限。
- `requirements/evidence.py`：根据原文字符范围、quote、数值、
  量纲及基本语义进行确定性核验，无法确定时返回 CLARIFY。
- `requirements/questions.py`：使用 StateManager 的既有 R2 检查，
  每轮不超过三个问题。
- `requirements/interaction.py`：受信离线用户入口，提交消息/纠错、
  按 revision 确认、批准或拒绝待审批约束、拒绝参数变更提议。
- `requirements/agent.py`：只读 LangGraph RequirementsAgent。
- `infra/state_repository.py`：原业务 SQLite 增量添加 `user_messages`
  与 `interaction_operations`，不创建第二套数据库。
- `core/state_manager.py`：保持原 `apply_patch` 校验，
  添加受信 scope 变更及原子交互收据、待审批约束拒绝入口。

## 崩溃一致性与幂等

1. 用户原文首先以 `operation_id` 持久化在 `user_messages`。
   同 operation ID、design、actor、正文重放复用原消息；不同内容拒绝。
2. 抽取和证据核验在事务外完成；字段级核验不通过则不会变成
   `PROVIDED`。消息存储本身不意味着工程状态已获批准。
3. `StateManager.apply_patch(..., interaction=...)` 复用原有参数、
   来源/角色/约束、CAS、依赖失效、审计校验。
4. `commit_interaction` 在**一个 SQLite 事务**中持久化工程 JSON
   （含其 StateEvent）及 `interaction_operations` receipt。
   先提交后响应丢失，原 operation 重试从收据恢复；未提交时可用
   相同消息重试。不同意图复用 operation ID 被拒绝。
5. 普通自然语言回复不使用 `Runtime.resume(accepted=True)`。
   完整用户消息不写入 GraphState；只读、受限长度的追问可以展示。

**真实安全边界**：本地 CLI actor 是调用者配置的**受信本地身份**，
不构成 Web 登录认证；模型绝不能提供 actor/USER context、
`verified_source_ref`、`approved`、`CONFIRMED` 的权威值。

## R01–R20 固定场景

| 场景 | 预期 | 测试位置 |
|---|---|---|
| R01 模糊需求 | 范围未判定，不编造数值 | test_acceptance |
| R02 D/n 缺 F | 准确追问 load | test_acceptance / test_flow |
| R03 D/F/n + 单稳态 + 范围 | 可信 PROVIDED、R2 就绪 | test_acceptance / test_flow |
| R04 m/kN/r/min | 确定性归一化 | test_acceptance |
| R05 转速缺单位 | 不接受且仍缺转速 | test_acceptance |
| R06 Nm 扭矩冒充载荷 | 不接受 | test_acceptance |
| R07 用户纠错 | revision、来源与审计更新 | test_acceptance / test_flow |
| R08 Agent 改确认值 | 权限阻断 | test_acceptance |
| R09 禁用材料 | pending HARD/NOT_IN | test_acceptance |
| R10 安装宽度上限 | pending HARD/LE | test_acceptance / test_flow |
| R11 B/间隙由系统设计 | 不无限追问 B | test_acceptance |
| R12 估算载荷 | 仍需核实 | test_acceptance |
| R13 无对象的“我确认” | 不触发 CONFIRMED | test_acceptance / test_flow |
| R14 拒绝参数变更提议 | 参数保持不变、提议 REJECTED | test_acceptance |
| R15 操作重放 | 不增加领域版本 | test_acceptance / test_flow |
| R16 同 ID 不同正文 | StateConflictError | test_acceptance / test_flow |
| R17 模型伪造字段/span | 不进入 PROVIDED | test_acceptance / test_flow |
| R18 动态/多工况 | 范围 unsupported，不能 R2 | test_acceptance |
| R19 进程重启续答 | 真实另一个 Python 进程恢复 | test_acceptance |
| R20 提示注入要求确认 | 不允许越权 | test_acceptance |

额外覆盖：启动后仍可查看当前状态、待审批约束批准/拒绝、
运行时直接返回可见问题、注册状态版本与 SQLite 收据事务失败、
持久化成功但客户端收不到响应后的操作重放。

## 执行命令

```powershell
python -m pip install -e ".[dev,llm]"
python -m pytest -q
python -m ruff check .
python -m pip check
git diff --check
python examples/pr03_multiturn_demo.py
python examples/pr03_requirements_cli.py
```

重启继续：`python examples/pr03_requirements_cli.py --design-id <design-id>`。
命令行默认离线抽取，无真实模型费用；`--llm` 需要
`BEARING_LLM_ENABLED=true`、`BEARING_LLM_API_KEY`、
`BEARING_LLM_BASE_URL` 与 `BEARING_REQUIREMENTS_MODEL`
（或现有 `BEARING_PLANNER_MODEL`）明确配置。

## 验收等级与限制

- **SOFTWARE_ACCEPTED**：只有在 Linux/Windows 全 CI、CLI/demo、
  R01–R20 和故障测试确实通过后才能标记。通过 pytest 不代表工程专业验收。
- **REAL_EXTRACTOR_PENDING**：默认不调用外部真实 LLM；若没有保留真实
  模型试验记录，不宣称经过真实模型验证。
- **DOMAIN_PENDING**：专业工程标准、范围规则审核与专业输入正确性尚待 PR-04，
  正式材料/润滑油/间隙/轴承宽度推荐待 PR-05，预校核 PR-06，
  方案反馈 PR-07，生产身份鉴权与 UI PR-08。
- 当前数值和简单术语抽取为保守的 V1 支持范围；复杂自然语言
  可以明确要求澄清，不宣称具备无限制中文语义理解。
- 目前 `InteractionService.confirm_parameter`、约束批准/拒绝命令
  具有 revision 绑定和原领域 CAS；对话 `submit_turn`、明确参数纠错具有
  用户操作收据。正式跨 HTTP 用户命令级业务收据可与 PR-08
  生产可信网关一起补全；不能因此降低已有确认和授权的守卫。
