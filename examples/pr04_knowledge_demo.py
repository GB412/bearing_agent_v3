from bearing_agents.knowledge.defaults import build_default_knowledge_base
from bearing_agents.knowledge.models import TableLookupStatus


def main() -> None:
    knowledge = build_default_knowledge_base()

    print("Knowledge search: clearance ratio")
    for hit in knowledge.knowledge.search("平均间隙比", limit=3):
        print(
            f"- {hit.entry.title}: {hit.entry.status}; "
            f"{hit.source.document_number}, section {hit.entry.section}"
        )

    lookup = knowledge.tables.lookup(
        "draft-09-table-5-clearance-ratio",
        {"journal_diameter": (100, "mm"), "surface_speed": (7.85, "m/s")},
    )
    print(f"\nTable lookup: {lookup.status}")
    print(lookup.message)
    assert lookup.status == TableLookupStatus.BLOCKED_UNAPPROVED
    print("\nNo draft numeric value was used as an engineering recommendation.")


if __name__ == "__main__":
    main()
