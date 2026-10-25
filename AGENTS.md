# Project Instructions

- 本项目使用 Python 3.11+、Pydantic 和 LangGraph。
- StateManager 是工程状态的唯一受信写入入口。
- Agent 不得伪造用户确认或硬约束来源。
- 保留已有 PR-01 安全契约。
- 所有新增功能必须包含 pytest 测试。
- 不得把预校核等同于 DLAP 性能验证。
- 一次只实现当前明确指定的 PR。
- 不自动合并 PR 或继续下一个 PR。
- 规划冲突时优先报告，不擅自重构。
