"""Bounded, observable agentic retrieval (ARAG) orchestration."""

from __future__ import annotations

from .graph import CodeGraph, graph_search
from .models import CodeUnit, SearchResult
from .search import DEFAULT_VECTOR_WEIGHT, SearchIndex, search


def _result_ids(results: list[SearchResult]) -> set[str]:
    return {result.unit.id for result in results}


def _serialize(results: list[SearchResult]) -> list[dict]:
    return [result.to_dict() for result in results]


def research(
    units: list[CodeUnit],
    query: str,
    limit: int = 8,
    hops: int = 1,
    max_steps: int = 2,
    confidence_threshold: float = 0.8,
    graph: CodeGraph | None = None,
    search_index: SearchIndex | None = None,
    vector_weight: float = DEFAULT_VECTOR_WEIGHT,
) -> dict:
    """Run at most two deterministic retrieval steps and explain the stop.

    This is deliberately bounded. A future LLM planner can replace the query
    proposal, but the budget, evidence format, and no-progress stop remain
    stable safety contracts.
    """
    max_steps = min(2, max(1, max_steps))
    steps: list[dict] = []
    initial = search(units, query, max(limit, 1), search_index=search_index, vector_weight=vector_weight)
    steps.append({"action": "search", "query": query, "results": _serialize(initial)})
    best_score = initial[0].score if initial else 0.0
    if not initial:
        return {"query": query, "results": [], "steps": steps, "stop_reason": "no_results"}
    if max_steps == 1 or (best_score >= confidence_threshold and initial[0].matched_terms):
        return {"query": query, "results": _serialize(initial[:limit]), "steps": steps, "stop_reason": "high_confidence"}

    expanded = graph_search(units, query, limit=max(limit * 2, 8), hops=hops, graph=graph, search_index=search_index, vector_weight=vector_weight)
    steps.append({"action": "graph_expand", "hops": hops, "results": _serialize(expanded[:limit])})
    merged = {result.unit.id: result for result in initial}
    for result in expanded:
        current = merged.get(result.unit.id)
        if current is None or result.score > current.score:
            merged[result.unit.id] = result
    final = sorted(merged.values(), key=lambda result: (-result.score, result.unit.id))[:limit]
    new_ids = _result_ids(final) - _result_ids(initial)
    reason = "new_graph_evidence" if new_ids else "no_new_evidence"
    return {"query": query, "results": _serialize(final), "steps": steps, "stop_reason": reason}
