from bearing_agents.domain.enums import RuleStatus
from bearing_agents.knowledge.defaults import build_default_knowledge_base


def test_default_catalog_indexes_user_supplied_07_08_09_drafts():
    knowledge = build_default_knowledge_base()

    sources = {source.document_number: source for source in knowledge.sources.list()}
    assert set(sources) == {
        "GB/T 21466.1-2024",
        "GB/T 21466.2-2024",
        "GB/T 21466.3-2024",
    }
    assert all(source.document_status == "DRAFT" for source in sources.values())
    assert all(source.review_status == RuleStatus.DRAFT_EXTRACTED for source in sources.values())


def test_clearance_ratio_search_returns_source_and_section_without_activating_values():
    knowledge = build_default_knowledge_base()

    hits = knowledge.knowledge.search("轴承间隙比", limit=5)

    assert hits
    hit = next(item for item in hits if item.entry.entry_id == "09-clearance-ratio")
    assert hit.source.document_number == "GB/T 21466.3-2024"
    assert hit.entry.section == "8"
    assert hit.entry.status == RuleStatus.DRAFT_EXTRACTED
    assert "不得给出正式数值推荐" in hit.entry.summary


def test_default_knowledge_index_does_not_claim_standard_rules_are_active():
    knowledge = build_default_knowledge_base()

    assert knowledge.rules.list()
    assert all(rule.status == RuleStatus.DRAFT_EXTRACTED for rule in knowledge.rules.list())
    assert all(table.status == RuleStatus.DRAFT_EXTRACTED for table in knowledge.tables.list())
    assert all(not table.rows for table in knowledge.tables.list())


def test_search_is_deterministic_and_empty_query_returns_no_hits():
    knowledge = build_default_knowledge_base()

    first = knowledge.knowledge.search("最小膜厚", limit=5)
    second = knowledge.knowledge.search("最小膜厚", limit=5)

    assert first == second
    assert knowledge.knowledge.search("   ") == []
