from __future__ import annotations

import re
from collections.abc import Iterable

from bearing_agents.knowledge.models import (
    KnowledgeEntry,
    KnowledgeHit,
    SourceDocument,
)


class SourceCatalog:
    """Small, versioned source index; it stores metadata, not standard full text."""

    def __init__(self, sources: Iterable[SourceDocument] = ()):
        self._sources: dict[str, SourceDocument] = {}
        for source in sources:
            if source.source_id in self._sources:
                raise ValueError(f"Duplicate source ID: {source.source_id}")
            self._sources[source.source_id] = source

    def get(self, source_id: str) -> SourceDocument | None:
        return self._sources.get(source_id)

    def list(self) -> list[SourceDocument]:
        return [self._sources[key] for key in sorted(self._sources)]


class KnowledgeRepository:
    """Deterministic lexical search over curated summaries and source metadata."""

    def __init__(
        self,
        entries: Iterable[KnowledgeEntry],
        sources: SourceCatalog,
    ):
        self._entries: dict[str, KnowledgeEntry] = {}
        self._sources = sources
        for entry in entries:
            if entry.entry_id in self._entries:
                raise ValueError(f"Duplicate knowledge entry ID: {entry.entry_id}")
            source = sources.get(entry.source_id)
            if source is None:
                raise ValueError(f"Unknown source for knowledge entry: {entry.source_id}")
            if source.version != entry.source_version:
                raise ValueError(f"Source version mismatch for knowledge entry: {entry.entry_id}")
            self._entries[entry.entry_id] = entry

    def get(self, entry_id: str) -> KnowledgeEntry | None:
        return self._entries.get(entry_id)

    def list(self) -> list[KnowledgeEntry]:
        return [self._entries[key] for key in sorted(self._entries)]

    def search(self, query: str, *, limit: int = 10) -> list[KnowledgeHit]:
        if limit < 1:
            raise ValueError("limit must be positive")
        chunks = re.findall(r"[\u4e00-\u9fff]+|[a-z0-9]+", query.lower())
        terms: list[str] = []
        for chunk in chunks:
            if re.fullmatch(r"[\u4e00-\u9fff]+", chunk):
                if len(chunk) == 1:
                    terms.append(chunk)
                else:
                    terms.extend(chunk[index:index + 2] for index in range(len(chunk) - 1))
            else:
                terms.append(chunk)
        if not terms:
            return []

        hits: list[KnowledgeHit] = []
        for entry in self._entries.values():
            source = self._sources.get(entry.source_id)
            if source is None:
                continue
            title = f"{entry.title} {source.title}".lower()
            corpus = " ".join((entry.summary, " ".join(entry.tags), entry.section)).lower()
            score = sum((2 if term in title else 1 if term in corpus else 0) for term in terms)
            if score:
                hits.append(KnowledgeHit(entry=entry, source=source, score=score))
        hits.sort(key=lambda hit: (-hit.score, hit.entry.entry_id))
        return hits[:limit]
