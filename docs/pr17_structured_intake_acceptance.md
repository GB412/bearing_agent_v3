# PR-17｜需求结构化录入专项验收（暂不测试设计与 DLAP）

## 范围

只验证：用户中文输入 → LLM/Pydantic JSON 结构化提取 → 轻量业务校验 → 可信 StateManager 写入 → 展示当前已录入内容、未决事项和 R2 就绪状态。

**不运行 Supervisor，不生成候选，不调用求解器。** 不用旧的 quote/start/end 字符定位合同。模型只负责提出语义结构，消息 ID、写入权限、参数修订号及用户审批仍由程序掌握。

## 本地运行（Windows PowerShell）

在仓库项目目录，先确认当前分支为 `fix/pr17-requirements-llm-partial-schema`，安装 `.[dev,llm]`，并运行：

```powershell
python -m pytest -q
python -m ruff check .
python examples/interactive_design.py --intake-only --db .venv/pr17-intake-offline.sqlite
```

真正的 DeepSeek 专项验收需要在当前终端安全配置 `BEARING_LLM_ENABLED`、`BEARING_LLM_API_KEY`、`BEARING_LLM_BASE_URL`、`BEARING_PLANNER_MODEL` 和 `BEARING_REQUIREMENTS_MODEL` 后，执行：

```powershell
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$env:PYTHONIOENCODING = "utf-8"
python examples/interactive_design.py --llm --intake-only --db .venv/pr17-intake-real.sqlite
```

启动后应出现 `INTAKE_ONLY`，不会出现 `Supervisor:` 调度轨迹。`:run` 在该模式下不可用。每组独立故事使用不同数据库，或记录已有 design-id 并通过 `--design-id` 继续会话。

## 分组测试（逐轮输入、每轮查看录入结果）

| 场景 | 普通用户输入 | 必须检查 |
|---|---|---|
| A1 明确条件 | “我要设计油润滑圆柱径向动压滑动轴承，轴径100mm，载荷12kN，转速1500rpm，单一稳态。” | scope 已识别，D=100mm、F=12000N、n=1500rpm，工况为单一稳态，R2=True |
| A2 分步补充 | “我先设计圆柱径向动压滑动轴承，轴径100毫米，转速1500转/分，载荷没查到。” → “后来查到了，径向载荷是12千牛，单一稳态。” | 第一轮绝不编造载荷，第二轮输入正确合并，不重复要求轴径 |
| B1 不确定值 | “载荷大约12kN，轴径100mm。” | 载荷不能直接变成确定性 PROVIDED，轴径应被保存 |
| B2 用户不知道 | “载荷我还没查到，先告诉我需要什么。” | 不得凭空出现载荷值 |
| C1 软偏好 | “宽度最好不超过70mm。” | SOFT、未批准，不能当硬性限制 |
| C2 硬约束 | “安装宽度必须不超过70mm。” | HARD、仍须独立审批 |
| D1 更正 | 在已有轴径100mm的设计中输入“我刚才说错了，轴径应该是120mm。” | 不静默覆盖原值，需版本化 `:correct` 操作 |
| D2 重复与冲突 | “轴径100mm，轴径120mm。” | 不随意挑一个值保存，提示冲突或澄清 |
| E1 范围以外 | “我要设计滚动轴承。” | 明确报告 unsupported，不能进入已有圆柱径向动压设计流程 |

测试时观察“参数（值、单位、来源标记、版本）”“工况”“约束 severity/approved”“本轮未录入”和“下一步问题”。如未达预期，记录最小复现文本、实际结构化字段及状态差异；不需要采集 API Key、HTTP 报文或原始服务商异常。

## 实现边界和风险

- JSON Schema 只限制结构，不能证明每个工程值都真实。已知明确信息采用轻量一致性检查，未知和歧义应要求澄清；不恢复字符级定位验证。
- 对未被现有正则识别的复杂语义，仍可能需要真正的 LLM 理解或用户确认。首版没有完成上下文省略代词（如“就按刚才那个”）的所有情况。
- 不确定值现阶段保留在用户消息及本轮澄清反馈中，尚未建设正式的估算参数候选管理；不能拿它给 DLAP 计算。
- `--intake-only` 使用现有权威数据库和安全边界，不增加新 Agent 或新状态机。
- `OFFLINE_VERIFIED` 和 `REAL_API_VERIFIED` 必须分开；自动化测试通过不意味着真实 DeepSeek 已通过现场验收。
