"""Hybrid lexical/vector retrieval for agent context."""

from __future__ import annotations

import heapq
import math
from bisect import bisect_left
from collections import Counter, defaultdict
from dataclasses import dataclass

from .config import BY_PATH
from .embeddings import DEFAULT_DIMENSIONS, embed, tokenize
from .models import CodeUnit, SearchResult

# Named here rather than repeated as a literal so `search.vector_weight` in
# rag-your-code.toml and the default a direct caller gets cannot drift apart.
DEFAULT_VECTOR_WEIGHT: float = BY_PATH["search.vector_weight"].default

# How much a word counts for, by the field the author wrote it in. A term in
# the name is what the declaration is called; the same term inside the body is
# a mention. Every key of `CodeUnit.searchable_fields` must appear here, and a
# test asserts the two sets agree -- a field with no weight would otherwise
# vanish from ranking the moment it was added, silently.
FIELD_WEIGHTS: dict[str, float] = {
    "name": 8.0,
    "signature": 4.0,
    "description": 3.0,
    "relations": 2.0,
    "body": 1.0,
}

# BM25's saturation and length-normalisation constants, at their standard
# values. `k1` bounds what repeating a word can buy; `b` decides how hard a
# field is discounted for being longer than its average.
#
# Three variations were implemented and measured against all three rulers
# before settling here, and two were dropped for want of evidence: excluding
# curated text from the length on the argument that a written description is
# deliberate rather than incidental, and counting authored words instead of
# tokeniser output so a run of Chinese expanded into overlapping bigrams would
# not read as five times the text. Each moved one to four questions in both
# directions at once, which is this instrument's noise. Lowering `b` to 0.5 or
# 0.3 under per-field normalisation was measured and was worse than 0.75 on
# the foreign-repository ruler. See docs/TESTING.md.
BM25_K1 = 1.2
BM25_B = 0.75


@dataclass(slots=True)
class SearchIndex:
    """In-memory inverted index reused across queries.

    Building this once avoids re-tokenizing every code unit. Each posting
    carries a term's weight in that unit alongside its id -- already scaled by
    the field the term appeared in and by how long that field is -- because
    ranking needs to know how often a term occurs and where, not merely that
    it occurs somewhere. The weight lives in the posting rather than in a
    per-unit table: an earlier version cached a per-unit frozenset of every
    token, which cost the largest share of resident memory while holding
    nothing the postings did not already have.

    Lists are kept sorted by unit id so membership can be answered by binary
    search. The same structure can later be backed by SQLite/ANN storage.
    """

    units: dict[str, CodeUnit]
    postings: dict[str, tuple[tuple[str, float], ...]]


def build_search_index(units: list[CodeUnit]) -> SearchIndex:
    """Builds the inverted lookup table, recording for each term the units that
    contain it and how much it counts for in each.

    A term's weight is BM25F's: its count in a field, divided by how long that
    field is against the average for that same field, then scaled by what the
    field is worth. Normalising per field is the part that matters. Measured
    against one length for the whole unit, a body repeating a word forty times
    still beat the declaration actually named after it, because a long body's
    advantage in raw count almost exactly cancelled its penalty for being
    long. Comparing each field against its own average removes that cancelling.

    Two passes are needed because a field's average length is a property of
    the corpus and is not known until every unit has been seen. The second
    pass re-tokenizes rather than holding every unit's tokens in memory at
    once, which costs about half again in time and keeps the peak bounded.
    """
    field_totals: Counter[str] = Counter()
    for unit in units:
        for field_name, text in unit.searchable_fields.items():
            field_totals[field_name] += len(tokenize(text))
    count = len(units) or 1
    # A field every unit leaves empty would otherwise divide by zero. Its terms
    # cannot reach any unit anyway, so the value only has to be finite.
    averages = {name: (total / count) or 1.0 for name, total in field_totals.items()}

    postings: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for unit in units:
        weighted: Counter[str] = Counter()
        for field_name, text in unit.searchable_fields.items():
            terms = tokenize(text)
            if not terms:
                continue
            saturation = 1 - BM25_B + BM25_B * len(terms) / averages[field_name]
            weight = FIELD_WEIGHTS[field_name] / saturation
            for term, occurrences in Counter(terms).items():
                weighted[term] += weight * occurrences
        for term, mass in weighted.items():
            postings[term].append((unit.id, mass))
    return SearchIndex(
        {unit.id: unit for unit in units},
        {term: tuple(sorted(entries)) for term, entries in postings.items()},
    )


def _in_posting(posting: tuple[tuple[str, float], ...], unit_id: str) -> bool:
    """Membership test over a posting list, which build_search_index keeps
    sorted by unit id. A one-element tuple sorts before every pair sharing its
    id, so it locates the entry without needing the mass that follows it.
    """
    position = bisect_left(posting, (unit_id,))
    return position < len(posting) and posting[position][0] == unit_id


