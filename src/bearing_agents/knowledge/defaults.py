from dataclasses import dataclass

from bearing_agents.domain.agent_protocols import RuleRecord
from bearing_agents.domain.enums import RuleStatus
from bearing_agents.knowledge.catalog import KnowledgeRepository, SourceCatalog
from bearing_agents.knowledge.models import (
    EngineeringTable,
    KnowledgeEntry,
    SourceDocument,
)
from bearing_agents.knowledge.repositories import RuleRepository, TableRepository


@dataclass(frozen=True)
class KnowledgeBase:
    sources: SourceCatalog
    knowledge: KnowledgeRepository
    rules: RuleRepository
    tables: TableRepository


def build_default_knowledge_base() -> KnowledgeBase:
    """Build the small V1 source index; draft values are deliberately not activated."""
    sources = SourceCatalog(
        [
            SourceDocument(
                source_id="draft-gbt-21466-1-2024",
                title="稳态条件下流体动压径向滑动轴承圆柱形轴承 第1部分：计算原理",
                document_number="GB/T 21466.1-2024",
                version="2024-06-21-draft / ISO 7902-1:2020",
                document_status="DRAFT",
                review_status=RuleStatus.DRAFT_EXTRACTED,
                reference_standard="ISO 7902-1:2020",
                locator=(
                    "2024_滑动轴承标准草案.zip/20240621-标准草案/"
                    "07 滑动轴承 稳态条件下流体动压径向滑动轴承 圆柱形轴承 第1部分：计算原理.docx"
                ),
                description="User-supplied Chinese draft; publication and expert approval are not established.",
            ),
            SourceDocument(
                source_id="draft-gbt-21466-2-2024",
                title="稳态条件下流体动压径向滑动轴承圆柱形轴承 第2部分：特征数值",
                document_number="GB/T 21466.2-2024",
                version="2024-06-21-draft / ISO 7902-2:2020",
                document_status="DRAFT",
                review_status=RuleStatus.DRAFT_EXTRACTED,
                reference_standard="ISO 7902-2:2020",
                locator=(
                    "2024_滑动轴承标准草案.zip/20240621-标准草案/"
                    "08 滑动轴承 稳态条件下流体动压径向滑动轴承 圆柱形轴承 第2部分：特征数值.docx"
                ),
                description="Large characteristic-value tables; structured extraction is deferred until a concrete model needs them.",
            ),
            SourceDocument(
                source_id="draft-gbt-21466-3-2024",
                title="稳态条件下流体动压径向滑动轴承圆柱形轴承 第3部分：许用运行参数",
                document_number="GB/T 21466.3-2024",
                version="2024-06-21-draft / ISO 7902-3:2020",
                document_status="DRAFT",
                review_status=RuleStatus.DRAFT_EXTRACTED,
                reference_standard="ISO 7902-3:2020",
                locator=(
                    "2024_滑动轴承标准草案.zip/20240621-标准草案/"
                    "09 滑动轴承 稳态条件下流体动压径向滑动轴承 圆柱形轴承 第3部分：许用运行参数.docx"
                ),
                description="User-supplied draft; the file contains placeholder publication dates and is not an approved rule source.",
            ),
        ]
    )

    entries = [
        KnowledgeEntry(
            entry_id="07-scope",
            title="计算方法的适用范围",
            summary=(
                "第1部分描述油润滑流体动压圆柱径向滑动轴承的稳态性能计算范围，"
                "并限定轴承结构、载荷位置和建模前提。该摘要用于定位原文，不是已批准的自动适用性判定。"
            ),
            source_id="draft-gbt-21466-1-2024",
            source_version="2024-06-21-draft / ISO 7902-1:2020",
            section="1",
            tags=["适用范围", "圆柱径向", "稳态", "支承结构"],
        ),
        KnowledgeEntry(
            entry_id="07-model-assumptions",
            title="雷诺方程模型假设",
            summary=(
                "第5.2节列出模型假设，包括润滑油流变性质、流动状态、油膜连续性、"
                "表面刚性和间隙方向等条件。使用模型前应逐项确认假设是否适用。"
            ),
            source_id="draft-gbt-21466-1-2024",
            source_version="2024-06-21-draft / ISO 7902-1:2020",
            section="5.2",
            tags=["雷诺方程", "模型假设", "层流", "牛顿流体"],
        ),
        KnowledgeEntry(
            entry_id="07-flow-regime",
            title="层流与紊流适用性",
            summary=(
                "第6.2节讨论通过雷诺数识别油膜流动状态，并指出该计算方法对紊流状态存在适用性限制。"
                "具体判据和计算输入仍需核对标准及专家意见。"
            ),
            source_id="draft-gbt-21466-1-2024",
            source_version="2024-06-21-draft / ISO 7902-1:2020",
            section="6.2",
            tags=["雷诺数", "层流", "紊流", "适用性"],
        ),
        KnowledgeEntry(
            entry_id="07-uncertainty",
            title="计算不确定性因素",
            summary=(
                "第6.3节提示扰动力、制造装配偏差、润滑油污染及腐蚀等不确定性因素。"
                "这些因素应进入风险提示和后续数据收集，而不是由模型自动假定为零。"
            ),
            source_id="draft-gbt-21466-1-2024",
            source_version="2024-06-21-draft / ISO 7902-1:2020",
            section="6.3",
            tags=["不确定性", "制造偏差", "污染", "风险"],
        ),
        KnowledgeEntry(
            entry_id="07-calculation-flow",
            title="计算流程与耦合关系",
            summary=(
                "第6.4至7.6节描述承载能力、最小膜厚、摩擦功耗、润滑油流量和热平衡之间的关系，"
                "部分性能量需要通过迭代求解。当前 PR-04 只建立知识索引，不实现该求解流程。"
            ),
            source_id="draft-gbt-21466-1-2024",
            source_version="2024-06-21-draft / ISO 7902-1:2020",
            section="6.4-7.6",
            tags=["计算流程", "最小膜厚", "摩擦功耗", "流量", "热平衡"],
        ),
        KnowledgeEntry(
            entry_id="08-characteristic-tables",
            title="特征数值表",
            summary=(
                "第2部分提供计算过程使用的特征数值。当前仅登记资料位置；"
                "不批量提取数值，也不在没有具体模型和审核的情况下插值或外推。"
            ),
            source_id="draft-gbt-21466-2-2024",
            source_version="2024-06-21-draft / ISO 7902-2:2020",
            section="特征数值表",
            tags=["特征数值", "无量纲系数", "数表", "后续计算"],
        ),
        KnowledgeEntry(
            entry_id="09-minimum-film",
            title="许用最小膜厚",
            summary=(
                "第5.1节涉及许用最小膜厚，并说明表面粗糙度、几何误差和变形等因素。"
                "数值表及公式尚未通过本项目的来源和专业审核。"
            ),
            source_id="draft-gbt-21466-3-2024",
            source_version="2024-06-21-draft / ISO 7902-3:2020",
            section="5.1",
            tags=["许用最小膜厚", "粗糙度", "磨损", "校核"],
        ),
        KnowledgeEntry(
            entry_id="09-maximum-pressure",
            title="许用最大比压",
            summary=(
                "第6节按轴承材料类别讨论许用最大比压。材料类别、制造工艺和适用条件"
                "必须与对应表格和来源一起核对，不能把平均投影比压直接等同于局部最大油膜压力。"
            ),
            source_id="draft-gbt-21466-3-2024",
            source_version="2024-06-21-draft / ISO 7902-3:2020",
            section="6",
            tags=["许用最大比压", "材料", "过载", "校核"],
        ),
        KnowledgeEntry(
            entry_id="09-maximum-temperature",
            title="许用最高温度",
            summary=(
                "第7节讨论轴承材料和润滑油对许用温度的影响。"
                "温度结论依赖材料和油品数据；没有实际热分析结果时不能判定温度通过。"
            ),
            source_id="draft-gbt-21466-3-2024",
            source_version="2024-06-21-draft / ISO 7902-3:2020",
            section="7",
            tags=["许用温度", "润滑油", "材料", "过热"],
        ),
        KnowledgeEntry(
            entry_id="09-clearance-ratio",
            title="平均间隙比经验值",
            summary=(
                "第8节给出与轴颈线速度和直径有关的平均间隙比经验资料。"
                "当前表格数据保持未启用状态；未完成边界、单位、例外和专家审核前不得给出正式数值推荐。"
            ),
            source_id="draft-gbt-21466-3-2024",
            source_version="2024-06-21-draft / ISO 7902-3:2020",
            section="8",
            tags=["平均间隙比", "间隙", "线速度", "轴颈直径", "参数推荐"],
        ),
    ]

    rules = [
        RuleRecord(
            rule_id="draft-07-applicability",
            source_document="draft-gbt-21466-1-2024",
            source_version="2024-06-21-draft / ISO 7902-1:2020",
            section="1",
            scope="cylindrical_radial_hydrodynamic",
            bearing_scope="cylindrical_radial_hydrodynamic",
            operating_scope="steady_state",
            inputs=["target_scope", "operating_regime"],
            operation="APPLICABILITY_REVIEW",
            status=RuleStatus.DRAFT_EXTRACTED,
            version="draft-1",
            tests=[],
        ),
        RuleRecord(
            rule_id="draft-09-clearance-ratio",
            source_document="draft-gbt-21466-3-2024",
            source_version="2024-06-21-draft / ISO 7902-3:2020",
            section="8",
            scope="cylindrical_radial_hydrodynamic",
            bearing_scope="cylindrical_radial_hydrodynamic",
            operating_scope="steady_state",
            inputs=["journal_diameter", "surface_speed"],
            units={"journal_diameter": "mm", "surface_speed": "m/s"},
            operation="TABLE_LOOKUP",
            table_ref="draft-09-table-5-clearance-ratio",
            status=RuleStatus.DRAFT_EXTRACTED,
            version="draft-1",
            tests=[],
        ),
        RuleRecord(
            rule_id="draft-09-minimum-film",
            source_document="draft-gbt-21466-3-2024",
            source_version="2024-06-21-draft / ISO 7902-3:2020",
            section="5.1",
            scope="cylindrical_radial_hydrodynamic",
            bearing_scope="cylindrical_radial_hydrodynamic",
            operating_scope="steady_state",
            inputs=["journal_diameter", "surface_speed"],
            units={"journal_diameter": "mm", "surface_speed": "m/s"},
            operation="TABLE_LOOKUP",
            table_ref="draft-09-table-2-minimum-film",
            status=RuleStatus.DRAFT_EXTRACTED,
            version="draft-1",
            tests=[],
        ),
    ]

    tables = [
        EngineeringTable(
            table_id="draft-09-table-5-clearance-ratio",
            title="第8节：平均间隙比经验值",
            source_id="draft-gbt-21466-3-2024",
            source_version="2024-06-21-draft / ISO 7902-3:2020",
            section="8",
            version="draft-1",
            status=RuleStatus.DRAFT_EXTRACTED,
            input_units={"journal_diameter": "mm", "surface_speed": "m/s"},
            output_units={"mean_clearance_ratio": "‰"},
            rows=[],
            description="Metadata only. Numeric cells are not activated pending expert review.",
        ),
        EngineeringTable(
            table_id="draft-09-table-2-minimum-film",
            title="第5.1节：许用最小膜厚经验值",
            source_id="draft-gbt-21466-3-2024",
            source_version="2024-06-21-draft / ISO 7902-3:2020",
            section="5.1",
            version="draft-1",
            status=RuleStatus.DRAFT_EXTRACTED,
            input_units={"journal_diameter": "mm", "surface_speed": "m/s"},
            output_units={"minimum_film_thickness": "μm"},
            rows=[],
            description="Metadata only. Numeric cells are not activated pending expert review.",
        ),
    ]

    source_catalog = sources
    return KnowledgeBase(
        sources=source_catalog,
        knowledge=KnowledgeRepository(entries, source_catalog),
        rules=RuleRepository(rules, source_catalog),
        tables=TableRepository(tables, source_catalog),
    )
