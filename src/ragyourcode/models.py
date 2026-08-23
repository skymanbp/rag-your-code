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
        return cls(**data)


@dataclass(slots=True)
class SearchResult:
    unit: CodeUnit
    score: float
    matched_terms: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        # Vectors are persisted for ranking but are an internal detail of the
        # index; returning them would needlessly consume an agent's context.
        unit = self.unit.to_dict(include_vector=False)
        return {
            "score": round(self.score, 6),
            "matched_terms": self.matched_terms,
            "evidence": self.evidence,
            "unit": unit,
        }