def _inverse_document_frequency(document_count: int, matching: int) -> float:
    """How much evidence one term carries, from how rare it is in this corpus.

    A word in nearly every unit says nothing about which unit is wanted, and
    a word in two says a great deal. Deriving that from the corpus rather than
    from a list of stopwords is what makes it work on a repository in any
    language: `the` and `calls` earn their low weight the same way a Chinese
    bigram does, by being everywhere, and no list has to be maintained.
    """
    return math.log(1 + (document_count - matching + 0.5) / (matching + 0.5))


def search(
    units: list[CodeUnit],
    query: str,
    limit: int = 8,
    search_index: SearchIndex | None = None,
    vector_weight: float = DEFAULT_VECTOR_WEIGHT,
) -> list[SearchResult]:
    """Ranks code units against a natural-language query by combining weighted
    word overlap with vector similarity.

    The lexical half is BM25 over weighted fields: rare words count for more
    than common ones, repeating a word saturates rather than accumulating
    without bound, and a unit is normalised by how much text it owns. An
    earlier version scored the plain fraction of query words present, which
    made `the` worth as much as `daemon` and handed every query to whichever
    unit was longest -- on a foreign repository the single largest declaration
    came back for four questions out of six.

    Every unit sharing any query word is scored, so nothing that matches is
    left out. Full vector scoring is reserved for units reached by a selective
    term, since computing a dot product for everything a stopword-class term
    touches is pure cost. With no overlap anywhere it falls back to similarity
    alone.
    """
    query_tokens = set(tokenize(query))
    if limit <= 0 or not query_tokens:
        return []
    query_vector = embed(query, len(units[0].vector) if units and units[0].vector else DEFAULT_DIMENSIONS)
    query_features = [(index, value) for index, value in enumerate(query_vector) if value]
    search_index = search_index or build_search_index(units)
    postings = [(token, search_index.postings.get(token, ())) for token in query_tokens]
    document_count = len(search_index.units) or 1

    # Accumulate term by term rather than unit by unit: a posting list is
    # exactly the units a term reaches, so this touches no unit the query
    # cannot possibly match. Length normalisation is already inside `mass`, so
    # all that remains is saturation -- the tenth occurrence of a word says
    # much less than the second, and neither should be able to run away with
    # the ranking.
    weights = {token: _inverse_document_frequency(document_count, len(posting)) for token, posting in postings if posting}
    lexical_scores: dict[str, float] = defaultdict(float)
    for token, posting in postings:
        if not posting:
            continue
        weight = weights[token]
        for unit_id, mass in posting:
            lexical_scores[unit_id] += weight * mass * (BM25_K1 + 1) / (mass + BM25_K1)

    # Divide by what this query could have scored at most, which is a constant
    # for the query and so changes no ranking. It exists to keep the lexical
    # half on the 0..1 scale `search.vector_weight` was documented and bounded
    # against: raw BM25 is unbounded, and against a score of 18 a weight of
    # 0.35 on a cosine would be arithmetic, not a tie-break.
    ceiling = sum(weights.values()) * (BM25_K1 + 1)

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
            vector_ids.update(unit_id for unit_id, _ in posting)
    if lexical_scores and not vector_ids and len(lexical_scores) <= selective_threshold:
        vector_ids = set(lexical_scores)

    # With no lexical overlap anywhere, fall back to pure cosine so a genuine
    # paraphrase still retrieves something.
    candidate_ids = lexical_scores.keys() if lexical_scores else search_index.units.keys()
    scored: list[tuple[float, str]] = []
    for unit_id in candidate_ids:
        unit = search_index.units[unit_id]
        lexical = (lexical_scores.get(unit_id, 0.0) / ceiling) if ceiling else 0.0
        vector_score = (
            sum(value * unit.vector[index] for index, value in query_features)
            if (unit_id in vector_ids or not lexical_scores) and len(unit.vector) == len(query_vector)
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


def _block(result: SearchResult) -> str:
    """One result as an agent reads it: identifier, score, why it matched,
    what it is, and the code itself.
    """
    unit = result.unit
    evidence = "\nEvidence: " + " | ".join(result.evidence) if result.evidence else ""
    return f"[{unit.id}] score={result.score:.3f}{evidence}\n{unit.description}\n```{unit.language}\n{unit.source}\n```"


def within_budget(results: list[SearchResult], max_chars: int) -> list[SearchResult]:
    """The leading results whose rendered size fits the caller's budget.

    The budget has to decide how many results there *are*, not merely how many
    get rendered into one of the two places they are sent. `search --json`
    used to serialise every result in full while capping only the context
    string beside them, so a default query answered with 65,025 characters
    against a stated budget of 12,000 -- and the agent, which reads the
    results, was the side that overran.

    The first result is always kept. A search that found something and
    returned nothing because the match was large is less useful than one
    oversized answer, and the caller is told how many were dropped.
    """
    kept: list[SearchResult] = []
    used = 0
    for result in results:
        size = len(_block(result))
        if kept and used + size > max_chars:
            break
        kept.append(result)
        used += size
    return kept


def context(results: list[SearchResult], max_chars: int = 12000) -> str:
    """Packs ranked results into one readable block for an agent prompt,
    stopping before the caller's character budget is exceeded.
    """
    return "\n\n".join(_block(result) for result in within_budget(results, max_chars))
