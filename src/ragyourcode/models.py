"""Data contracts used by indexing, storage, and agent integrations."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class CodeUnit:
    """One searchable code unit and its generated, explainable description."""

    id: str
    path: str
    language: str
    kind: str
    name: str
    qualified_name: str
    signature: str
    start_line: int
    end_line: int
    source: str
    description: str
    serial: int
    parent: str | None = None
    calls: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    vector: Sequence[float] = field(default_factory=list)

    @property
    def searchable_fields(self) -> dict[str, str]:
        """Everything retrieval may match, kept apart by where the author
        wrote it. Where a word appears is itself evidence of how much it
        means: a term in a declaration's name is what the author decided to
        call the thing, while the same term two hundred lines into a body is
        a passing mention. Ranking weights those differently, so they cannot
        arrive as one undifferentiated blob -- flattened, a long function
        outranks the function that is actually named after the query, purely
        by owning more words.

        Because the description is one of these fields, replacing a generated
        description with a better one immediately widens the set of queries
        that can reach this unit.
        """
        return {
            "name": f"{self.qualified_name} {self.kind}",
            "signature": self.signature,
            "description": self.description,
            "relations": "calls: " + " ".join(self.calls) + "\nimports: " + " ".join(self.imports),
            "body": self.source,
        }

    @property
    def searchable_text(self) -> str:
        """Every searchable field as one block, for callers that want the
        words without caring where they came from -- the unit's own embedding
        is built from this. Derived from ``searchable_fields`` rather than
        rebuilt beside it, so a field added for ranking cannot go missing
        from the text that gets embedded.
        """
        return "\n".join(self.searchable_fields.values())

    def to_dict(self, include_vector: bool = True, include_source: bool = True) -> dict[str, Any]:
        """Serialises a unit to a plain dictionary for storage or for an agent
        reply, optionally leaving out the vector or the source.

        Vectors are an internal ranking detail; sending them to an agent would
        consume context and explain nothing. The source is left out of a
        *result* for a different reason: a reply carries it once already, in
        the budgeted context block, and repeating it per result is what let a
        search answer run to five times its stated budget.
        """
        data = {
            "id": self.id,
            "path": self.path,
            "language": self.language,
            "kind": self.kind,
            "name": self.name,
            "qualified_name": self.qualified_name,
            "signature": self.signature,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "description": self.description,
            "serial": self.serial,
            "parent": self.parent,
            "calls": self.calls,
            "imports": self.imports,
        }
        if include_source:
            data["source"] = self.source
        if include_vector:
            data["vector"] = list(self.vector)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CodeUnit":
        """Rebuilds a unit from its stored dictionary form when an index is
        loaded back from disk.
        """
        return cls(**data)


@dataclass(slots=True)
class SearchResult:
    """One retrieved unit together with why it was retrieved: its relevance
    score, the query words that actually matched, and for graph expansion
    the chain of edges that led to it. The evidence is the point: a result
    you cannot explain is a result you should not act on.
    """
    unit: CodeUnit
    score: float
    matched_terms: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialises a result for an agent reply: where the unit is, what it
        is called, why it matched, and how well -- but not its source.

        A result is navigation evidence. The code itself arrives once, in the
        reply's budgeted context block, and an agent that wants more opens the
        cited file. Carrying it here as well is what let one `search --json`
        answer reach 65,025 characters against a stated budget of 12,000, and
        one `research` answer reach 111,843 by serialising the same eight
        units three times over. Bounding the emitters one at a time would have
        left the next one free to overrun; a result that has no source cannot.
        """
        return {
            "score": round(self.score, 6),
            "matched_terms": self.matched_terms,
            "evidence": self.evidence,
            # Vectors are persisted for ranking but are an internal detail of
            # the index; returning them would needlessly consume context.
            "unit": self.unit.to_dict(include_vector=False, include_source=False),
        }
