"""Guards for the three retrieval-correctness root causes fixed in P4.

E: the vector-candidate set replaced the lexical candidate set, so units
   matching MORE query terms went unscored and `limit` came back under-filled.
F: parsing and publication walked the tree separately, so a save landing
   between them recorded a fresh hash beside stale units, permanently.
G: calls resolved by bare leaf name, fabricating edges into the standard
   library while this module promised unresolved calls were omitted.
"""

from __future__ import annotations

from pathlib import Path

from ragyourcode.graph import build_graph
from ragyourcode.indexer import build_units, fingerprint, read_index, snapshot_repository, write_index
from ragyourcode.search import build_search_index, search


def _corpus(tmp_path: Path, count: int = 80) -> Path:
    """More units than the selective threshold's 64 floor, with skewed terms."""
    for index in range(count):
        (tmp_path / f"mod_{index}.py").write_text(
            f"def handler_{index}(request, response):\n"
            f'    """Handle request and return response."""\n'
            f"    return response\n",
            encoding="utf-8",
        )
    (tmp_path / "special.py").write_text(
        "def retry_request_with_backoff(request, response):\n"
        '    """Retry a failed request and return response."""\n'
        "    return response\n",
        encoding="utf-8",
    )
    return tmp_path


def test_limit_is_filled_when_a_rare_term_joins_common_ones(tmp_path: Path):
    """A rare token must not shrink the candidate set to itself.

    `backoff` reaches one unit; `request` and `response` reach all 81. Scoring
    only what the rare term reached returned a single result for `--limit 8`.
    """
    units = build_units(_corpus(tmp_path))
    assert len(units) > 64, "the corpus must exceed the selective threshold's floor"
    index = build_search_index(units)
    results = search(units, "backoff request response", limit=8, search_index=index)
    assert len(results) == 8, f"limit 8 must be filled, got {len(results)}"
    assert results[0].unit.name == "retry_request_with_backoff", "the rare term still wins the top slot"
    assert all(result.matched_terms for result in results), "every returned unit must carry its evidence"


def test_every_lexically_matching_unit_can_be_returned(tmp_path: Path):
    units = build_units(_corpus(tmp_path, count=70))
    index = build_search_index(units)
    results = search(units, "handler_7 request", limit=100, search_index=index)
    returned = {result.unit.id for result in results}
    matching = {unit.id for unit in units if "request" in unit.searchable_text}
    assert matching <= returned, f"{len(matching - returned)} lexically matching units were never scored"


def test_a_write_between_parse_and_publish_leaves_the_index_self_reporting_stale(tmp_path: Path):
    """The index may lag reality; it may never lie about lagging.

    Publishing hashes from a second walk recorded the new hash beside units
    parsed from the old content, so `fingerprint` matched and every later
    incremental run reused the stale units forever.
    """
    source = tmp_path / "svc.py"
    source.write_text("def charge(amount):\n    return amount\n", encoding="utf-8")
    index = tmp_path / "index.json"

    snapshot = snapshot_repository(tmp_path)
    units = build_units(tmp_path, snapshot=snapshot)
    source.write_text("def charge(amount):\n    return amount * 2\n", encoding="utf-8")
    write_index(index, tmp_path, units, build_graph(units).to_dict(), snapshot=snapshot)

    payload, loaded = read_index(index)
    assert payload["fingerprint"] != fingerprint(tmp_path), "the index must not claim to describe the new bytes"
    rebuilt = build_units(tmp_path, previous_units=loaded, previous_files=payload["files"])
    assert "amount * 2" in rebuilt[0].source, "the next incremental run must re-parse, not reuse"


def test_a_foreign_module_call_produces_no_edge(tmp_path: Path):
    """`os.path.join` must not reach a local `join`; the module promises omission."""
    (tmp_path / "strutil.py").write_text("def join(parts, sep):\n    return sep.join(parts)\n", encoding="utf-8")
    (tmp_path / "loader.py").write_text(
        "import os\n\ndef load_config(root, name):\n    return os.path.join(root, name)\n", encoding="utf-8"
    )
    graph = build_graph(build_units(tmp_path))
    assert [edge for edge in graph.edges if edge.kind == "calls"] == []


def test_a_local_module_call_still_resolves(tmp_path: Path):
    (tmp_path / "strutil.py").write_text("def join(parts, sep):\n    return sep.join(parts)\n", encoding="utf-8")
    (tmp_path / "loader.py").write_text(
        "import strutil\n\ndef load_config(root, name):\n    return strutil.join([root, name], '/')\n", encoding="utf-8"
    )
    graph = build_graph(build_units(tmp_path))
    calls = [edge for edge in graph.edges if edge.kind == "calls"]
    assert [(edge.source.split(":")[0], edge.target.split(":")[0], edge.label) for edge in calls] == [
        ("loader.py", "strutil.py", "strutil.join")
    ]


def test_a_receiver_call_still_resolves_within_its_file(tmp_path: Path):
    (tmp_path / "svc.py").write_text(
        "class Svc:\n    def helper(self):\n        return 1\n\n    def run(self):\n        return self.helper()\n",
        encoding="utf-8",
    )
    graph = build_graph(build_units(tmp_path))
    labels = {(edge.source.rsplit(":", 1)[-1], edge.target.rsplit(":", 1)[-1]) for edge in graph.edges if edge.kind == "calls"}
    assert ("Svc.run", "Svc.helper") in labels
