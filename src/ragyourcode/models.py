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
    def searchable_text(self) -> str:
        """Assembles everything about a unit that retrieval is allowed to match
        against: qualified name, kind and signature, the description, the
        names it calls and imports, and the full source. Because the
        description is part of this text, replacing a generated description
        with a better one immediately widens the set of queries that can
        reach this unit.
        """
        return "\n".join(
            (
                f"{self.qualified_name} {self.kind} {self.signature}",
                self.description,
                "calls: " + " ".join(self.calls),
                "imports: " + " ".join(self.imports),
                self.source,
            )
        )

    def to_dict(self, include_vector: bool = True) -> dict[str, Any]:
        """Serialises a unit to a plain dictionary for storage or for an agent
        reply, optionally leaving the vector out. Vectors are an internal
        ranking detail; sending them to an agent would consume context and
        explain nothing.
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
            "source": self.source,
            "description": self.description,
            "serial": self.serial,
            "parent": self.parent,
            "calls": self.calls,
            "imports": self.imports,
        }
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
        # Vectors are persisted for ranking but are an internal detail of the
        # index; returning them would needlessly consume an agent's context.
        """Serialises a result for an agent reply, rounding the score and
        stripping the vector.
        """
        unit = self.unit.to_dict(include_vector=False)
        return {
            "score": round(self.score, 6),
            "matched_terms": self.matched_terms,
            "evidence": self.evidence,
            "unit": unit,
        }
