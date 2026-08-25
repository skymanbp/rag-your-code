"""Guards for the bounded research loop and for the payload it returns.

The early stop used to be an absolute score threshold of 0.8. When ranking
became BM25F the score scale moved underneath it and only 3% of queries could
reach 0.8 at all, so the stop silently stopped existing -- a constant coupled
to a scale nobody recorded. It is a margin now, which is a ratio between two
scores from the same query and cannot drift when the scoring changes again.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ragyourcode.agentic import DEFAULT_DOMINANCE, dominance, research
from ragyourcode.graph import build_graph
from ragyourcode.indexer import build_units
from ragyourcode.models import CodeUnit, SearchResult
from ragyourcode.search import build_search_index, search


def _service(root: Path) -> list[CodeUnit]:
    (root / "service.py").write_text(
        "def fetch():\n    return 1\n\ndef process():\n    return fetch()\n",
        encoding="utf-8",
    )
    return build_units(root)


def _result(score: float) -> SearchResult:
    unit = CodeUnit(
        id=f"x.py:1:u{score}",
        path="x.py",
        language="python",
        kind="function",
        name="u",
        qualified_name="u",
        signature="def u():",
        start_line=1,
        end_line=1,
        source="def u():\n    return 1\n",
        description="",
        serial=1,
    )
    return SearchResult(unit, score, ["u"])


def test_agentic_research_is_bounded_and_explainable(tmp_path: Path):
    units = _service(tmp_path)
    result = research(
        units,
        "unrelated behavior",
        limit=4,
        hops=1,
        max_steps=2,
        graph=build_graph(units),
        search_index=build_search_index(units),
    )
    assert len(result["steps"]) <= 2
    assert result["stop_reason"] in {"new_graph_evidence", "no_new_evidence", "no_results", "high_confidence"}
    assert "results" in result


def test_a_dominant_top_result_skips_the_second_step(tmp_path: Path):
    """The stop has to actually fire, which the old threshold no longer did."""
    units = _service(tmp_path)
    result = research(
        units,
        "process",
        limit=4,
        max_steps=2,
        dominance_threshold=0.0,
        graph=build_graph(units),
        search_index=build_search_index(units),
    )
    assert result["stop_reason"] == "high_confidence"
    assert len(result["steps"]) == 1


def test_a_close_field_does_not_skip_the_second_step(tmp_path: Path):
    units = _service(tmp_path)
    result = research(
        units,
        "process",
        limit=4,
        max_steps=2,
        dominance_threshold=1.01,
        graph=build_graph(units),
        search_index=build_search_index(units),
    )
    assert result["stop_reason"] != "high_confidence"
    assert len(result["steps"]) == 2


def test_dominance_is_a_ratio_not_a_score():
    """Scaling every score by the same factor must not change the decision.

    This is the property the absolute threshold lacked, and the reason it died
    silently: multiply the old scores by 0.4 and the stop stops firing.
    """
    close = [_result(1.0), _result(0.9)]
    scaled = [_result(0.4), _result(0.36)]
    assert dominance(close) == pytest.approx(dominance(scaled))
    assert dominance([_result(1.0)]) == 1.0
    assert dominance([]) == 0.0
    assert 0.0 < DEFAULT_DOMINANCE < 1.0


def test_a_research_reply_carries_the_code_once(tmp_path: Path):
    """Two reported steps used to mean three copies of every unit's source.

    Measured on a 1153-unit repository, one research answer was 111,843
    characters against a stated budget of 12,000.
    """
    units = _service(tmp_path)
    result = research(
        units,
        "process fetch",
        limit=4,
        max_steps=2,
        graph=build_graph(units),
        search_index=build_search_index(units),
    )
    assert all("source" not in entry["unit"] for entry in result["results"])
    for step in result["steps"]:
        for entry in step["results"]:
            assert set(entry) == {"id", "score", "matched_terms"}, entry
    assert "return fetch()" in result["context"]


def test_a_search_result_is_navigation_not_a_copy_of_the_file(tmp_path: Path):
    units = _service(tmp_path)
    serialised = search(units, "process", limit=2)[0].to_dict()
    assert "source" not in serialised["unit"]
    assert "vector" not in serialised["unit"]
    # What a caller needs to go and look, and to check why it was returned.
    assert {"id", "path", "start_line", "end_line", "signature", "description"} <= set(serialised["unit"])
    assert {"score", "matched_terms", "evidence"} <= set(serialised)


def test_a_stored_unit_still_carries_its_source(tmp_path: Path):
    """Dropping source from a *result* must not drop it from the index."""
    unit = _service(tmp_path)[0]
    assert "source" in unit.to_dict()
    assert CodeUnit.from_dict(unit.to_dict()).source == unit.source
