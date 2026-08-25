"""Guards for the rung report an unfamiliar repository gets on first contact.

Indexing a repository is not the same as making it searchable. A fresh index
retrieves against the sentence the parser generated, which adds no word the
source did not already have, and nothing used to say so: whoever ran `index`
had to know it, find `describe` in the documentation, and work out how many
rounds it would take.

The size of that gap is not quoted here. It is asserted, in
`tests/test_repo_queries.py::test_written_descriptions_beat_generated_ones`,
because a score falls whenever the repository gains code nobody has described
yet and a number in a docstring would rot the first time it did.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from ragyourcode import config as config_module
from ragyourcode import descriptions as descriptions_module
from ragyourcode.indexer import build_units
from ragyourcode.workflow import bootstrap, store_descriptions

INDEX_REPORT = {"indexed_units": 0, "graph_edges": 0}


def _report(root: Path, limit: int | None = None) -> dict:
    cfg = config_module.load(root)
    units = build_units(root, descriptions=descriptions_module.load(root))
    return bootstrap(units, descriptions_module.load(root), cfg, root, INDEX_REPORT, limit)


def _describe_everything(root: Path) -> None:
    cfg = config_module.load(root)
    store = descriptions_module.load(root)
    units = build_units(root)
    store_descriptions(
        units,
        store,
        cfg,
        [{"id": unit.id, "text": f"Written by hand about {unit.qualified_name}, in domain terms."} for unit in units],
    )


def test_an_undescribed_repository_is_told_to_describe(tmp_path: Path):
    (tmp_path / "billing.py").write_text("def charge(card):\n    return card\n", encoding="utf-8")
    report = _report(tmp_path)
    assert report["next"]["action"] == "describe"
    assert report["next"]["remaining"] == report["missing"] == 1
    assert report["batch"]["units"], "the rung that needs work must hand over that work"


def test_the_report_is_resumable_rather_than_remembered(tmp_path: Path):
    """It reads the state, so running it twice is not the same as running it once."""
    for index in range(4):
        (tmp_path / f"mod_{index}.py").write_text(f"def handler_{index}(job):\n    return job\n", encoding="utf-8")
    before = _report(tmp_path, limit=2)
    assert before["next"]["remaining"] == 4
    assert before["next"]["rounds_at_this_batch_size"] == 2

    cfg = config_module.load(tmp_path)
    store = descriptions_module.load(tmp_path)
    units = build_units(tmp_path)
    store_descriptions(units, store, cfg, [{"id": units[0].id, "text": "One written description, in domain terms."}])

    after = _report(tmp_path, limit=2)
    assert after["described"] == 1
    assert after["next"]["remaining"] == 3


def test_a_described_repository_is_told_to_promote(tmp_path: Path):
    """The last rung: text in the code needs none of the sidecar's bookkeeping."""
    (tmp_path / "billing.py").write_text("def charge(card):\n    return card\n", encoding="utf-8")
    _describe_everything(tmp_path)
    report = _report(tmp_path)
    assert report["next"]["action"] == "promote"
    assert report["next"]["insertions"] >= 1
    assert report["batch"] is None, "a rung with no work to hand over must not hand over a batch"


def test_a_repository_at_the_top_of_the_ladder_is_told_it_is_ready(tmp_path: Path):
    (tmp_path / "billing.py").write_text(
        'def charge(card):\n    """Take the money."""\n    return card\n',
        encoding="utf-8",
    )
    _describe_everything(tmp_path)
    report = _report(tmp_path)
    assert report["next"]["action"] == "ready"
    assert report["batch"] is None


def test_every_rung_says_why_and_how(tmp_path: Path):
    """A report that names a step without saying what it buys is a chore list."""
    (tmp_path / "billing.py").write_text("def charge(card):\n    return card\n", encoding="utf-8")
    for _ in range(2):
        report = _report(tmp_path)
        assert report["next"]["why"].strip()
        assert report["next"]["how"], report["next"]
        _describe_everything(tmp_path)


def test_the_command_line_and_the_protocol_report_the_same_rung(tmp_path: Path):
    """Two entry points, one implementation -- which is why it lives in workflow.py."""
    (tmp_path / "billing.py").write_text("def charge(card):\n    return card\n", encoding="utf-8")
    index = tmp_path / "index.json"
    env = {**dict(__import__("os").environ), "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"), "PYTHONIOENCODING": "utf-8"}

    command = subprocess.run(
        [sys.executable, "-m", "ragyourcode.cli", "bootstrap", str(tmp_path), "--output", str(index), "--json"],
        capture_output=True, text=True, encoding="utf-8", env=env,
    )
    assert command.returncode == 0, command.stderr
    from_cli = json.loads(command.stdout)

    protocol = subprocess.run(
        [sys.executable, "-m", "ragyourcode.cli", "agent", "--root", str(tmp_path), "--index", str(index)],
        input='{"action":"bootstrap"}\n', capture_output=True, text=True, encoding="utf-8", env=env,
    )
    assert protocol.returncode == 0, protocol.stderr
    from_protocol = json.loads(protocol.stdout.splitlines()[0])

    assert from_cli["next"]["action"] == from_protocol["next"]["action"]
    assert from_cli["missing"] == from_protocol["missing"]
    assert [unit["id"] for unit in from_cli["batch"]["units"]] == [unit["id"] for unit in from_protocol["batch"]["units"]]
