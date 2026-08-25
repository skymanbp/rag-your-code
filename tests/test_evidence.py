"""Retrieval must be able to say it has no answer.

Ranking always produces a least-bad unit and returns it with a score and a
rank, which read exactly like an answer. Graded against 32 questions about
subjects neither this repository nor `benchmarks/cold_queries.json`'s
repository implements, every single one came back answered -- `where are CUDA
kernels dispatched to the device` on the evidence of `are`, `the`, `to` and
`where`. These assert the second question retrieval now asks: not which unit
ranks highest, but whether any of this is evidence at all.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ragyourcode.agentic import research
from ragyourcode.graph import graph_search
from ragyourcode.indexer import build_units
from ragyourcode.search import (
    COVERAGE_FULL_STRENGTH,
    DEFAULT_MIN_CONCENTRATION,
    DEFAULT_MIN_COVERAGE,
    assess,
    build_search_index,
    diagnose,
    search,
)


def _repository(root: Path, count: int) -> Path:
    """A repository about one subject, large enough for the coverage bar to be
    at full strength. Every unit shares the words that describe the subject,
    so those become the ubiquitous ones -- which is the arrangement the gate
    exists to see through.
    """
    for index in range(count):
        (root / f"ledger_{index}.py").write_text(
            f"def post_ledger_entry_{index}(entry, ledger):\n"
            '    """Post an accounting entry to the ledger and return the ledger."""\n'
            "    return ledger\n",
            encoding="utf-8",
        )
    (root / "reconcile.py").write_text(
        "def reconcile_quarterly_statement(entry, ledger):\n"
        '    """Reconcile a quarterly statement against the ledger."""\n'
        "    return ledger\n",
        encoding="utf-8",
    )
    return root


@pytest.fixture(scope="module")
def big(tmp_path_factory) -> list:
    return build_units(_repository(tmp_path_factory.mktemp("big"), COVERAGE_FULL_STRENGTH + 20))


SCATTERED_QUERY = "the propeller gantry turbine and nacelle"
RARE = ("propeller", "gantry", "turbine", "nacelle")


def _with_rare_words(root: Path, together: bool) -> list:
    """The same four rare words, once spread over four declarations and once
    gathered into one.

    Four rather than two, and that is the measure's own arithmetic rather than
    a choice: N equally rare words spread over N units put 1/N of the query's
    weight in the best of them, so two scattered words score 0.50 and cannot be
    told from a real half-match. Scattering only becomes visible once a question
    asks about several distinct things -- which is exactly when a wrong answer
    would have looked most convincing.

    Everything else about the two repositories is identical, so any difference
    in what retrieval does is the co-occurrence and nothing else.
    """
    _repository(root, COVERAGE_FULL_STRENGTH + 20)
    if together:
        (root / "rig.py").write_text(
            "def align_the_assembly(entry, ledger):\n"
            f'    """Align the {" and ".join(RARE)} before posting."""\n'
            "    return ledger\n",
            encoding="utf-8",
        )
    else:
        for word in RARE:
            (root / f"rig_{word}.py").write_text(
                f"def inspect_the_{word}(entry, ledger):\n"
                f'    """Inspect the {word} before posting."""\n'
                "    return ledger\n",
                encoding="utf-8",
            )
    units = build_units(root)
    return [units, build_search_index(units)]


@pytest.fixture(scope="module")
def scattered(tmp_path_factory) -> list:
    return _with_rare_words(tmp_path_factory.mktemp("apart"), together=False)


@pytest.fixture(scope="module")
def gathered(tmp_path_factory) -> list:
    return _with_rare_words(tmp_path_factory.mktemp("together"), together=True)


def test_a_question_this_repository_cannot_answer_returns_nothing(big):
    """The whole point, stated once.

    Nothing here is about GPUs. The words that do match -- `to`, `the` -- are
    words this repository uses everywhere, and half a query matching looks
    like evidence until you notice which half.
    """
    index = build_search_index(big)
    assert search(big, "where are CUDA kernels dispatched to the device", search_index=index) == []


def test_the_same_question_is_answered_when_the_gate_is_opened(big):
    """The gate is what withholds it, not a failure to retrieve.

    Without this, a test asserting emptiness would also pass if retrieval had
    simply broken -- and the two are told apart by exactly two arguments.
    """
    index = build_search_index(big)
    guesses = search(
        big,
        "where are CUDA kernels dispatched to the device",
        search_index=index,
        min_coverage=0.0,
        min_concentration=0.0,
    )
    assert guesses, "with no bar, ranking still hands back a least-bad unit"
    assert not guesses[0].matched_terms or set(guesses[0].matched_terms) <= {"to", "the", "are", "where"}


def test_a_real_question_about_this_repository_is_still_answered(big):
    """The bar has to let the answerable through, or it is just an off switch."""
    index = build_search_index(big)
    results = search(big, "reconcile the quarterly statement", search_index=index)
    assert results, "a question this repository answers must survive the bar"
    assert results[0].unit.name == "reconcile_quarterly_statement"


def test_words_the_whole_repository_uses_are_not_evidence(big):
    """A query made only of the subject's own vocabulary singles out nothing."""
    index = build_search_index(big)
    evidence = assess(index, "entry ledger")
    assert evidence.matched == (), "terms this common must not count towards coverage"
    assert evidence.ubiquitous, "they matched, they just do not discriminate"
    assert evidence.reason == "only_ubiquitous_terms_matched"
    assert search(big, "entry ledger", search_index=index) == []


