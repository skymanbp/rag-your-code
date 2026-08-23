from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"


def cli_env(**overrides: str) -> dict[str, str]:
    """Environment that runs the working tree, not whatever pip has installed.

    Without this the subprocess imports ``ragyourcode`` from site-packages, so a
    stale installed copy would decide whether these tests pass.
    """
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(SRC), env.get("PYTHONPATH", "")]).rstrip(os.pathsep)
    env.update(overrides)
    return env


def run_cli(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-m", "ragyourcode.cli", *args], cwd=cwd, capture_output=True, text=True, check=True, env=cli_env())


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


SAMPLE_WITH_NON_ASCII = '''def 重试请求(url):
    "重试失败的 HTTP 请求 🚀 with backoff."
    return url
'''


def test_agent_survives_non_ascii_on_a_non_utf8_console(tmp_path: Path):
    """The protocol is UTF-8; the OS codepage must not get a vote.

    ``PYTHONIOENCODING`` simulates a non-UTF-8 console (cp936 on this project's
    development machine) deterministically on every platform. Before the streams
    were pinned, printing a response holding a character outside that codepage
    raised UnicodeEncodeError and killed the long-lived subprocess, and a UTF-8
    request line was mis-decoded into mojibake that matched nothing.
    """
    (tmp_path / "m.py").write_text(SAMPLE_WITH_NON_ASCII, encoding="utf-8")
    env = cli_env(PYTHONIOENCODING="cp1252")
    env.pop("PYTHONUTF8", None)

    indexed = subprocess.run(
        [sys.executable, "-m", "ragyourcode.cli", "index", str(tmp_path)],
        capture_output=True, env=env, check=True,
    )
    assert json.loads(indexed.stdout.decode("utf-8"))["indexed_units"] == 1

    requests = (
        json.dumps({"action": "search", "query": "重试 HTTP 请求", "limit": 3}, ensure_ascii=False) + "\n"
        + json.dumps({"action": "stats"}) + "\n"
    ).encode("utf-8")
    agent = subprocess.run(
        [sys.executable, "-m", "ragyourcode.cli", "agent", "--root", str(tmp_path)],
        input=requests, capture_output=True, env=env,
    )
    assert agent.returncode == 0, agent.stderr.decode("utf-8", "replace")
    lines = [line for line in agent.stdout.decode("utf-8").splitlines() if line.strip()]
    assert len(lines) == 2, "the subprocess must answer both requests, not die on the first"
    assert [hit["unit"]["name"] for hit in json.loads(lines[0])["results"]] == ["重试请求"]
    assert "🚀" in lines[0]
