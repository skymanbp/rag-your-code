from __future__ import annotations

from pathlib import Path

from ragyourcode.agentic import research
from ragyourcode.graph import build_graph
from ragyourcode.indexer import build_units
from ragyourcode.search import build_search_index


def test_agentic_research_is_bounded_and_explainable(tmp_path: Path):
    (tmp_path / "service.py").write_text(
        "def fetch():\n    return 1\n\ndef process():\n    return fetch()\n",
        encoding="utf-8",
    )
    units = build_units(tmp_path)
    result = research(
        units,
        "unrelated behavior",
        limit=4,
        hops=1,
        max_steps=2,
        confidence_threshold=0.99,
        graph=build_graph(units),
        search_index=build_search_index(units),
    )
    assert len(result["steps"]) <= 2
    assert result["stop_reason"] in {"new_graph_evidence", "no_new_evidence", "no_results", "high_confidence"}
    assert "results" in result
