# PR-02 验收记录：精简的受控 LangGraph 骨架

基线：`main@5edb6569f00f913e0c9469290a7acb2867feffcc`。
分支：`feat/pr02-langgraph-runtime`。2026-10-25 实施。
优先依据：用户批准的精简要求 > V3.4 > V3.3，仍只交付一个 PR。

## 结果与命令

本地 Windows / Python 3.14：全量 **134 passed**（PR-01 原 92 项文件未改动），
Ruff、`git diff --check`、`pip check` 通过。Langchain-core 的 Pydantic v1
兼容导入在 Python 3.14 发出一条上游 warning；项目使用 Pydantic v2，不隐藏该警告。
CI 增加 Linux/Python 3.11、Windows/Python 3.14 两组；远端结果以实际 PR checks 为准。

```powershell
python -m pip install -e ".[dev]"
python -m pip check
python -m pytest -q
python -m ruff check .
git diff --check
python examples/pr02_fake_dynamic_demo.py
python examples/pr02_interrupt_recovery.py
python -m pytest -q tests/orchestration/test_recovery.py
```

离线动态图输出三条路径：空设计/缺载荷为 clarify → MISSING_INPUT；可信 R2 为
analyze_conditions → generate_candidate（仅演示意图）→ produce_summary。
可用 `--output path.json` 保存第一条演示命令的完整 trace。所有数字均为
SYNTHETIC_WORKFLOW fixture，不是推荐参数；Fake 不写候选，也不产生 PRECHECK_PASS。

## V3.4 F01–F12 对应证据

| ID | 自动化测试/断言 | 本 PR 结果 |
|---|---|---|
| F01 | `test_f01_empty_state_only_clarifies`；参数/候选保持空 | PASS |
| F02 | `test_f02_missing_load_is_not_a_design_gate`；R2=false | PASS |
| F03 | `test_f03_state_driven_loop_uses_existing_facts`；动态三动作、演示标记 | PASS |
| F04 | `test_f04_f05_fake_patch_is_rejected_at_both_boundaries`；直接 StateManager 与 Fake 输出双边界 | PASS |
| F05 | 同上参数化 user-origin HARD 约束；领域事实不变 | PASS |
| F06 | `test_f06_illegal_plans_never_dispatch`；非法 action/executor/真实仿真均零派发；另测 schema/input refs | PASS |
| F07 | `test_f07_stale_decision_never_dispatch`、`test_f07_domain_change_during_agent_call_cannot_be_overwritten` | PASS |
| F08 | `test_f08_old_json_and_distinct_dependency_semantics`、实际旧 SQLite JSON、旧前置新鲜性阻断 | PASS；无 typed consumed refs |
| F09 | `test_f09_changed_inputs_expire_old_request`（目标/依赖/规则集）及候选 target 协议测试 | PASS；不执行正式候选确认 |
| F10 | `test_f10_duplicate_resume_has_one_task_effect`、任务 CAS/重复操作/意图冲突 | PASS；保证限于任务效果 |
| F11 | `test_f11_committed_task_replays_after_real_checkpoint_failure`，两个故障模式；另有跨进程 interrupt/resume | PASS；真实 SqliteSaver |
| F12 | no-progress、工具异常、非法计划、步数预算及 simulation_unavailable 测试 | PASS；有限停止，无虚构性能 |

V3.3 旧编号映射：F01–F03 不变；F04→新 F04/F05；F05→新 F06/F07；
F06→新 F09；F07→新 F11；F08→新 F12；F09→新 F08；F10→新 F12 仿真项。

## 故障恢复记录

`recovery_worker.py` 是测试专用子进程入口，生产使用原版官方 saver。
测试专用 FaultSaver 在任务 complete 已提交后，同时阻断 checkpoint 和 pending
writes 两种保存入口，确保丢失节点结果而确实需要重放。

