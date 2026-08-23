from __future__ import annotations

import json
from pathlib import Path

from ragyourcode.graph import graph_from_dict
from ragyourcode.annotate import comment_for
from ragyourcode.embeddings import embed
from ragyourcode.indexer import MAX_SOURCE_BYTES, build_units, file_fingerprints, iter_source_files, read_index, write_index


def test_corrupt_graph_edges_are_ignored(tmp_path: Path):
    (tmp_path / "x.py").write_text("def run():\n    return 1\n", encoding="utf-8")
    units = build_units(tmp_path)
    graph = graph_from_dict(units, {"edges": [{"source": "bad"}, "not-an-edge", {"source": units[0].id, "target": units[0].id, "kind": "self"}]})
    assert len(graph.edges) == 1


def test_schema_one_index_can_be_read_and_rebuilt(tmp_path: Path):
    (tmp_path / "x.py").write_text("def run():\n    return 1\n", encoding="utf-8")
    units = build_units(tmp_path)
    index = tmp_path / "index.json"
    index.write_text(json.dumps({"schema": 1, "units": [unit.to_dict() for unit in units]}), encoding="utf-8")
    payload, loaded = read_index(index)
    assert payload["schema"] == 1
    assert loaded[0].name == "run"


def test_duplicate_legacy_serial_reembeds_reassigned_unit(tmp_path: Path):
    (tmp_path / "a.py").write_text("def first():\n    return 1\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("def second():\n    return 2\n", encoding="utf-8")
    old = build_units(tmp_path)
    for unit in old:
        unit.serial = 1
        unit.vector = embed(comment_for(unit.description, unit.serial, unit.id) + "\n" + unit.searchable_text)
    old_second_vector = list(old[1].vector)
    rebuilt = build_units(tmp_path, previous_units=old, previous_files=file_fingerprints(tmp_path))
    assert [unit.serial for unit in rebuilt] == [1, 2]
    assert rebuilt[1].vector != old_second_vector
    expected = embed(comment_for(rebuilt[1].description, 2, rebuilt[1].id) + "\n" + rebuilt[1].searchable_text)
    assert rebuilt[1].vector == expected


def test_switching_from_compact_removes_stale_sidecar(tmp_path: Path):
    (tmp_path / "x.py").write_text("def run():\n    return 1\n", encoding="utf-8")
    units = build_units(tmp_path)
    index = tmp_path / "index.json"
    write_index(index, tmp_path, units, compact=True)
    payload, _ = read_index(index)
    sidecar = index.parent / payload["vector_store"]["path"]
    assert sidecar.exists()
    write_index(index, tmp_path, units, compact=False)
    assert not sidecar.exists()


def test_missing_compact_sidecar_is_explicitly_degraded(tmp_path: Path):
    (tmp_path / "x.py").write_text("def run():\n    return 1\n", encoding="utf-8")
    index = tmp_path / "index.json"
    write_index(index, tmp_path, build_units(tmp_path), compact=True)
    payload = json.loads(index.read_text(encoding="utf-8"))
    (index.parent / payload["vector_store"]["path"]).unlink()
    degraded, units = read_index(index)
    assert degraded["degraded"] == "vector_store_unavailable"
    assert units[0].vector == []


def test_oversized_source_is_skipped(tmp_path: Path):
    source = tmp_path / "generated.py"
    with source.open("wb") as stream:
        stream.seek(MAX_SOURCE_BYTES)
        stream.write(b"x")
    assert list(iter_source_files(tmp_path)) == []


def test_python_syntax_error_is_reported(tmp_path: Path):
    (tmp_path / "broken.py").write_text("def broken(:\n    pass\n", encoding="utf-8")
    diagnostics: list[dict] = []
    assert build_units(tmp_path, diagnostics=diagnostics) == []
    assert diagnostics[0]["code"] == "syntax_error"
    assert diagnostics[0]["path"] == "broken.py"


def test_index_supplied_sidecar_path_cannot_delete_a_source_file(tmp_path: Path):
    """A scanned repository may ship its own index.json; it is untrusted input.

    Deriving the sidecar to delete from that file turned the documented
    ``index`` command into an arbitrary in-tree delete that still exited 0.
    """
    (tmp_path / "app.py").write_text("def hello():\n    return 1\n", encoding="utf-8")
    precious = tmp_path / "precious.py"
    precious.write_text("def keep_me():\n    return 42\n", encoding="utf-8")
    index = tmp_path / "index.json"
    index.write_text(
        json.dumps(
            {
                "schema": 2,
                "units": [],
                "vector_store": {"path": "precious.py", "dimensions": 384, "dtype": "float32-le", "count": 0},
            }
        ),
        encoding="utf-8",
    )
    write_index(index, tmp_path, build_units(tmp_path), compact=True)
    assert precious.exists()
    assert precious.read_text(encoding="utf-8").startswith("def keep_me")


def test_orphaned_vector_sidecars_are_reclaimed(tmp_path: Path):
    """An unreadable or absent index.json used to leak its sidecar forever."""
    (tmp_path / "x.py").write_text("def run():\n    return 1\n", encoding="utf-8")
    index = tmp_path / "index.json"
    orphan = index.parent / "index.deadbeef.0123456789abcdef.vectors.bin"
    orphan.write_bytes(bytes(16))
    write_index(index, tmp_path, build_units(tmp_path), compact=True)
    assert not orphan.exists()
    assert len(list(index.parent.glob("index.*.vectors.bin"))) == 1
