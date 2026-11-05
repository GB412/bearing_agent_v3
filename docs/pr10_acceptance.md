# PR-10：ValidationAgent 校核证据诊断与安全修订提示

## 目标

不改变已有确定性 `RuleEngine` / `ValidationAgent.evaluate` 的权威结论，在独立的**只读诊断层**解释已经落库的候选预校核报告，让用户知道“缺少什么、违反了什么、下一步应找谁处理”。

本 PR 解决的是轻量诊断骨架，不代表已完成专业解释型 LLM，也不接入 DLAP。

## 实际能力

- 只允许从已存在的 CandidateDesign ID + 版本读取**已持久化**的 `CandidatePrecheckReport`。
- 将缺少设计变量、无 ACTIVE/已审核规则覆盖、规则失败/待复核以及失效旧报告转为结构化 `ValidationFinding`。
- 为每项发现生成受控 `next_action`，如 CLARIFY_REQUIREMENT、REVIEW_RULE_SOURCE、REVIEW_DESIGN_VARIABLE、RECHECK_INPUT、EXPERT_REVIEW。
- 仅对尚未确认的候选设计变量给出“可讨论修订”提示；用户固定输入、已确认参数及硬约束不可列为自动调整对象。
- 不输出无来源的“加大间隙”“降低油温”“把材料换成 X”等具有方向性的工程结论。
- `ValidationService.diagnose` 提供可信应用入口，`BearingDesignApplication.precheck_candidate` 保持原始 `execution`、`report`、`state_version` 结构，同时额外返回 `diagnosis`。
- `PRECHECK_PASS` 只代表当前有效预校核；不自动生成改进方案，不声称性能求解完成。
- `STALE` 必须先重新校核，不能继续拿旧失败项指导具体修订。

## 扩展性与过度设计审查

- 没有新增数据库、StateManager 字段、Agent、任务状态或 LangGraph 节点。
- 不复制 RuleEngine；只解释已保存的规则执行结果。
- 使用少量有类型的诊断结果，下一步 PR-11 可直接消费 `next_action`。
- 当前版本不新增独立 LLM 排序器，避免仅为调整展示顺序而增加与 PR-08、PR-09 重复的模型适配基础设施。
- 后续需要专业解释时，可以注入受控 LLM 解释器，但解释不能覆盖 `precheck_status`、规则来源和允许修订范围。

## 验收

1. 部分候选的缺失设计变量得到明确解释。
2. 审核规则不足时返回规则覆盖缺口，不误判 PASS。
3. 有可信已存 FAIL 报告时，显示规则引用和目标参数。
4. 用户固定输入与已确认设计变量不能进入可自动修改列表。
5. 旧候选的 STALE 报告优先提示重新校核。
6. 非当前候选版本、未落库报告、伪造输入摘要均拒绝诊断。
7. 应用层原有 precheck API 兼容，并新增 diagnosis。
8. Linux/Windows CI 全量回归和 Ruff 通过。

## 专业边界

软件预校核和专家规则批准是两项独立验收。PR-10 的建议只说明下一步应该核对什么，并不证明可安全修改哪一个数值或用多大的幅度修订。当前默认知识库仍无完整审核规则/专业求解结果。
