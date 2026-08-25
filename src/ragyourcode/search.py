"""Hybrid lexical/vector retrieval for agent context."""

from __future__ import annotations

import heapq
import math
from bisect import bisect_left
from collections import Counter, defaultdict
from dataclasses import dataclass

from .config import BY_PATH
from .embeddings import DEFAULT_DIMENSIONS, LocalEmbedder, tokenize
from .models import CodeUnit, SearchResult

# Named here rather than repeated as a literal so `search.vector_weight` in
# rag-your-code.toml and the default a direct caller gets cannot drift apart.
DEFAULT_VECTOR_WEIGHT: float = BY_PATH["search.vector_weight"].default
DEFAULT_VECTOR_RECALL: int = BY_PATH["search.vector_recall"].default
DEFAULT_MIN_COVERAGE: float = BY_PATH["search.min_coverage"].default
DEFAULT_MIN_CONCENTRATION: float = BY_PATH["search.min_concentration"].default

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

# Above this share of the corpus a word stops telling the units apart, so it is
# left out of the evidence question entirely -- out of the numerator and out of
# the denominator alike. Which is the whole trick: `where are CUDA kernels
# dispatched to the device` matches `where`, `are`, `to` and `the`, four of its
# eight words, and half a query looks like evidence until you notice that the
# matching half is words this repository contains everywhere. Counting only
# words that discriminate silenced 20 of 32 unanswerable English questions that
# no plain coverage threshold could reach, at exactly the same cost in real
# answers. Derived from the corpus, so it needs no stopword list and works the
# same in a language nobody anticipated. It is a property of the scoring model
# rather than a preference, which is why it sits here beside `k1` and `b`
# instead of in the settings.
COMMON_TERM = 0.05

# A share alone is degenerate on a small corpus, in the direction that matters
# most: across ten units a word in one of them is the most discriminating word
# there is, and 1/10 is already twice the share above. Read as a fraction only,
# every term in a ten-unit index is "everywhere" and every query is refused --
# the same defect as a constant tied to a scale, arrived at from the other
# side. So a word is common only once it is also in more units than this, which
# leaves the fraction in charge above roughly 160 units and never lets it fire
# on an index too small for the word "everywhere" to mean anything.
COMMON_TERM_FLOOR = 8

