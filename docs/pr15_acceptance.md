# PR-15：真实 DeepSeek API 与多 Agent 动态框架验收

## 当前结论

- **OFFLINE_VERIFIED**：GitHub CI 在无密钥条件下运行 Python 全量测试、稳定的自然语言场景、Guard、权限、失效、候选/校核和受限修订。
- **REAL_API_PENDING**：仅有用户在自己的可联网设备实际执行 `--live` 并提供脱敏结果后，才可以写 `REAL_API_VERIFIED`。远程 CI 绝不使用或保存私人 API Key。
- **DOMAIN_PENDING**：默认 GB/T 草案并非完整已批准的行业规则，DLAP 没有接入。演示候选和合成规则不能证明正式工程合格。

### 目标与范围

基于已完成 PR-11～PR-14，不新增 Agent 或状态机，优先证明用户可以用日常中文提出需求，Supervisor 会根据上下文变化调度不同专业动作。

新的 `examples/pr15_live_verification.py` 支持离线和明确 opt-in 的真实模式。内置三组相对自然的多轮设计对话，不是直接向模型下达 Agent 指令：

- `missing_load`：轴径和转速明确，暂时缺少载荷，后续补充。
- `space_limit`：可靠性、安装空间限制、用户不愿提前定材料。
- `uncertain_design`：工况具备但专业参数缺少依据，检查系统是否如实提示。

每个会话记录真实执行动作、Guard 结果、候选版本和软件验收状态；不会保存用户原话、模型提示、API Key、HTTP 头或原始异常。

## A. 先在无密钥模式下校验

在本地 PowerShell 进入仓库：

```powershell
git switch main
git pull origin main
python -m pip install -e ".[dev,llm]"
python -m pytest -q
python -m ruff check .
python examples/pr15_live_verification.py --scenario missing_load --max-steps 4
```

不加 `--live` 绝不会实例化真实模型，这只能证明软件执行路径；禁止用 OFFLINE 记录替代真实 API 测试。

## B. 安全配置 DeepSeek V4 Pro

在当前 PowerShell 中设置**非秘密**的模型配置：

```powershell
$env:BEARING_LLM_ENABLED = "true"
$env:BEARING_LLM_BASE_URL = "https://api.deepseek.com"
$env:BEARING_PLANNER_MODEL = "deepseek-v4-pro"
$env:BEARING_REQUIREMENTS_MODEL = "deepseek-v4-pro"
```

使用不会把真实密钥写入 PowerShell 命令历史的输入方法（不要提交 `.env`、脚本或日志）：

```powershell
$secureKey = Read-Host "DeepSeek API Key" -AsSecureString
$keyPtr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
try {
    $env:BEARING_LLM_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($keyPtr)
}
finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($keyPtr)
    Remove-Variable secureKey, keyPtr
}
```

**提醒**：用户已经把一把密钥发送到聊天中，演示后请在 DeepSeek 控制台轮换该密钥。不可把密钥交给 GitHub Actions，也不可把密钥放在任何 `--output` 文件中。

## C. 真实模型冒烟与多轮验证（逐步放开成本）

先单场景小预算：

```powershell
python examples/pr15_live_verification.py --live --scenario missing_load --max-steps 3 --output .venv/pr15-missing-load.json
```

验收它能输出 `REAL_API_ATTEMPTED`、`real_api_observed: true`、真实模型 ID 和清楚的终止原因。**有一次真实请求并不代表规划正确**：还需要人工核对动作顺序、Guard、交互结果和工程边界。

再尝试另外两个场景：

```powershell
python examples/pr15_live_verification.py --live --scenario space_limit --max-steps 4 --output .venv/pr15-space.json
python examples/pr15_live_verification.py --live --scenario uncertain_design --max-steps 4 --output .venv/pr15-uncertain.json
```

最后做一次**真正的人机自由对话**，不是只跑脚本：

```powershell
python examples/interactive_design.py --llm --db .venv/pr15-human.sqlite
```

可自然输入：

1. “给齿轮箱做个滑动轴承初步方案，我不太清楚先需要哪些条件。”
2. “轴径是100毫米，转速1500转，载荷我现在没有。”
3. “我查了资料，径向12千牛，先按稳态分析。”
4. “宽度最多70毫米，材料先别帮我决定，帮我说清需要核实的依据。”

**不要故意命令它先调用什么 Agent。** 观察系统是不是主动问对问题、能否利用已有数据、是否避免越权。

## D. 验收矩阵：做了什么才算真正动态？

| 观察维度 | 可接受现象 | 错误现象 |
|---|---|---|
| 需求引导 | 能基于已知/缺少信息提出针对性问题 | 用户给过参数仍重复追问，或者发明载荷 |
| 动态路径 | 不同情境出现不同合法动作/对象 | 所有情境永远同一路径或循环 |
| 数据可信 | 未经确认的偏好只作提示，约束需用户批准 | 模型把主观提示变成工程硬约束 |
| 设计输出 | 有依据才提出参数，否则部分候选/待复核 | 无数表依据硬编间隙、材料或油温 |
| 校核反馈 | 有明确规则与结果才做 FAIL/PASS；缺覆盖 REVIEW_REQUIRED | 默认规则缺失却显示 PASS |
| 失效/版本 | 修改输入后保留历史、失效相关结果 | 旧候选被覆盖或旧校核继续当新结论 |
| 可靠性 | 模型服务失败终止，不悄悄切换 Fake | 把模型异常包装成成功 |
| 成本和隐私 | 不上传密钥至仓库；打印/报告不含凭据、原始请求 | 错误日志中出现密钥 |

结束时检查 `.venv/pr15-*.json`，仅分享经过审阅的非秘密字段；`git status` 应不出现密钥文件。尤其不要将带真实模型 API 的日志提交到仓库。

本次真实 API 的个人消费、响应稳定性、输出正确性、以及“是否真能展示”只能由用户机器的实际结果决定。若未运行，必须保持 `REAL_API_PENDING`。

## 过度设计审查

本 PR 只增加一个脚本、一组回归测试与验收文档，并对已有 CLI 做最小错误脱敏。不改变总控图结构，不新增 Agent、事件总线、插件层、候选数据库或数值求解器；真实 API 仍复用 `LLMPlanner`、`LLMExtractor`、`open_application`。