def test_a_query_sharing_no_word_at_all_is_named_as_such(big):
    index = build_search_index(big)
    evidence = assess(index, "renegotiating multilateral tariffs")
    assert evidence.matched == () and evidence.ubiquitous == ()
    assert evidence.reason == "no_query_term_in_index"


def test_the_four_reasons_are_distinct_and_each_carries_a_hint(big, scattered):
    """An empty answer is only actionable if it says which kind of empty.

    Each of these is recovered by a different move, so collapsing them into
    one `no_results` would throw away the only part a caller can act on.
    """
    index = build_search_index(big)
    asked = [
        (index, "renegotiating multilateral tariffs"),
        (index, "entry ledger"),
        (index, "post a reconciliation somewhere obscure"),
        (scattered[1], SCATTERED_QUERY),
    ]
    reasons = {diagnose(assess(where, query))["reason"] for where, query in asked}
    assert len(reasons) == 4, reasons
    for where, query in asked:
        report = diagnose(assess(where, query))
        assert report["hint"], f"{report['reason']} must tell the caller what to do next"
        assert report["min_coverage"] == DEFAULT_MIN_COVERAGE
        assert report["min_concentration"] == DEFAULT_MIN_CONCENTRATION


def test_words_that_never_occur_together_are_not_evidence(scattered):
    """Coverage is satisfiable out of units that have nothing to do with the
    question, and that is how a repository answers a question about a subject
    it does not contain: every word is here, no two of them in one place.
    """
    units, index = scattered
    evidence = assess(index, SCATTERED_QUERY)
    assert set(evidence.matched) == set(RARE), "every rare word of the query is in this index"
    assert evidence.coverage == 1.0, "coverage alone calls this perfect evidence"
    assert evidence.concentration < DEFAULT_MIN_CONCENTRATION
    assert evidence.reason == "matched_terms_are_scattered"
    assert search(units, SCATTERED_QUERY, search_index=index) == []


def test_the_same_words_are_evidence_once_one_unit_holds_them_all(gathered):
    """The other side of the same rule, so what is measured is the
    co-occurrence and not merely the words being unusual.
    """
    units, index = gathered
    assert assess(index, SCATTERED_QUERY).coverage == 1.0, "identical coverage to the scattered case"
    results = search(units, SCATTERED_QUERY, search_index=index)
    assert results, "one declaration about all of them is what the bar looks for"
    assert results[0].unit.name == "align_the_assembly"