# A small repository cannot hold the vocabulary of a sentence, so coverage
# reads low there for a reason that has nothing to do with whether it has the
# answer. Measured on one repository subsampled to eight sizes, average
# coverage of questions it can answer falls 0.789 -> 0.731 -> 0.559 -> 0.410
# from 1153 units to 400, 100 and 10, while coverage of questions nothing can
# answer stays flat at 0.13-0.18 whatever the size. So the separation survives
# and only its position moves, and the bar is eased in proportion below this
# many units rather than switched off at a cliff: a small index keeps partial
# protection and never refuses a question it could have answered.
COVERAGE_FULL_STRENGTH = 200


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

    The embedder lives here because a query vector and a unit vector have to
    come from the same scheme to be comparable at all. Keeping it beside the
    postings is what makes that impossible to get wrong from a call site --
    comparing a query embedded one way against units embedded another produces
    numbers that look fine and mean nothing.
    """

    units: dict[str, CodeUnit]
    postings: dict[str, tuple[tuple[str, float], ...]]
    embedder: object = None


@dataclass(slots=True, frozen=True)
class Evidence:
    """Whether a query reached this index at all, kept apart from how its
    results rank.

    Ranking answers "which of these is best". It cannot answer "is any of this
    an answer", and reading the first as the second is what let a repository
    reply to all 32 questions in `benchmarks/absent_queries.json` -- every one
    about a subject neither repository implements. `where are CUDA kernels
    dispatched to the device` came back with a test about word counting, on the
    evidence of `are`, `the`, `to` and `where`. That is not a Chinese problem
    or a ranking problem; it is a missing question.

    Two numbers answer it, and they are independent:

    ``coverage`` is the share of the query's *discriminating* words that appear
    in the index -- see `COMMON_TERM` for why the others are dropped from both
    sides of that fraction.

    ``concentration`` is the share of the query's discriminating *weight* that
    occurs inside a single unit. Coverage alone asks whether each word occurs
    somewhere, and a question about a subject nothing here implements can pass
    that entirely out of unrelated declarations -- four of its six words found
    in four places that have nothing to do with one another or with what was
    asked. Two thirds coverage, and no two of those words ever together.

    The worked example that belongs here is deliberately absent, because
    `benchmarks/absent_queries.json` grades this repository on questions whose
    subjects it does not contain, and spelling one out here would put that
    subject's vocabulary into the index and make the question answerable. That
    has now happened twice; see CONTRIBUTING.md.

    Both are ratios inside the query, deliberately: a threshold on a *score* is
    tied to whatever scale the ranking currently produces, and this project has
    already had one of those stop meaning anything the moment BM25F changed the
    scale.
    """

    terms: int
    considered: tuple[str, ...]
    matched: tuple[str, ...]
    ubiquitous: tuple[str, ...]
    coverage: float
    concentration: float
    # The bars actually applied, after the small-index easing. Carried rather
    # than recomputed by whoever asks, because the setting and the bar are not
    # the same number below `COVERAGE_FULL_STRENGTH` units, and a diagnosis
    # quoting the setting there would name a bar that was never used.
    required_coverage: float
    required_concentration: float
    sufficient: bool

    @property
    def reason(self) -> str:
        """Why an answer was withheld, as a stable token an agent can branch on."""
        if self.sufficient:
            return ""
        if not self.matched:
            return "only_ubiquitous_terms_matched" if self.ubiquitous else "no_query_term_in_index"
        if self.coverage < self.required_coverage:
            return "too_little_of_the_query_matched"
        return "matched_terms_are_scattered"


def assess(
    search_index: SearchIndex,
    query: str,
    min_coverage: float = DEFAULT_MIN_COVERAGE,
    min_concentration: float = DEFAULT_MIN_CONCENTRATION,
) -> Evidence:
    """How much of `query` occurs in this index, and how much of it in one place.

    Both questions are answered here rather than at the call sites, so the
    caller deciding whether to answer and the caller explaining why it did not
    ask the same thing -- two copies of a rule is how the two ends of a contract
    start disagreeing.

    Cost is bounded by what a discriminating term *is*. Concentration reads the
    posting list of every distinctive word, and a word is only distinctive while
    it stays under `COMMON_TERM` of the corpus, so the work is at most a few
    percent of the index per query word and never the full scan that scoring
    would have been. The words with the long posting lists are exactly the ones
    excluded.

    Nothing is exempt, including a semantic embedder, and that is a correction.
    1.0.0 exempted one by the argument that a paraphrase sharing no word with
    its answer is exactly what a model is for, so lexical evidence is then
    evidence of nothing. The argument is sound; the conclusion was wrong, and it
    was reasoned rather than measured because there was no model here to measure
    with. There is now: exempt and asked no other question, a trained model
    answered all sixty questions about subjects neither graded repository
    implements -- the entire defect 1.0.0 existed to fix, reintroduced by the
    one path that skipped the fix.

    Two vector-space replacements were measured before this was settled. A floor
    on the similarity is a threshold on a score, the failure this project has
    already had once, and the distributions overlap far too much to place one:
    answerable questions sit at a median nearest-unit cosine of 0.469 and
    unanswerable ones at 0.418. A scale-free version -- how many standard
    deviations the nearest unit stands above the corpus's own mean for that
    query -- looked more promising and measured worse, taking a cold ruler from
    0.329 hit@1 to 0.186 for two thirds of the silence. Applying these two bars
    unchanged costs the foreign ruler nothing at all and holds silence at 0.967.
    """
    terms = set(tokenize(query))
    total = len(search_index.units) or 1
    everywhere = max(COMMON_TERM * total, COMMON_TERM_FLOOR)
    ubiquitous, considered = [], []
    for term in sorted(terms):
        (ubiquitous if len(search_index.postings.get(term, ())) > everywhere else considered).append(term)
    matched = tuple(term for term in considered if search_index.postings.get(term))
    # Everything the query asked about is a word this repository uses
    # everywhere: there is no discriminating evidence to have, so the ratio is
    # zero rather than the vacuous 1.0 that dividing nothing by nothing invites.
    coverage = (len(matched) / len(considered)) if considered else 0.0

    # Rarity-weighted rather than counted. A unit holding two ordinary words is
    # not better evidence than one holding the single rare word the question is
    # about, and counting terms says it is. This is the same worth `search`
    # ranks by, asked as a different question: not "which unit scores highest"
    # but "did any one unit see enough of what was asked".
    worth = {term: _inverse_document_frequency(total, len(search_index.postings[term])) for term in matched}
    budget = sum(worth.values())
    per_unit: dict[str, float] = defaultdict(float)
    for term in matched:
        for unit_id, _ in search_index.postings[term]:
            per_unit[unit_id] += worth[term]
    # Divided by the whole distinctive budget, not by what happened to match:
    # normalising by the matched part alone scores a question that reached two
    # words and found both in one unit as perfect evidence, which is precisely
    # the shape an unanswerable question has.
    #
    # A word that is not here is charged what the rarest word that *is* here
    # would be worth, never the unbounded value of occurring in zero units. The
    # difference does not matter on a large corpus and decides everything on a
    # small one: across nine units the zero-occurrence figure is eighteen times
    # a real term's, against 1.2 times across five hundred, so the measure
    # changes shape with the size of the repository -- the same degeneracy
    # `COMMON_TERM_FLOOR` exists to stop, arrived at from a third direction.
    absent_worth = _inverse_document_frequency(total, 1)
    unmatched_budget = absent_worth * sum(1 for term in considered if term not in worth)
    concentration = (max(per_unit.values(), default=0.0) / (budget + unmatched_budget)) if considered else 0.0

    scale = min(1.0, total / COVERAGE_FULL_STRENGTH)
    needed_coverage, needed_concentration = min_coverage * scale, min_concentration * scale
    return Evidence(
        len(terms),
        tuple(considered),
        matched,
        tuple(term for term in ubiquitous if search_index.postings.get(term)),
        coverage,
        concentration,
        needed_coverage,
        needed_concentration,
        bool(terms) and coverage >= needed_coverage and concentration >= needed_concentration,
    )


_HINTS = {
    "no_query_term_in_index": (
        "No word of this question occurs anywhere in the index. Ask in the vocabulary the code "
        "itself uses, or write descriptions so the concepts have words to be found by."
    ),
    "only_ubiquitous_terms_matched": (
        "The only words that matched are ones this repository uses throughout, so they single out "
        "nothing. Add a term specific to what you are looking for."
    ),
    "too_little_of_the_query_matched": (
        "Too little of this question occurs in the index for a result to be evidence rather than a "
        "guess. Try the words the code uses, or lower search.min_coverage to see the guesses."
    ),
    "matched_terms_are_scattered": (
        "The words that matched occur in this repository, but never together in one place, so no "
        "single declaration is about what you asked. This is usually a question about something "
        "the repository does not implement, described in words it happens to use elsewhere."
    ),
}


def diagnose(
    evidence: Evidence,
    min_coverage: float = DEFAULT_MIN_COVERAGE,
    min_concentration: float = DEFAULT_MIN_CONCENTRATION,
) -> dict[str, object]:
    """Why nothing was returned, in a form an agent can branch on.

    An empty answer is only useful if it says which kind of empty it is. All
    four of these are recoverable and each by a different move -- rephrase in
    the code's vocabulary, add a distinctive word, write the descriptions that
    would give the concept words at all, or accept that the subject is not in
    this repository -- and none of them is what an agent does when handed a
    plausible wrong unit instead.
    """
    return {
        "reason": evidence.reason,
        "query_terms": evidence.terms,
        "distinctive_terms": list(evidence.considered),
        "matched_terms": list(evidence.matched),
        "ubiquitous_terms": list(evidence.ubiquitous),
        "coverage": round(evidence.coverage, 4),
        "min_coverage": min_coverage,
        "concentration": round(evidence.concentration, 4),
        "min_concentration": min_concentration,
        # What the two settings became for an index this size. Equal to the
        # settings above on any repository past `COVERAGE_FULL_STRENGTH` units,
        # and lower on a small one -- where quoting the setting alone would tell
        # a caller its query missed a bar that was never applied to it.
        "applied_min_coverage": round(evidence.required_coverage, 4),
        "applied_min_concentration": round(evidence.required_concentration, 4),
        "hint": _HINTS.get(evidence.reason, ""),
    }


def build_search_index(units: list[CodeUnit], embed_with=None) -> SearchIndex:
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
        embed_with if embed_with is not None else LocalEmbedder(len(units[0].vector) if units and units[0].vector else DEFAULT_DIMENSIONS),
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
    vector_recall: int = DEFAULT_VECTOR_RECALL,
    min_coverage: float = DEFAULT_MIN_COVERAGE,
    min_concentration: float = DEFAULT_MIN_CONCENTRATION,
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

    When -- and only when -- the embedder carries real semantics, similarity
    may also *add* candidates the words never reached. That is the one thing a
    vector can do that ranking cannot: six of thirty-five questions on the
    foreign ruler have no acceptable answer sharing a single token with the
    query, and no weighting makes those reachable. Under the feature hash the
    same widening is measurably harmful, because a cosine over hashed token
    overlap ranks unrelated units confidently, so it stays switched off there.
    Lexical evidence remains dominant either way: a unit found by similarity
    alone scores at most `vector_weight`, so it surfaces where the words found
    little and yields where they found a lot.

    A query too little of which occurs in the index, or whose words never occur
    together, returns nothing at all. Ranking cannot express "no answer here":
    something is always least-bad, and it is returned with a score and a rank
    that read exactly like an answer. `assess` decides this, `search.min_coverage`
    and `search.min_concentration` set the two bars, and callers report the
    reason -- an empty reply that explains itself is actionable, where a
    plausible wrong one costs an agent the edit it makes on top of it.
    """
    query_tokens = set(tokenize(query))
    if limit <= 0 or not query_tokens:
        return []
    search_index = search_index or build_search_index(units)
    # Before any embedding or scoring: an unanswerable query is turned away
    # having touched only the posting lists of its own distinctive words, never
    # the corpus. Which is strictly less work than answering it would have been.
    if not assess(search_index, query, min_coverage, min_concentration).sufficient:
        return []
    # The query goes through the index's own embedder, never the module-level
    # one: a query vector from a different scheme than the units it is
    # compared against yields numbers that look like scores and are not.
    query_vector = search_index.embedder.one(query)
    query_features = [(index, value) for index, value in enumerate(query_vector) if value]
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
    # paraphrase still retrieves something. Reaching here now means the coverage
    # gate let the query through with nothing matched, which happens for a
    # semantic embedder -- where a paraphrase really is the case to serve -- or
    # for a repository that set `search.min_coverage` to zero and asked for the
    # old behaviour. Under the feature hash at any positive setting this branch
    # is unreachable, which is the point: there, similarity over hashed token
    # overlap ranked the entire corpus on noise.
    candidate_ids = lexical_scores.keys() if lexical_scores else search_index.units.keys()
    # Semantics may add candidates; hashed token overlap may not. This is the
    # single place a vector can change what is *found* rather than what order
    # things are returned in, and it is gated on the embedder because the same
    # widening measured worse under the feature hash.
    if lexical_scores and vector_recall > 0 and query_features and getattr(search_index.embedder, "semantic", False):
        width = len(query_vector)
        nearest = heapq.nlargest(
            vector_recall,
            (
                (sum(value * unit.vector[index] for index, value in query_features), unit_id)
                for unit_id, unit in search_index.units.items()
                if unit_id not in lexical_scores and len(unit.vector) == width
            ),
        )
        if nearest:
            vector_ids.update(unit_id for _, unit_id in nearest)
            candidate_ids = list(lexical_scores) + [unit_id for _, unit_id in nearest]
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
