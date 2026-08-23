"""Hybrid lexical/vector retrieval for agent context."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from .embeddings import DEFAULT_DIMENSIONS, embed, tokenize
from .models import CodeUnit, SearchResult


@dataclass(slots=True)
class SearchIndex:
    """In-memory inverted index reused across queries.

    Building this once avoids re-tokenizing every code unit and allows vector
    work to focus on candidates containing informative query terms. The same
    structure can later be backed by SQLite/ANN storage.
    """

    units: dict[str, CodeUnit]
    terms_by_unit: dict[str, frozenset[str]]
    postings: dict[str, tuple[str, ...]]


def build_search_index(units: list[CodeUnit]) -> SearchIndex:
    postings: dict[str, set[str]] = defaultdict(set)
    terms_by_unit: dict[str, frozenset[str]] = {}
    by_id = {unit.id: unit for unit in units}
    for unit in units:
        terms = frozenset(tokenize(unit.searchable_text))
        terms_by_unit[unit.id] = terms
        for term in terms:
            postings[term].add(unit.id)
    return SearchIndex(by_id, terms_by_unit, {term: tuple(sorted(ids)) for term, ids in postings.items()})


def search(
    units: list[CodeUnit],
    query: str,
    limit: int = 8,
    search_index: SearchIndex | None = None,
) -> list[SearchResult]:
    if limit <= 0 or not tokenize(query):
        return []
    query_tokens = set(tokenize(query))
    query_vector = embed(query, len(units[0].vector) if units and units[0].vector else DEFAULT_DIMENSIONS)
    query_features = [(index, value) for index, value in enumerate(query_vector) if value]
    search_index = search_index or build_search_index(units)
    posting_lists = [search_index.postings.get(token, ()) for token in query_tokens]
    lexical_ids = set().union(*posting_lists)
    # Common terms (for example ``function``) can occur in every unit and make
    # exact cosine scanning dominate latency. Compute vectors only for units
    # reached through at least one informative term. If nothing matches at all,
    # retain full vector fallback for genuine paraphrases.
    selective_threshold = max(64, min(2048, len(units) // 10))
    vector_ids = set().union(*(posting for posting in posting_lists if 0 < len(posting) <= selective_threshold))
    if lexical_ids and not vector_ids and len(lexical_ids) <= selective_threshold:
        vector_ids = set(lexical_ids)
    candidate_ids = vector_ids or lexical_ids or set(search_index.units)
    ranked: list[SearchResult] = []
    for unit_id in candidate_ids:
        unit = search_index.units[unit_id]
        terms = search_index.terms_by_unit.get(unit.id, frozenset())
        matched = sorted(query_tokens & terms)
        lexical = len(matched) / max(1, len(query_tokens))
        vector_score = (
            sum(value * unit.vector[index] for index, value in query_features)
            if (unit.id in vector_ids or not lexical_ids) and len(unit.vector) == len(query_vector)
            else 0.0
        )
        # Exact symbols and domain terms are high-confidence evidence. Keep
        # lexical overlap dominant so a noisy feature-hash vector cannot push
        # an exact match below an unrelated semantic neighbor; use the vector
        # score to rank paraphrases and break lexical ties.
        score = lexical + 0.15 * max(0.0, vector_score)
        if matched:
            ranked.append(SearchResult(unit, score, matched))
        elif score > 0:
            ranked.append(SearchResult(unit, score, []))
    ranked.sort(key=lambda result: (-result.score, result.unit.id))
    return ranked[:limit]


def context(results: list[SearchResult], max_chars: int = 12000) -> str:
    blocks: list[str] = []
    used = 0
    for result in results:
        unit = result.unit
        evidence = "\nEvidence: " + " | ".join(result.evidence) if result.evidence else ""
        block = f"[{unit.id}] score={result.score:.3f}{evidence}\n{unit.description}\n```{unit.language}\n{unit.source}\n```"
        if used + len(block) > max_chars:
            break
        blocks.append(block)
        used += len(block)
    return "\n\n".join(blocks)