def test_a_small_repository_is_not_refused_its_own_questions(tmp_path):
    """A ten-unit index cannot hold the vocabulary of a sentence.

    Measured on one repository subsampled to eight sizes, coverage of
    answerable questions falls from 0.789 at 1153 units to 0.410 at 10, while
    coverage of unanswerable ones stays flat at 0.13-0.18. Applying the full
    bar there would refuse questions the index can answer, so it is eased in
    proportion instead -- and that easing is what this asserts.
    """
    units = build_units(_repository(tmp_path, 8))
    index = build_search_index(units)
    assert len(units) < COVERAGE_FULL_STRENGTH
    assert search(units, "reconcile the quarterly statement please", search_index=index)


def test_the_bar_reaches_full_strength_only_once_the_index_is_large_enough(big, tmp_path):
    """The ramp, asserted as a comparison rather than as a number."""
    small = build_search_index(build_units(_repository(tmp_path, 8)))
    query = "where are CUDA kernels dispatched to the device"
    assert assess(build_search_index(big), query).sufficient is False
    assert assess(small, query).sufficient is True, "a tiny index must not pretend to this much judgement"


def test_a_semantic_embedder_is_not_exempt(big):
    """1.0.0 exempted one and this asserts the correction.

    The reasoning behind the exemption was that a paraphrase sharing no word
    with its answer is exactly what a model is for, so lexical evidence is then
    evidence of nothing. Sound, and wrong: measured against a real multilingual
    model, exempt and asked no other question, retrieval answered all sixty
    questions about subjects neither graded repository implements -- the whole
    defect the bar exists to fix, back again by the one path that skipped it.
    Applying the bars to the model instead costs the foreign ruler nothing
    measurable and holds silence at 0.967.
    """

    class Semantic:
        semantic = True

        def one(self, text):
            return [0.0] * 8

    index = build_search_index(big)
    index.embedder = Semantic()
    assert assess(index, "where are CUDA kernels dispatched to the device").sufficient is False


def test_graph_expansion_does_not_walk_outward_from_a_withheld_seed(big):
    """Expanding a guess turns one unsupported result into a neighbourhood."""
    index = build_search_index(big)
    assert graph_search(big, "where are CUDA kernels dispatched to the device", search_index=index) == []


def test_research_reports_why_it_stopped_without_changing_stop_reason(big):
    """`stop_reason` keeps its published values; the detail arrives beside it.

    Widening an enumeration callers already branch on is a breaking change
    wearing the clothes of an improvement.
    """
    reply = research(big, "where are CUDA kernels dispatched to the device", search_index=build_search_index(big))
    assert reply["results"] == []
    assert reply["stop_reason"] == "no_results"
    assert reply["diagnosis"]["reason"] == "only_ubiquitous_terms_matched"
    assert reply["diagnosis"]["hint"]


def test_the_cli_reports_the_diagnosis_and_reports_none_when_it_answered(tmp_path, capsys):
    """Both branches of the field, because a caller reads it unconditionally."""
    from ragyourcode.cli import main

    _repository(tmp_path, COVERAGE_FULL_STRENGTH + 20)
    assert main(["index", str(tmp_path)]) == 0
    capsys.readouterr()

    assert main(["search", "where are CUDA kernels dispatched", "--root", str(tmp_path), "--json"]) == 0
    refused = json.loads(capsys.readouterr().out)
    assert refused["results"] == []
    assert refused["diagnosis"]["reason"]
    assert refused["diagnosis"]["hint"]

    assert main(["search", "reconcile the quarterly statement", "--root", str(tmp_path), "--json"]) == 0
    answered = json.loads(capsys.readouterr().out)
    assert answered["results"]
    assert answered["diagnosis"] is None
