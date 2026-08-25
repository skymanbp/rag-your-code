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


@pytest.fixture(scope="module")
def units():
    # With the description store, because that is how the CLI builds an index.
    # Without it the same ruler scores 0.171 rather than 0.500 on hit@1, which
    # would be measuring a configuration nobody runs.
    return build_units(ROOT, descriptions=descriptions_module.load(ROOT))


def test_every_acceptable_answer_names_code_that_exists(units):
    problems = check_ruler(load_questions(), units)
    assert not problems, "the ruler has drifted from the code:\n  " + "\n  ".join(problems)


def test_the_ruler_is_well_formed():
    questions = load_questions()
    entries = questions["queries"]
    assert len(entries) >= 50, "too few questions to distinguish a change from noise"
    assert questions["k"] >= 1
    for entry in entries:
        assert entry["query"].strip(), f"{entry['id']}: empty question"
        assert entry["language"] in {"en", "zh"}
        assert entry["kind"] in {"concept", "why", "symbol"}
        assert all(len(pair) == 2 for pair in entry["acceptable"])
    # Both languages have to be represented, because the CJK path through the
    # tokenizer is the one place a query can share no character class with the
    # text it must match.
    languages = {entry["language"] for entry in entries}
    assert languages == {"en", "zh"}


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
