"""The ruler that grades silence has to be kept honest too.

`repo_queries.json` and `cold_queries.json` are checked against the code they
name: a renamed declaration fails loudly rather than reading as a regression.
`absent_queries.json` makes the opposite claim -- that nothing answers these
questions -- and a claim like that rots in the opposite direction. The day this
repository grows a DNS resolver, `how is a hostname resolved` stops being
unanswerable, and a ruler nobody checks would go on scoring a correct answer as
a failure to stay quiet.

So the claim is made mechanical: each question carries the vocabulary that
makes it the question it is, and that vocabulary must reach no unit at all.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from benchmarks.repo_queries import check_ruler, evaluate, load_questions
from ragyourcode import descriptions as descriptions_module
from ragyourcode.indexer import build_units
from ragyourcode.search import build_search_index

ROOT = Path(__file__).resolve().parents[1]
ABSENT_PATH = ROOT / "benchmarks" / "absent_queries.json"


@pytest.fixture(scope="module")
def units():
    return build_units(ROOT, descriptions=descriptions_module.load(ROOT))


def test_the_absent_ruler_is_well_formed():
    questions = load_questions(ABSENT_PATH)
    entries = questions["queries"]
    assert len(entries) >= 30, "too few questions to distinguish a change from noise"
    seen: set[str] = set()
    for entry in entries:
        assert entry["query"].strip(), f"{entry['id']}: empty question"
        assert entry["id"] not in seen, f"{entry['id']}: duplicate question id"
        seen.add(entry["id"])
        assert entry["language"] in {"en", "zh"}
        assert entry["kind"] in {"concept", "why", "symbol"}
        assert entry["absent"] is True, f"{entry['id']}: this ruler grades silence only"
        assert entry["acceptable"] == [], f"{entry['id']}: an absent question cannot have an answer"
        assert entry["subject"], f"{entry['id']}: absence is asserted through this vocabulary"
    # Both languages, because the failure this ruler measures turned out to
    # look very different in each: the coverage bar silences almost every
    # Chinese question and only two thirds of the English ones.
    assert {entry["language"] for entry in entries} == {"en", "zh"}
    assert questions["why"].strip() and questions["caveat"].strip()


def _intruders(units) -> list[tuple[str, str, int]]:
    """Which absent question's own vocabulary reaches a corpus that must not
    contain it.
    """
    index = build_search_index(units)
    return [
        (entry["id"], term, len(index.postings[term]))
        for entry in load_questions(ABSENT_PATH)["queries"]
        for term in entry["subject"]
        if index.postings.get(term)
    ]


def test_no_subject_of_an_absent_question_exists_in_this_repository(units):
    """The absence claim, re-derived rather than trusted.

    This is the assertion the ruler's own caveat promises, and it is the one
    that fails first when the repository grows into a subject the ruler
    assumed it would never contain.
    """
    assert not _intruders(units), (
        "this repository now contains the vocabulary of a question the ruler calls unanswerable; "
        f"retire or rewrite those questions rather than letting them score as misses: {_intruders(units)}"
    )


def test_no_subject_of_an_absent_question_exists_in_the_vendored_corpus():
    """The other half of the same claim, which used to be unenforceable.

    This ruler asserts its questions are unanswerable in *both* graded
    repositories. Until the foreign one was vendored that half could only be
    asserted, because the subject was somebody else's checkout and a re-run
    here could not see what it had become. It is now a directory in this
    repository at a pinned tag, so the claim is a test.

    It has already earned its place. One question's subject list carried a
    generic English verb where a specific term belonged, and the corpus below
    uses that verb in a comment about signing keys -- so the question was one
    ordinary word away from being answerable by accident. The verb was
    replaced with a term that names the thing.

    Naming the subject here would put it in the index and break the very
    claim this asserts, which is why the paragraph above is written around it.
    That has now happened five times; CONTRIBUTING.md keeps the tally.
    """
    corpus = ROOT / "benchmarks" / "corpus" / "flask"
    assert corpus.is_dir(), f"the vendored corpus is missing from {corpus}"
    assert not _intruders(build_units(corpus)), (
        "the vendored corpus contains the vocabulary of a question the ruler calls unanswerable; "
        f"rewrite the question rather than letting it score as a miss: {_intruders(build_units(corpus))}"
    )


def test_the_absent_ruler_is_scored_on_silence_and_not_folded_into_hit_rates(units):
    """Averaging a question that should return something with one that should
    return nothing produces a number that improves when either half gets worse.
    """
    report = evaluate(units, load_questions(ABSENT_PATH))
    assert report["aggregate"]["questions"] == 0, "no absent question may enter the hit-rate aggregate"
    assert report["absent"]["questions"] == len(load_questions(ABSENT_PATH)["queries"])
    assert report["misses"] == [], "a question with no answer cannot be missed"


def test_check_ruler_refuses_a_question_claiming_both_absence_and_an_answer(units):
    """The two halves of the claim are held consistent, so a set cannot drift
    into a mix graded by whichever branch it happens to fall down.
    """
    questions = load_questions(ABSENT_PATH)
    assert check_ruler(questions, units) == []
    contradiction = {**questions, "queries": [{**questions["queries"][0], "acceptable": [["a.py", "b"]]}]}
    problems = check_ruler(contradiction, units)
    assert problems and "absent" in problems[0]


def test_this_repository_is_mostly_silent_on_questions_it_cannot_answer(units):
    """The number this whole change exists to move.

    Before the coverage bar it was 0.000 -- all 32 answered, in both languages,
    on both repositories. It is asserted as a floor rather than as a figure
    because it moves with the corpus, and the floor is what must not rot.
    """
    report = evaluate(units, load_questions(ABSENT_PATH))
    assert report["absent"]["silence"] >= 0.9, report["spoke"]


def test_each_bar_alone_leaves_questions_the_other_one_catches(units):
    """Two bars, and the test has to show that both are load-bearing.

    Coverage asks whether the words are here; concentration asks whether they
    are here *together*. Opening either one on its own must let some question
    through that the pair refuses, or one of them is decoration -- and a
    decorative bar is worse than none, because its number gets quoted.
    """
    questions = load_questions(ABSENT_PATH)
    both = evaluate(units, questions)["absent"]["silence"]
    coverage_only = evaluate(units, questions, min_concentration=0.0)["absent"]["silence"]
    concentration_only = evaluate(units, questions, min_coverage=0.0)["absent"]["silence"]
    assert coverage_only < both, "concentration catches nothing coverage did not already"
    assert concentration_only <= both


def test_opening_both_bars_restores_the_defect_they_exist_to_fix(units):
    """Without this, the assertion above would also pass if retrieval had
    simply stopped returning anything, and the two are told apart by exactly
    two arguments.
    """
    report = evaluate(units, load_questions(ABSENT_PATH), min_coverage=0.0, min_concentration=0.0)
    assert report["absent"]["silence"] == 0.0, "with no bar, ranking answers every question it is asked"
