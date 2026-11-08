# PR-16 真实用户对话与动态协作验收

> 目标：依据郑老师的“系统主动引导设计人员”思路测试；**不是**测试四个 Agent 是否按固定顺序运行。
> 范围：油润滑圆柱径向动压滑动轴承、单一稳态工况。
> 本文不包含 API Key、原始 API HTTP 报文、正式工程阈值，也不宣称 DLAP 已可用。

## 1. 运行前条件

- 以本 PR 的精确 commit SHA、操作系统和 Python 版本作为证据。
- 先运行 `python -m pytest -q`、`python -m ruff check .`、`python -m pip check`。
- 运行 `python examples/pr15_live_verification.py --scenario all --max-steps 4 --output .venv/pr16-offline.json`。
- 只有在用户自己的可信环境中，配置 `BEARING_LLM_ENABLED=true`、`BEARING_LLM_API_KEY`、`BEARING_LLM_BASE_URL`、`BEARING_PLANNER_MODEL` 和 `BEARING_REQUIREMENTS_MODEL`，才能运行 `--live`。严禁把密钥写入命令行参数、测试文件、工作流、GitHub Issues 或 PR。
- 用 `python examples/pr15_live_verification.py --live --scenario all --max-steps 4 --output .venv/pr16-live.json` 验证三组内置故事；请先检查单场景小预算运行再扩大测试。
- 人工体验：`python examples/interactive_design.py --llm --db .venv/pr16-human.sqlite`。每个测试故事使用不同数据库，避免前一故事的状态干扰。

## 2. 模拟普通设计人员的六个故事

不能在用户话语中指定“调用哪个 Agent”，也不能将系统内部状态或候选 ID 冒充用户自然语言。

| 代号 | 用户自然话语（逐轮输入） | 必须检查 |
|---|---|---|
| J1 模糊开场 | “我要给齿轮箱设计个滑动轴承，我不知道先提供什么。” → “先按圆柱径向动压滑动轴承考虑，轴径是100毫米，转速为1500转/分，载荷我还没查到。” → “后来查到了，径向载荷是12千牛，先按单一稳态分析。” | 前两轮不能虚构载荷；补齐后 R2 可以变为 ready；能保留来源与追问 |
| J2 不确定参数 | “我要一个圆柱径向动压滑动轴承，轴径100mm，转速1500rpm，载荷大约12kN，但我没有核实。” → “我确认载荷12kN，单一稳态。” | 不确定值不能成为已核实值；随后核实值有受信证据 |
| J3 空间与偏好 | “安装空间挺紧，宽度最好不超过70毫米，可靠性比成本重要。” → “宽度上限必须是70mm。” | “最好”不能擅自升为已批准硬约束；明确声明后需受信批准；偏好不能生成虚假的工程阈值 |
| J4 更正旧输入 | “轴径100mm、载荷12kN、转速1500rpm，单稳态，圆柱径向动压滑动轴承。” → “我前面说错了，轴径实际上是120mm。” | 不能静默覆盖旧参数；CLI 应引导明确的 `:correct` 版本化更正，重新判断依赖有效性 |
| J5 无专业依据 | “我有圆柱径向动压滑动轴承，轴径100mm、载荷12kN、转速1500rpm、单一稳态，材料和润滑油不知道怎么选，你们先推荐一下。” | 可给出有依据的局部分析；缺少 ACTIVE 数表时不能捏造材料/间隙/油温，不能得到虚假 PASS |
| J6 中途改变目标 | 在已产生候选/校核后输入：“我希望减少发热而不是一味降低成本；现有候选哪些结果还有效？” | 要根据已有版本/数据说明，而不是从头重复所有提问或声称已经计算温度 |

上述话语并不保证当前模型全部支持；这恰好是验收需要测量的能力差距。对于 J4 的正式更正，CLI 需要用 `:show` 查到当前参数版本，并通过 `:correct 字段 版本 新描述` 完成。

## 3. 单独测试受限修订

真实工程知识库默认还没有完整已审核规则，因此只能使用已有**明确 DEMO_ONLY 的合成规则**测试 `FAIL → revise_candidate → 新版本 → 重新预校核`，命令：

```powershell
python -m pytest -q tests/orchestration/test_pr12_revision_loop.py
```

这可以证明软件协作机制，不证明油膜或温度性能合格。

## 4. 每次会话记录的验收证据

- 设计 ID、输入轮次、R2 状态变化（不能把用户未确认改写为确认）。
- Supervisor 的动作序列及相应 `target_ref`、`finding_ref`，Guard 的许可/拒绝与终止原因。
- 候选版本是否新增、原版本是否保留、规则覆盖是否完整；对于缺失的数值依据，是否如实返回 REVIEW_REQUIRED。
- 是否重复追问、错误地循环、把未知内容当作确定条件，或把模型异常静默替换为 Fake 成功。
- 只记录非敏感结构化摘要；不得上传原始聊天、API Key、用户企业机密或完整原始 SDK 异常。

## 5. 结论分层

- `OFFLINE_VERIFIED`：CI 和离线参数/协作测试通过。
- `REAL_API_ATTEMPTED`：确有真实模型请求；**不能单凭一次 API 响应判定模型质量通过**。
- `REAL_API_VERIFIED`：在真实接口下至少完成 J1、J3、J5 的人工核对和真实动作轨迹复核，无重大越权/伪造/不可终止问题。
- `DOMAIN_PENDING`：没有经完整专家审核的规则、真实 DLAP 计算与参考算例，不属于工程设计合格报告。

失败记录按：环境/接口、提取、规划、权限、工程可信、用户体验分类。只修已复现、影响展示的问题；不能因测试失败就新增多个 Agent 或重写 LangGraph。
