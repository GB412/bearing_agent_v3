# bearing_agent_v3 — PR-01 审阅与修复任务 V1

**审阅对象**：https://github.com/GB412/bearing_agent_v3

**审阅版本**：`main`，commit `726acb25e9fcaf97b3bdcf4099b80b577b3c1f9c`（2026-10-24）

**审阅方式**：经 GitHub 连接读取远程仓库的文件、目录和提交信息并进行静态代码审阅；当前容器无法访问 GitHub，**未能在本地克隆或执行整个仓库的 pytest / ruff**。因此结论是“静态审阅：需要修复后再验收”，不是对实际 CI 执行结果的断言。

**总评**：分层合理；StateManager / Repository / DependencyTracker 的方向正确；基础计算公式正确。主要问题集中在状态写入旁路、工程参数类型和单位、约束与候选方案的失效传播。**不建议直接进入 PR-02**，先做一次 PR-01 修复提交。

## 1. 优先级与代码证据

### P0-01：`state_updates` 任意字段赋值绕过模型、单位及固定输入保护

- **位置**：[`src/bearing_agents/core/state_manager.py#L81-L123`](https://github.com/GB412/bearing_agent_v3/blob/726acb25e9fcaf97b3bdcf4099b80b577b3c1f9c/src/bearing_agents/core/state_manager.py#L81-L123)；[`domain/agent_protocols.py#L35-L43`](https://github.com/GB412/bearing_agent_v3/blob/726acb25e9fcaf97b3bdcf4099b80b577b3c1f9c/src/bearing_agents/domain/agent_protocols.py#L35-L43)。
- `patch.parameters` 进行了保护；但 `patch.state_updates` 的 `setattr(updated,key,value)` 允许直接替换 `parameters`、`constraints`、`candidate_designs`、`target_scope`、`confirmations` 等字段；对这些赋值也未执行完整的 Pydantic 校验。未来 Agent 一旦提交 StatePatch，风险更大。
- **修复**：禁止 `state_updates.parameters` / `state_updates.confirmations` / `state_updates.target_scope` 等敏感字段；优先采用类型化操作（`parameter_changes`, `constraint_changes`, `candidate_additions`, `confirmation_events` 等）及命令级白名单。提交前执行 `DesignState.model_validate(...)`，统一状态写权限与版本验证。
- **测试**：直接在 `state_updates` 中替换固定输入、构造非法类型、伪造确认、篡改设计 ID 等均应拒绝；正常更新候选方案、工况、约束则通过受控操作实现。

### P0-02：约束或规则变更不可靠地使旧预校核失效

- **位置**：[`src/bearing_agents/core/dependency_tracker.py#L12-L50`](https://github.com/GB412/bearing_agent_v3/blob/726acb25e9fcaf97b3bdcf4099b80b577b3c1f9c/src/bearing_agents/core/dependency_tracker.py#L12-L50)。
- `constraints -> constraint_precheck` 只是一个受影响指标；候选方案是否 stale 主要看 `candidate.source_parameter_revisions` 和 `journal_diameter`，并没有纳入约束版本、规则版本、审批版本或对候选设计的显式依赖。
- **修复**：为候选方案/预校核记录建立 `input_dependency_refs`（参数修订、约束 ID+版本、规则集版本、工况 ID+版本）；初版保守策略：约束集合变更使所有已预校核候选 `precheck_status=STALE`，必要时也应撤销旧用户确认或设置待重新确认。保存历史 `PRECHECK_PASS` 但不能作为当前有效结论。
- **测试**：轴承宽度 60mm、原限制 80mm、已 `PRECHECK_PASS`；限制改为 50mm，立即变 `STALE`；材料允许集变化也能正确重校核。

### P1-03：只校验单位，不规范化后续计算实际参数值

- **位置**：[`core/state_manager.py#L98-L107`](https://github.com/GB412/bearing_agent_v3/blob/726acb25e9fcaf97b3bdcf4099b80b577b3c1f9c/src/bearing_agents/core/state_manager.py#L98-L107)、[`core/unit_normalizer.py#L15-L38`](https://github.com/GB412/bearing_agent_v3/blob/726acb25e9fcaf97b3bdcf4099b80b577b3c1f9c/src/bearing_agents/core/unit_normalizer.py#L15-L38)、[`tools/engineering_calculator.py#L10-L23`](https://github.com/GB412/bearing_agent_v3/blob/726acb25e9fcaf97b3bdcf4099b80b577b3c1f9c/src/bearing_agents/tools/engineering_calculator.py#L10-L23)。
- 例如同一轴径可以由用户填 `100 mm` 或 `0.1 m`。保存时 `normalize()` 的计算结果被丢弃；后续若错误地把原值 0.1 传入 `journal_surface_speed(diameter_mm=...)`，线速度将相差 1000 倍。
- **修复**：保留原始值和单位以供追溯，但提供明确的 `get_quantity(parameter, target_unit)` 或统一的量值转换函数；所有计算工具仅接收明确单位的规范值。要求数值类型存成规范的数值（而不是带数值的字符串）。
- **测试**：100mm 和 0.1m 代入计算结果严格一致；12kN 与 12000N 同值；单位跨维度错用被拒绝。

### P1-04：所有参数统一 `float(value)>0`，类别数据与合法零值无法表达

- **位置**：[`domain/parameters.py#L8-L22`](https://github.com/GB412/bearing_agent_v3/blob/726acb25e9fcaf97b3bdcf4099b80b577b3c1f9c/src/bearing_agents/domain/parameters.py#L8-L22)、[`core/state_manager.py#L98-L108`](https://github.com/GB412/bearing_agent_v3/blob/726acb25e9fcaf97b3bdcf4099b80b577b3c1f9c/src/bearing_agents/core/state_manager.py#L98-L108)。
- 设计需求未来有 `shaft_material='bronze'`、指定油品、旋转方向等类别型字段；目前 StateManager 强制 `float()`，会拒绝字符串材料。也会拒绝数学上允许为 0 的信息；并且未知 parameter_id 使用任何已登记单位都可能被接纳（仅检查单位有效，不检查字段含义）。
- **修复**：为已支持的参数建立**轻量字段注册表**：ID、数据类型、物理量纲、合法值域、适用任务和允许的状态；数值型和枚举/文本型分开校验。保留向后扩展能力，不用在 PR-01 造完整滑动轴承 ISO 规则库。
- **测试**：类别型材料合法，数值字段不允许冒充文本；`journal_diameter` 不得配 N 单位；非负字段允许 0，严格正字段拒绝 0；True/False 不能被当成数值 1/0。

### P1-05：确认状态和字段角色的修改权限不完整

- **位置**：[`core/state_manager.py#L75-L113`](https://github.com/GB412/bearing_agent_v3/blob/726acb25e9fcaf97b3bdcf4099b80b577b3c1f9c/src/bearing_agents/core/state_manager.py#L75-L113)、[`domain/agent_protocols.py#L35-L43`](https://github.com/GB412/bearing_agent_v3/blob/726acb25e9fcaf97b3bdcf4099b80b577b3c1f9c/src/bearing_agents/domain/agent_protocols.py#L35-L43)。
- 当前 `source` 和 `actor` 是自由文本；Agent 可以提出 `status=CONFIRMED` 并自己填写 `confirmed_by`，没有权威确认操作。已有角色也没有锁定转换策略，例如硬约束角色改成设计变量需要强制审核。
- **修复**：使用受控的 `ConfirmParameter`/`ChangeParameterRole` 命令，证明来自交互层的用户确认；禁止普通 Agent 写补丁时把 `status` 直接提升 `CONFIRMED`。当前仅需接口及离线测试，真实登录身份权限可留给后续 UI 集成。固定输入数值保持不变时的正常“确认”也应允许，不能误当作重新赋值禁止。
- **测试**：Agent 自行确认必须拒绝；用户确认操作成功；变更 FIXED_INPUT 和 HARD_CONSTRAINT 的角色需要额外批准；`parameter_id` 与 map key 不一致则拒绝。

### P1-06：空项目“缺失字段列表”为空，易被后续总控误判为完整

- **位置**：[`core/state_manager.py#L141-L147`](https://github.com/GB412/bearing_agent_v3/blob/726acb25e9fcaf97b3bdcf4099b80b577b3c1f9c/src/bearing_agents/core/state_manager.py#L141-L147)、[`docs/decision_records.md`](https://github.com/GB412/bearing_agent_v3/blob/726acb25e9fcaf97b3bdcf4099b80b577b3c1f9c/docs/decision_records.md)。
- 当前接口只枚举“已存在且状态 MISSING 且带 required_for”的字段；但新设计初始化的 `parameters={}`。空列表不能代表 R1/R2 通过。
- **修复**：加入 `StageRequirementRegistry`/最小必需字段模板（仅支持当前目标类型，实际完善留给 PR-03）；提供明确的 `ReadinessResult {ready, missing, conflicts, not_configured}`。未配置规则时 **fail-closed**（`not_configured`），不能以空集合直接通过。
- **测试**：刚创建的空设计不能显示 ready_for_design=True；必需字段缺失列表正确，允许将轴承宽度标为设计变量无需用户先填具体数值。

### P2-07：README 最小示例自身不能运行

- **位置**：[`README.md#L29-L45`](https://github.com/GB412/bearing_agent_v3/blob/726acb25e9fcaf97b3bdcf4099b80b577b3c1f9c/README.md#L29-L45)。
- `StatePatch` 要求顶层 `source`，但示例只给 `patch.parameters` 内参数的 `source`，通过 Pydantic 模型验证时将因缺少 `patch.source` 失败。
- **修复**：补上顶层 `"source": "user"`；在测试中执行 README 示例（或独立 smoke test）以避免回归。

### P2-08：`model_copy(update=...)` 不执行 Pydantic 验证；任务状态为自由文本

- **位置**：[`core/dependency_tracker.py#L27-L48`](https://github.com/GB412/bearing_agent_v3/blob/726acb25e9fcaf97b3bdcf4099b80b577b3c1f9c/src/bearing_agents/core/dependency_tracker.py#L27-L48)、[`domain/agent_protocols.py`](https://github.com/GB412/bearing_agent_v3/blob/726acb25e9fcaf97b3bdcf4099b80b577b3c1f9c/src/bearing_agents/domain/agent_protocols.py)。
- `TaskRecord.status: str` 而仓库已经定义了 `TaskStatus`。对任务和状态的更新建议经过类型化结构和统一验证，避免错误状态进入业务库。

## 2. 已达成的良好设计（保留，不重构）

- 模块隔离清楚：`domain` 模型，`core` 状态与依赖，`tools` 工程公式，`infra` 数据库；属于合适的 PR-01 规模。
- 用 SQLite 的 `UPDATE ... WHERE state_version=?` 实现乐观并发控制，较适合当前原型。
- 缺值不伪造；已分离 `ParameterRole` 和 `ParameterStatus`；已保留事件历史、来源和候选方案版本。
- 已把径向间隙、直径间隙设为不同 parameter ID；基本圆周速度/投影比压公式正确，注释没有将平均比压混为最大油膜压力。
- 代码尚未实现 LangGraph / 多 Agent / DLAP，这符合 PR-01 的阶段边界，不应当当作缺陷。

## 3. 推荐修复顺序

1. P0-01 限制 state_updates、改为类型化更新与统一校验。
2. P0-02 修复约束变化/规则变化后候选预校核失效。
3. P1-03 / P1-04 统一量值转换、参数字段类型与合法值域。
4. P1-05 可靠的确认/角色变更事件与字段 ID 一致性。
5. P1-06 刚创建项目不能误判 R2 就绪。
6. P2-07 / P2-08 README 和模型质量收尾。

最后执行 `python -m pytest -q`、`ruff check .`；输出测试总数与结果、变更文件清单、架构变更决策、每项 P0/P1 的修复证据。**修复后停止，等待我再次验收，不要提前实现 LangGraph 或 Agent。**

## 5. 其他注意事项

仓库当前为**公开（public）**，且包含郑老师讨论逐字稿与项目研究记录。请用户自行确认这类资料是否适合公开。若包含不宜公开的研究讨论，建议改为私有仓库并评估是否需清理 Git 历史。此为信息治理建议，并非对已经发生泄露的判断。
