"""Bounded, observable agentic retrieval (ARAG) orchestration."""

from __future__ import annotations

from .graph import CodeGraph, graph_search
from .models import CodeUnit, SearchResult
from .search import (
    DEFAULT_MIN_CONCENTRATION,
    DEFAULT_MIN_COVERAGE,
    DEFAULT_VECTOR_RECALL,
    DEFAULT_VECTOR_WEIGHT,
    SearchIndex,
    assess,
    build_search_index,
    context,
    diagnose,
    search,
    within_budget,
)


def _result_ids(results: list[SearchResult]) -> set[str]:
    """Collects the unit identifiers out of a list of search results, so two
    result sets can be compared for overlap or novelty. Used to decide
    whether a second retrieval round actually surfaced anything new.
    """
    return {result.unit.id for result in results}


# How far ahead of the runner-up the top result must be before a second
# retrieval step is skipped, as a fraction of the top score.
#
# This replaced an absolute `confidence_threshold` of 0.8, which was a number
# tied to a scoring scale. When ranking became BM25F the scale moved and the
# threshold quietly died: measured across 105 ruler questions, only 3% of
# queries reached 0.8 at all, so the early stop had stopped existing and every
# research call ran the graph expansion. A margin is a ratio between two scores
# from the same query, so it cannot drift when the scoring changes again.
#
# Measured over those 105 questions: top-1 is correct 42% of the time overall,
# and 68-73% of the time among the queries this fires on. Anywhere in 0.2-0.5
# behaves the same at this sample size; 0.30 is the middle of that band, not a
# measured optimum.
DEFAULT_DOMINANCE: float = 0.30


def _serialize(results: list[SearchResult]) -> list[dict]:
    """Converts search results into plain JSON-ready dictionaries for the agent
    protocol reply.
    """
    return [result.to_dict() for result in results]


def _trace(results: list[SearchResult]) -> list[dict]:
    """One step of the search, as a trace rather than as a payload.

    A step exists so the caller can see how the answer was reached: which
    units each round reached and how strongly. That needs an identifier, a
    score and the matching words -- not a second and third copy of every
    unit's description, callees and imports. Reporting two steps in full is
    what made a research reply three times the size of the answer inside it.
    """
    return [
        {"id": result.unit.id, "score": round(result.score, 6), "matched_terms": result.matched_terms}
        for result in results
    ]


def dominance(results: list[SearchResult]) -> float:
    """How far the top result is ahead of the runner-up, relative to the top.

    One result alone is unopposed and scores 1.0. Nothing scores 0.0. The
    quantity is scale-free by construction, which is the whole point: it
    compares two numbers produced by the same query under the same scoring
    rule, so no future change to that rule can silently recalibrate it.
    """
    if not results:
        return 0.0
    top = results[0].score
    if len(results) == 1:
        return 1.0
    return (top - results[1].score) / top if top else 0.0


def research(
    units: list[CodeUnit],
    query: str,
    limit: int = 8,
    hops: int = 1,
    max_steps: int = 2,
    dominance_threshold: float = DEFAULT_DOMINANCE,
    graph: CodeGraph | None = None,
    search_index: SearchIndex | None = None,
    vector_weight: float = DEFAULT_VECTOR_WEIGHT,
    vector_recall: int = DEFAULT_VECTOR_RECALL,
    min_coverage: float = DEFAULT_MIN_COVERAGE,
    min_concentration: float = DEFAULT_MIN_CONCENTRATION,
    max_chars: int = 12000,
) -> dict:
    """Run at most two deterministic retrieval steps and explain the stop.

    This is deliberately bounded. A future LLM planner can replace the query
    proposal, but the budget, evidence format, and no-progress stop remain
    stable safety contracts.

    The reply carries the code once, in a context block trimmed to
    ``max_chars``. Results are navigation only. Reporting two retrieval steps
    used to mean serialising the same eight units three times with their
    source attached, which is how one research answer reached 111,843
    characters against a stated budget of 12,000.
    """
    max_steps = min(2, max(1, max_steps))
    steps: list[dict] = []
    search_index = search_index or build_search_index(units)
    initial = search(units, query, max(limit, 1), search_index=search_index, vector_weight=vector_weight, vector_recall=vector_recall, min_coverage=min_coverage, min_concentration=min_concentration)
    steps.append({"action": "search", "query": query, "results": _trace(initial)})
    if not initial:
        # Two observable steps are worth nothing if the first one stopping is
        # reported as a bare emptiness. A second step cannot recover a query
        # whose words are not in this index, or whose words are never together
        # in one of them, so the reply says so instead of spending the budget to
        # arrive at the same silence.
        # `stop_reason` keeps its published set of values -- the specific reason
        # goes in the new `diagnosis` field beside it. Widening an enumeration
        # callers already branch on is a breaking change wearing the clothes of
        # an improvement; adding a field next to it is not.
        report = diagnose(assess(search_index, query, min_coverage, min_concentration), min_coverage, min_concentration)
        return {"query": query, "results": [], "steps": steps, "stop_reason": "no_results", "context": "", "diagnosis": report}
    unopposed = dominance(initial) >= dominance_threshold and bool(initial[0].matched_terms)
    if max_steps == 1 or unopposed:
        kept = initial[:limit]
        return {"query": query, "results": _serialize(kept), "steps": steps, "stop_reason": "high_confidence", "context": context(within_budget(kept, max_chars), max_chars)}

    expanded = graph_search(units, query, limit=max(limit * 2, 8), hops=hops, graph=graph, search_index=search_index, vector_weight=vector_weight, vector_recall=vector_recall, min_coverage=min_coverage, min_concentration=min_concentration)
    steps.append({"action": "graph_expand", "hops": hops, "results": _trace(expanded[:limit])})
    merged = {result.unit.id: result for result in initial}
    for result in expanded:
        current = merged.get(result.unit.id)
        if current is None or result.score > current.score:
            merged[result.unit.id] = result
    final = sorted(merged.values(), key=lambda result: (-result.score, result.unit.id))[:limit]
    new_ids = _result_ids(final) - _result_ids(initial)
    reason = "new_graph_evidence" if new_ids else "no_new_evidence"
    return {"query": query, "results": _serialize(final), "steps": steps, "stop_reason": reason, "context": context(within_budget(final, max_chars), max_chars)}
