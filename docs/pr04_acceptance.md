# PR-04 专业知识、规则与工程查表服务

## 目标

为后续 DesignAgent 和 ValidationAgent 提供可追溯的专业资料索引、规则仓库、工程数表仓库和确定性规则执行接口。PR-04 不实现完整 RAG 平台，不生成轴承候选，也不执行 DLAP。

## 本 PR 的实现

- SourceCatalog：登记资料名称、编号、版本、来源位置、文件状态和审核状态。
- KnowledgeRepository：对经过整理的短摘要做确定性词项检索，返回来源、章节和审核状态。
- RuleRepository：保存 RuleRecord，校验来源引用和版本，并生成确定性的规则集版本号。
- TableRepository：支持带单位的多维区间查表；边界由每行显式定义；不插值、不外推；零行命中返回 OUT_OF_RANGE，多行命中返回 AMBIGUOUS。
- RuleEngine：只执行 ACTIVE 且来源已核验的规则；支持参数比较和表格查找；返回结构化证据，不写入 DesignState。
- 用户约束评估：通过同一个 RuleEngine 的 evaluate_constraint 单独执行已批准的 ConstraintRecord，不把用户约束伪装成 ISO 标准规则。

## 当前导入的资料状态

项目提供的 2024 标准草案压缩包包含：

| 资料 | 索引内容 | 当前状态 |
|---|---|---|
| GB/T 21466.1-2024 草案 / ISO 7902-1:2020 参考 | 适用范围、模型假设、层流/紊流、不确定性、计算流程 | DRAFT_EXTRACTED |
| GB/T 21466.2-2024 草案 / ISO 7902-2:2020 参考 | 特征数值资料位置 | DRAFT_EXTRACTED；详细表格提取后置 |
| GB/T 21466.3-2024 草案 / ISO 7902-3:2020 参考 | 许用最小膜厚、许用最大比压、许用温度、平均间隙比 | DRAFT_EXTRACTED |

这些中文文件是用户提供的草案。09 文件含有待填写的发布日期/实施日期等占位内容。PR-04 只登记元数据和简短内容摘要，不将标准全文或数值表复制到公开仓库。所有草案来源、规则和表格均保持 DRAFT_EXTRACTED。

特别是 09 第 8 节平均间隙比表、第 5.1 节最小膜厚表以及第 6/7 节许用参数，不会在缺少来源核验和轴承专业人员审核时作为正式推荐值或正式校核阈值。当前默认表格没有数值行，查表明确返回 BLOCKED_UNAPPROVED。

## 规则生命周期

规则沿用现有 RuleStatus：

DRAFT_EXTRACTED -> SOURCE_CHECKED -> EXPERT_APPROVED -> ACTIVE

ACTIVE 规则必须有精确 source_version、reviewer 和可执行定义。当前默认知识库没有 ACTIVE 的标准数值规则。单元测试中的 ACTIVE 合成 fixture 仅用于验证执行器，不会进入默认知识库。

## 边界

- 不新增第二个数据库；本 PR 的默认目录是代码内只读资料清单，仓库对象可由后续持久化适配器替换。
- 不修改 StateManager，不直接写回 DesignState。
- 不将 R2 解释为工程规则已齐备。
- 不推荐轴承宽度、间隙、材料或润滑油的正式数值。
- 不计算油膜压力分布、最小膜厚、温度场或热平衡。
- 不接入 DLAP。
- 不引入向量数据库、完整 OCR 流水线、知识图谱或企业级材料/油品数据库。

## 验收场景

1. 检索“间隙比”返回 09 第 8 节、来源编号、版本和 DRAFT_EXTRACTED 状态。
2. 默认知识库中的草案规则不能被 RuleEngine 执行。
3. 默认 09 间隙比表没有活动数值，查表返回 BLOCKED_UNAPPROVED。
4. ACTIVE 合成比较规则能够对 60 mm 与 50 mm 的边界确定性返回 FAIL，对 40 mm 返回 PASS。
5. 用户安装宽度上限等 ConstraintRecord 只有 approved 后才允许评价；评价来源标记为 user-constraint。
6. 数值单位可转换；量纲错误、缺失输入、未核验固定输入不能返回 PASS。
7. 查表区间边界唯一；越界不外推；区间重叠返回 AMBIGUOUS。
8. 同一规则集内容生成相同版本号。
9. 既有 PR-01、PR-02、PR-03 回归测试继续通过。

## 执行命令

PowerShell 命令：

python -m pytest -q tests/knowledge tests/rules
python -m pytest -q
python -m ruff check .
python -m pip check
python examples/pr04_knowledge_demo.py
git diff --check

## 验收声明

PR-04 完成表示软件具备最小的来源索引、规则仓库、查表和确定性执行能力。它不表示 07/09 草案已被正式批准，也不表示已经获得可用于工程推荐的间隙、膜厚、比压或温度数值。
