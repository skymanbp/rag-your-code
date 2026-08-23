from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from ragyourcode.indexer import build_units, read_index, write_index
from ragyourcode.search import search


def test_python_units_are_numbered_and_described(tmp_path: Path):
    source = tmp_path / "app.py"
    source.write_text(
        "import json\n\nclass Store:\n    def save(self, item):\n        return json.dumps(item)\n\nasync def fetch(url):\n    return url\n",
        encoding="utf-8",
    )
    units = build_units(tmp_path)
    assert [unit.serial for unit in units] == [1, 2, 3]
    assert units[1].qualified_name == "Store.save"
    assert "calls" in units[1].description
    assert units[1].start_line == 4
    assert units[1].vector


def test_index_round_trip_and_search(tmp_path: Path):
    (tmp_path / "service.py").write_text("def retry_request(client, url):\n    return client.get(url)\n", encoding="utf-8")
    units = build_units(tmp_path)
    index = tmp_path / "index.json"
    write_index(index, tmp_path, units)
    _, loaded = read_index(index)
    results = search(loaded, "retry request client", limit=1)
    assert results
    assert results[0].unit.name == "retry_request"
    assert results[0].unit.vector


def test_agent_json_lines_protocol(tmp_path: Path):
    (tmp_path / "math.py").write_text("def add(left, right):\n    return left + right\n", encoding="utf-8")
    subprocess.run([sys.executable, "-m", "ragyourcode.cli", "index", str(tmp_path)], check=True, capture_output=True, text=True)
    proc = subprocess.run(
        [sys.executable, "-m", "ragyourcode.cli", "agent", "--root", str(tmp_path)],
        input='{"action":"search","query":"add numbers"}\n{"action":"stats"}\n',
        check=True,
        capture_output=True,
        text=True,
    )
    lines = [json.loads(line) for line in proc.stdout.splitlines()]
    assert lines[0]["results"][0]["unit"]["name"] == "add"
    assert "vector" not in lines[0]["results"][0]["unit"]
    assert lines[1]["units"] == 1
    assert lines[1]["files"] == 1
    assert lines[1]["stale"] is False


def test_search_zero_limit_returns_no_results(tmp_path: Path):
    (tmp_path / "x.py").write_text("def useful():\n    return 1\n", encoding="utf-8")
    assert search(build_units(tmp_path), "useful", limit=0) == []


def test_chinese_subphrase_retrieval(tmp_path: Path):
    (tmp_path / "payment.py").write_text(
        "def retry_payment():\n    \"\"\"\u5904\u7406\u652f\u4ed8\u91cd\u8bd5\u903b\u8f91\u3002\"\"\"\n    return True\n",
        encoding="utf-8",
    )
    results = search(build_units(tmp_path), "\u652f\u4ed8\u91cd\u8bd5", limit=1)
    assert results[0].unit.name == "retry_payment"
    assert results[0].matched_terms


def test_agent_reports_bad_json_and_continues(tmp_path: Path):
    (tmp_path / "x.py").write_text("def useful():\n    return 1\n", encoding="utf-8")
    subprocess.run([sys.executable, "-m", "ragyourcode.cli", "index", str(tmp_path)], check=True, capture_output=True, text=True)
    proc = subprocess.run(
        [sys.executable, "-m", "ragyourcode.cli", "agent", "--root", str(tmp_path)],
        input="not-json\n[]\n{\"action\":\"search\",\"query\":\"x\",\"limit\":\"bad\"}\n{\"action\":\"stats\"}\n",
        check=True,
        capture_output=True,
        text=True,
    )
    lines = [json.loads(line) for line in proc.stdout.splitlines()]
    assert lines[0]["error"] == "invalid_json"
    assert lines[1]["error"] == "invalid_request"
    assert lines[2]["error"] == "invalid_request"
    assert lines[3]["units"] == 1


def test_running_agent_detects_source_changes(tmp_path: Path):
    source = tmp_path / "x.py"
    source.write_text("def useful():\n    return 1\n", encoding="utf-8")
    subprocess.run([sys.executable, "-m", "ragyourcode.cli", "index", str(tmp_path)], check=True, capture_output=True, text=True)
    proc = subprocess.Popen(
        [sys.executable, "-m", "ragyourcode.cli", "agent", "--root", str(tmp_path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    assert proc.stdin is not None and proc.stdout is not None
    proc.stdin.write('{"action":"stats"}\n')
    proc.stdin.flush()
    assert json.loads(proc.stdout.readline())["stale"] is False
    source.write_text("def useful():\n    return 2\n", encoding="utf-8")
    proc.stdin.write('{"action":"stats"}\n')
    proc.stdin.flush()
    assert json.loads(proc.stdout.readline())["stale"] is True
    proc.stdin.close()
    assert proc.wait(timeout=5) == 0
