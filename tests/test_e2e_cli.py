from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def run_cli(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-m", "ragyourcode.cli", *args], cwd=cwd, capture_output=True, text=True, check=True)


def test_cli_index_search_annotate_and_stale_detection(tmp_path: Path):
    source = tmp_path / "worker.py"
    source.write_text("def process_queue(queue):\n    return queue.consume()\n", encoding="utf-8")

    indexed = json.loads(run_cli("index", str(tmp_path), cwd=Path.cwd()).stdout)
    assert indexed["indexed_units"] == 1

    searched = json.loads(run_cli("search", "consume queue", "--root", str(tmp_path), "--json", cwd=Path.cwd()).stdout)
    assert searched["stale"] is False
    assert searched["results"][0]["unit"]["name"] == "process_queue"

    annotated = json.loads(run_cli("annotate", "--root", str(tmp_path), cwd=Path.cwd()).stdout)
    annotation_text = Path(annotated["output"]).read_text(encoding="utf-8")
    assert "RAG[00001]" in annotation_text
    assert source.read_text(encoding="utf-8").startswith("def process_queue")

    source.write_text("def process_queue(queue):\n    return queue.consume(10)\n", encoding="utf-8")
    stale = json.loads(run_cli("search", "consume queue", "--root", str(tmp_path), "--json", cwd=Path.cwd()).stdout)
    assert stale["stale"] is True

    stale_annotation = subprocess.run(
        [sys.executable, "-m", "ragyourcode.cli", "annotate", "--root", str(tmp_path)],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
    )
    assert stale_annotation.returncode == 2
    assert "Index is stale" in stale_annotation.stderr


def test_search_without_index_is_a_concise_error(tmp_path: Path):
    proc = subprocess.run(
        [sys.executable, "-m", "ragyourcode.cli", "search", "anything", "--root", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2
    assert proc.stderr.startswith("error:")
    assert "Traceback" not in proc.stderr
