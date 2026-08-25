"""Hybrid lexical/vector retrieval for agent context."""

from __future__ import annotations

import heapq
from bisect import bisect_left
from collections import Counter, defaultdict
from dataclasses import dataclass

from .config import BY_PATH
from .embeddings import DEFAULT_DIMENSIONS, embed, tokenize
from .models import CodeUnit, SearchResult

# Named here rather than repeated as a literal so `search.vector_weight` in
# rag-your-code.toml and the default a direct caller gets cannot drift apart.
DEFAULT_VECTOR_WEIGHT: float = BY_PATH["search.vector_weight"].default


@dataclass(slots=True)
class SearchIndex:
    """In-memory inverted index reused across queries.

    Building this once avoids re-tokenizing every code unit. Matched terms are
    read straight out of ``postings``; an earlier version also cached a
    per-unit frozenset of every token, which cost the largest share of the
    index's resident memory while holding nothing ``postings`` did not already
    have. The same structure can later be backed by SQLite/ANN storage.
    """

    units: dict[str, CodeUnit]
    postings: dict[str, tuple[str, ...]]


def build_search_index(units: list[CodeUnit]) -> SearchIndex:
    """Builds the inverted lookup table by tokenising every unit once and
    recording, for each term, which units contain it. The lists are kept
    sorted so membership can later be answered by binary search rather than
    by carrying a word set through the scoring loop.
    """
    postings: dict[str, set[str]] = defaultdict(set)
    for unit in units:
        for term in set(tokenize(unit.searchable_text)):
            postings[term].add(unit.id)
    return SearchIndex({unit.id: unit for unit in units}, {term: tuple(sorted(ids)) for term, ids in postings.items()})


def _in_posting(posting: tuple[str, ...], unit_id: str) -> bool:
    """Membership test over a posting list, which build_search_index keeps sorted."""
    position = bisect_left(posting, unit_id)
    return position < len(posting) and posting[position] == unit_id


def search(
    units: list[CodeUnit],
    query: str,
    limit: int = 8,
    search_index: SearchIndex | None = None,
    vector_weight: float = DEFAULT_VECTOR_WEIGHT,
) -> list[SearchResult]:
    """Ranks code units against a natural-language query by combining word
    overlap with vector similarity. Every unit sharing any query word is
    scored, so nothing that matches is left out: an earlier design let the
    vector shortlist decide who was scored at all, and units matching more
    query words went unranked, returning one result where eight were asked
    for. Full vector scoring is reserved for units reached by a selective
    term, since computing a dot product for everything a stopword-class term
    touches is pure cost. Word overlap stays dominant so an exact symbol
    match cannot be pushed below a noisy neighbour, and with no overlap
    anywhere it falls back to similarity alone.
    """
    query_tokens = set(tokenize(query))
    if limit <= 0 or not query_tokens:
        return []
    query_vector = embed(query, len(units[0].vector) if units and units[0].vector else DEFAULT_DIMENSIONS)
    query_features = [(index, value) for index, value in enumerate(query_vector) if value]
    search_index = search_index or build_search_index(units)
    postings = [(token, search_index.postings.get(token, ())) for token in query_tokens]

    # Matched terms come straight from the posting lists. Walking postings costs
    # O(sum of posting lengths) of dict work, where scoring each candidate by
    # intersecting a cached per-unit token set cost a frozenset operation per
    # candidate -- and every lexically matching unit now gets a score.
    matched_counts: Counter[str] = Counter()
    for _, posting in postings:
        matched_counts.update(posting)

    # A term present in a tenth of the corpus (``function``, ``return``) is not
    # evidence of relevance, and its posting list is effectively the whole index;
    # computing a 384-dimension dot product for everything it reaches is what
    # this threshold exists to avoid. It selects which candidates additionally
    # receive a VECTOR score. It must not decide which candidates are scored at
    # all -- doing that silently dropped units matching MORE query terms and
    # under-filled ``limit`` (116 units, `--limit 8`, one result returned).
    selective_threshold = max(64, min(2048, len(units) // 10))
    vector_ids: set[str] = set()
    for _, posting in postings:
        if 0 < len(posting) <= selective_threshold:
            vector_ids.update(posting)
    if matched_counts and not vector_ids and len(matched_counts) <= selective_threshold:
        vector_ids = set(matched_counts)

    # With no lexical overlap anywhere, fall back to pure cosine so a genuine
    # paraphrase still retrieves something.
    candidate_ids = matched_counts.keys() if matched_counts else search_index.units.keys()
    scored: list[tuple[float, str]] = []
    for unit_id in candidate_ids:
        unit = search_index.units[unit_id]
        lexical = matched_counts.get(unit_id, 0) / len(query_tokens)
        vector_score = (
            sum(value * unit.vector[index] for index, value in query_features)
            if (unit_id in vector_ids or not matched_counts) and len(unit.vector) == len(query_vector)
            else 0.0
        )
        # Exact symbols and domain terms are high-confidence evidence. Keep
        # lexical overlap dominant so a noisy feature-hash vector cannot push an
        # exact match below an unrelated semantic neighbor; use the vector score
        # to rank paraphrases and break lexical ties.
        score = lexical + vector_weight * max(0.0, vector_score)
        if lexical or score > 0:
            scored.append((score, unit_id))
    # Materialise only the winners. Building a SearchResult for every lexical
    # match and then sorting all of them cost more than the scoring itself once
    # recall became complete: at 10k units that alone was most of a 10x query
    # regression. nsmallest keeps the exact previous ordering -- highest score
    # first, ties broken by ascending unit id -- at O(n log limit).
    winners = heapq.nsmallest(limit, scored, key=lambda item: (-item[0], item[1]))
    # Which terms matched is only needed for the handful actually returned, and
    # postings are stored sorted, so a binary search beats carrying a per-unit
    # term list through the scoring loop for every candidate in the corpus.
    return [
        SearchResult(search_index.units[unit_id], score, sorted(token for token, posting in postings if _in_posting(posting, unit_id)))
        for score, unit_id in winners
    ]


def context(results: list[SearchResult], max_chars: int = 12000) -> str:
    """Packs ranked results into one readable block for an agent prompt, each
    carrying identifier, score, matching evidence, description and source,
    and stops before exceeding the caller character budget.
    """
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
