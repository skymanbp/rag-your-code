from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from ragyourcode.graph import build_graph, graph_search
from ragyourcode.indexer import build_units, read_index, write_index
from ragyourcode.search import build_search_index


def test_global_serials_are_unique_across_files(tmp_path: Path):
    (tmp_path / "a.py").write_text("def first():\n    return 1\n\ndef second():\n    return 2\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("def third():\n    return 3\n", encoding="utf-8")
    units = build_units(tmp_path)
    assert [unit.serial for unit in units] == [1, 2, 3]
    assert len({unit.serial for unit in units}) == len(units)


def test_incremental_build_reuses_unchanged_unit_and_serial(tmp_path: Path):
    source = tmp_path / "worker.py"
    source.write_text("def run():\n    return 1\n", encoding="utf-8")
    first = build_units(tmp_path)
    first_unit = first[0]
    index = tmp_path / "index.json"
    write_index(index, tmp_path, first)
    payload, old_units = read_index(index)
    second = build_units(tmp_path, previous_units=old_units, previous_files=payload["files"])
    assert second[0].serial == first_unit.serial
    assert second[0].vector == first_unit.vector

    source.write_text("def run():\n    return 2\n", encoding="utf-8")
    changed = build_units(tmp_path, previous_units=old_units, previous_files=payload["files"])
    assert changed[0].serial == first_unit.serial
    assert changed[0].source != first_unit.source
    assert changed[0].vector != first_unit.vector


def test_compact_vector_sidecar_round_trip(tmp_path: Path):
    (tmp_path / "worker.py").write_text("def run():\n    return 1\n", encoding="utf-8")
    index = tmp_path / "index.json"
    units = build_units(tmp_path)
    write_index(index, tmp_path, units, compact=True)
    payload, loaded = read_index(index)
    assert payload["vector_store"]["dtype"] == "float32-le"
    assert loaded[0].vector
    assert len(loaded[0].vector) == len(units[0].vector)


def test_incremental_compact_refresh_preserves_sidecar(tmp_path: Path):
    source = tmp_path / "worker.py"
    source.write_text("def run():\n    return 1\n", encoding="utf-8")
    index = tmp_path / "index.json"
    units = build_units(tmp_path)
    write_index(index, tmp_path, units, compact=True)
    payload, old_units = read_index(index)
    old_sidecar = index.parent / payload["vector_store"]["path"]
    source.write_text("def run():\n    return 2\n", encoding="utf-8")
    changed = build_units(tmp_path, previous_units=old_units, previous_files=payload["files"])
    write_index(index, tmp_path, changed, compact=True)
    refreshed, loaded = read_index(index)
    assert refreshed.get("vector_store")
    assert loaded[0].vector
    assert not old_sidecar.exists()
    assert len(list(tmp_path.glob("index.*.vectors.bin"))) == 1


def test_graph_search_returns_call_path_evidence(tmp_path: Path):
    (tmp_path / "service.py").write_text(
        "def fetch():\n    return 1\n\ndef process():\n    return fetch()\n",
        encoding="utf-8",
    )
    units = build_units(tmp_path)
    graph = build_graph(units)
    results = graph_search(units, "process", limit=4, hops=1, graph=graph, search_index=build_search_index(units))
    process = next(result for result in results if result.unit.name == "process")
    fetch = next(result for result in results if result.unit.name == "fetch")
    assert any("graph:" in evidence for evidence in fetch.evidence)
    assert any("calls" in edge.kind for edge in graph.edges)
    assert process.unit.name == "process"


def test_ambiguous_cross_file_calls_are_not_guessed(tmp_path: Path):
    (tmp_path / "a.py").write_text("def shared():\n    return 'a'\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("def shared():\n    return 'b'\n", encoding="utf-8")
    (tmp_path / "caller.py").write_text("def caller():\n    return shared()\n", encoding="utf-8")
    graph = build_graph(build_units(tmp_path))
    assert not any(edge.kind == "calls" and edge.label == "shared" for edge in graph.edges)


def test_agent_graph_open_neighbors_refresh_protocol(tmp_path: Path):
    (tmp_path / "service.py").write_text("def fetch():\n    return 1\n\ndef process():\n    return fetch()\n", encoding="utf-8")
    subprocess.run([sys.executable, "-m", "ragyourcode.cli", "index", str(tmp_path)], check=True, capture_output=True, text=True)
    proc = subprocess.run(
        [sys.executable, "-m", "ragyourcode.cli", "agent", "--root", str(tmp_path)],
        input=(
            '{"action":"search","query":"process","graph":true}\n'
            '{"action":"open","path":"service.py","start_line":1,"end_line":1}\n'
            '{"action":"open","path":"../secret.txt"}\n'
            '{"action":"refresh"}\n'
            '{"action":"stats"}\n'
        ),
        check=True,
        capture_output=True,
        text=True,
    )
    lines = [json.loads(line) for line in proc.stdout.splitlines()]
    assert lines[0]["results"]
    assert lines[0]["results"][0]["unit"]["name"] == "process"
    assert lines[1]["source"] == "def fetch():"
    assert lines[2]["error"] == "path_outside_root"
    assert lines[3]["indexed_units"] == 2
    assert lines[4]["edges"] >= 1