| 进程 A 故障 | 退出码 | A 退出时业务状态 | 新进程 B 结果 |
|---|---|---|---|
| saver 写入抛异常 | 1 | version=3；1 个 COMPLETED 任务；3 个事件；3 条操作日志 | MISSING_INPUT；receipt replayed=true；状态与计数不变 |
| `os._exit` 强制终止 | 71 | 同上，任务效果已提交 | 同上，真实磁盘 checkpoint 恢复 |
| 正常 interrupt 后进程退出 | 0 | 等待任务绑定参数 revision、thread、规则版本及输入摘要 | 新进程可信 resume；version 4→5；工程参数不变 |

另测 journal 插入失败时业务 JSON/事件/版本一并回滚。幂等检查先于 CAS；
同 operation ID 不同意图/用户拒绝冲突明确报错，不能重复提交。

## 接口、文件与限制

核心新增接口：`StateManager.apply_task_command`、`TaskCommand/TaskReceipt`、
`open_runtime`、`Runtime.invoke/recover/resume`、`task_plan_view`。
公开 PR-01 接口不改名；StatePatch 没有任务写入字段。
task_plan 是唯一任务记录；新增 `task_operations` 仅保存幂等凭据，不是第二套任务表。
三项以内活动任务，串行运行，受控状态转换；计划修订/原因使用现有 StateEvent。

修改文件按职责分组：

- 协议/领域：`domain/agent_protocols.py`、新增 `domain/tasks.py`。
- 状态/存储：`core/state_manager.py`、`core/dependency_tracker.py`、`infra/state_repository.py`。
- 编排：新增 `orchestration/contracts.py`、`orchestration/workflow.py`，没有通用 Agent runtime。
- 验证：新增 `tests/orchestration/` 的 fixtures、任务/动态图/中断/恢复测试及子进程 helper。
- 演示：新增两个 `examples/pr02_*.py`。
- 配置/说明：`pyproject.toml`、CI、README、架构决策、本验收记录及协议文档。

明确推迟的验收责任：

| 事项 | 责任 PR |
|---|---|
| 真 LLMPlanner、真实模型实验 | PR-02B |
| 完整可信用户消息/纠错事件、参数操作恢复幂等 | PR-03；API/UI 映射到 PR-08 |
| 正式候选生成写入的复合提交幂等 | PR-05；迭代修订扩展在 PR-07 |
| typed consumed refs、精准消费追踪、正式候选接受/拒绝 | PR-07；交互呈现在 PR-08 |

不建设通用事务/迁移/不可变记录平台，不引入 RAG、ISO、专业 Agent、UI、
DLAP 或并行调度。这里只保证本 PR 的任务效果幂等；不声明跨库 exactly-once。
确认仅解决演示任务，绝不等于参数/候选工程批准。SQLite saver 适合本地原型。

软件自测：PASS，正式审阅待定。领域验收：NOT_APPLICABLE。
回滚须保存旧业务库备份；新版本可读旧 JSON，旧版本未必认识新增任务字段。
用户已有未跟踪 `AGENTS.md` 仅作为本地约束读取，不纳入本 PR。

## 审阅边界修复

任务结果提交遇到 CAS 冲突时，运行时最多重试三次；每次都重读权威状态，并要求工程
输入摘要不变、任务仍为 RUNNING、更新版本下 Guard 仍允许该动作。FakeAgent 不会因提交
重试而再次执行。输入变化或无法安全完成时，现有任务操作将其转为 STALE 后结束运行。
派发前 Guard 拒绝同样会将已启动任务转为 STALE。失效操作最多尝试三次 CAS；持续冲突时
抛出明确错误并保留可恢复的图节点，不会无限循环。
结束的图执行只有在同一确认意图已有持久操作收据时才允许幂等返回；否则拒绝新增确认。
回归覆盖见 `test_task_only_version_change_during_agent_call_does_not_strand_running_task`、
`test_guard_rejection_after_start_does_not_leave_task_running`、
`test_trusted_resume_cannot_create_confirmation_after_graph_has_ended`。

FakeAgent 的 `AgentResult` 当前只存在于执行栈中；`last_result_ref` 指向提交事件而不是可
读取的结果内容，且本 PR 没有实际读取该结果的消费者。可读取、受大小限制的结果摘要留给
PR-02B 评估，不新增结果数据库。
