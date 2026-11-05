# PR-13: 中文交互演示（框架验收）

## 运行

```powershell
git switch main
python -m pip install -e ".[dev,llm]"
python examples/interactive_design.py --db .venv/design.sqlite
```

真实模型 API 必须显式开启；请先在当前 PowerShell 会话中设置：
```powershell
$env:BEARING_LLM_ENABLED="true"
$env:BEARING_LLM_API_KEY="<填入真实密钥>"
$env:BEARING_LLM_BASE_URL="https://api.openai.com/v1"
$env:BEARING_PLANNER_MODEL="<你有权限的模型名>"
$env:BEARING_REQUIREMENTS_MODEL=$env:BEARING_PLANNER_MODEL
python examples/interactive_design.py --llm --db .venv/design-real.sqlite
```

**不要把真实密钥提交到仓库**。真实 API 调用仅发生在显式 `--llm` 模式；模型失败时不自动回退到伪 Planner。CI 不接触付费密钥，不能替代本地真实模型验收。

交互命令：`:show`、`:run`、`:approve 约束ID 版本`、`:confirm 参数ID 版本`、`:correct 参数ID 版本 新描述`、`:report [文件名]`、`:quit`。退出后，可使用相同数据库及 `--design-id` 恢复设计。

示例中文输入：
```text
我要设计圆柱径向动压滑动轴承，单一稳态，轴径100mm，载荷12kN，转速1500rpm，轴承宽度60mm
轴承宽度不能超过70mm
```

声明：当前默认专业知识库未激活完整经专家审核的轴承专业限值，缺少油膜压力、最小膜厚、温度场等 DLAP 求解。不能将 `REVIEW_REQUIRED`、演示回路或少量基础派生指标描述为专业工程校核通过；导出报告统一标记 `ENGINEERING_DOMAIN_PENDING`。

## 验收

- [ ] Linux Python 3.11 + Windows Python 3.14 全量测试、Ruff、pip check、diff check。
- [ ] 离线 CLI 中用户需求经证据核验，生成部分候选/提示规则缺口。
- [ ] 中文显式宽度、径向间隙可作为用户提供的设计变量；宽度上限仍需用户批准为约束。
- [ ] CLI 可导出包含引用、候选版本、状态和清晰工程边界的 Markdown 报告。
- [ ] 未启用真实模型环境时 `--llm` 拒绝启动，不暗中降级。
- [ ] 真正真实模型 API 的端到端测试在用户本地配置密钥后运行；未运行时标记 `REAL_API_PENDING`。

代码设计原则：复用 `BearingDesignApplication`、`InteractionService`、`LLMPlanner`、`LLMExtractor`、`StateManager`；只添加一个 CLI 和最小的设计变量提取支持，不增加 Agent、数据库、Web UI、复杂插件或额外消息队列。
