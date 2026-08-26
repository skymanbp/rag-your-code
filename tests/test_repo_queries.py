"""The repository-questions ruler must keep referring to real code.

A ruler is only worth what it is checked against. If a declaration is renamed
and its question quietly stops matching anything, retrieval looks worse; if the
question were then removed to make the number go up, retrieval looks better.
Both are the ruler failing, not retrieval, and neither is visible from the
score alone. So the ruler is validated structurally here, and its *score* is
deliberately not asserted -- it moves whenever the repository gains code that
nobody has described yet, which is normal and not a regression.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks.repo_queries import QUERIES_PATH, check_ruler, evaluate, load_questions
from ragyourcode import descriptions as descriptions_module
from ragyourcode.indexer import build_units

ROOT = Path(__file__).resolve().parents[1]
COLD_PATH = ROOT / "benchmarks" / "cold_queries.json"
COBRA_PATH = ROOT / "benchmarks" / "cobra_queries.json"


@pytest.fixture(scope="module")
def units():
    # With the description store, because that is how the CLI builds an index.
    return build_units(ROOT, descriptions=descriptions_module.load(ROOT))


@pytest.fixture(scope="module")
def cold_units():
    """The same repository as a first-time user's index sees it: parsed, with
    only the sentence the parser generates and nothing anybody wrote.
    """
    return build_units(ROOT)


def test_every_acceptable_answer_names_code_that_exists(units):
    problems = check_ruler(load_questions(), units)
    assert not problems, "the ruler has drifted from the code:\n  " + "\n  ".join(problems)


@pytest.mark.parametrize("path", [QUERIES_PATH, COLD_PATH, COBRA_PATH], ids=["repository", "cold", "cobra"])
def test_the_ruler_is_well_formed(path: Path):
    questions = load_questions(path)
    entries = questions["queries"]
    assert len(entries) >= 30, "too few questions to distinguish a change from noise"
    assert questions["k"] >= 1
    seen: set[str] = set()
    for entry in entries:
        assert entry["query"].strip(), f"{entry['id']}: empty question"
        assert entry["id"] not in seen, f"{entry['id']}: duplicate question id"
        seen.add(entry["id"])
        assert entry["language"] in {"en", "zh"}
        assert entry["kind"] in {"concept", "why", "symbol"}
        assert entry["acceptable"], f"{entry['id']}: no acceptable answer listed"
        assert all(len(pair) == 2 for pair in entry["acceptable"])
    # Both languages have to be represented, because the CJK path through the
    # tokenizer is the one place a query can share no character class with the
    # text it must match.
    languages = {entry["language"] for entry in entries}
    assert languages == {"en", "zh"}


@pytest.mark.parametrize("path", [COLD_PATH, COBRA_PATH], ids=["cold", "cobra"])
def test_a_foreign_ruler_says_which_repository_it_grades(path: Path):
    """It grades code that is not in this repository, so it has to name it and
    say why a ruler asked about this project cannot stand in for it.
    """
    questions = load_questions(path)
    assert questions["repository"], "a ruler over foreign code must name that code"
    assert questions["caveat"].strip()
    assert questions["why"].strip()
    pinned = questions["measured_against"]
    for field in ("upstream", "tag", "commit", "released", "licence", "omitted"):
        assert pinned.get(field), f"{path.name}: the vendored subject must record {field}"
    corpus = ROOT / questions["vendored"]
    assert corpus.is_dir(), f"{path.name} names {corpus}, which is not here"


@pytest.mark.parametrize("path", [COLD_PATH, COBRA_PATH], ids=["cold", "cobra"])
def test_every_acceptable_answer_on_a_foreign_ruler_names_code_that_exists(path: Path):
    """The check the runner performs, made a test so a vendored corpus cannot
    be bumped to a new tag without the questions being re-checked against it.
    """
    questions = load_questions(path)
    corpus = build_units(ROOT / questions["vendored"])
    assert not check_ruler(questions, corpus)


def test_written_descriptions_beat_generated_ones(units, cold_units):
    """The reason `describe` exists, asserted rather than stated.

    This used to be a comment quoting two numbers, which is exactly the kind of
    claim that rots: both had already moved by the time anybody looked.
    """
    questions = load_questions()
    warm = evaluate(units, questions)["aggregate"]
    cold = evaluate(cold_units, questions)["aggregate"]
    assert warm["hit_at_1"] > cold["hit_at_1"], (warm, cold)
    assert warm["mrr"] > cold["mrr"], (warm, cold)


def test_the_ruler_has_headroom(units):
    """A ruler everything already passes cannot measure an improvement.

    This is the property the eight-question set lacked: every candidate change
    scored between five and six out of eight, so nothing could be told apart.
    """
    report = evaluate(units, load_questions())
    assert report["misses"], "no question fails; this ruler can no longer show progress"
    assert report["aggregate"]["hit_at_1"] > 0.2, "so many questions fail that the ruler is measuring noise"


def test_the_questions_file_is_the_only_place_the_count_lives():
    """The module docstring must not restate a figure that would rot."""
    source = (ROOT / "benchmarks" / "repo_queries.py").read_text(encoding="utf-8")
    docstring = source[: source.index('"""', 3)]
    count = str(len(json.loads(QUERIES_PATH.read_text(encoding="utf-8"))["queries"]))
    assert count not in docstring
