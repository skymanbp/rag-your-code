"""Guards for the JSON-lines daemon's failure contract.

The daemon serves one untrusted request per stdin line for the life of an agent
session. Its defining property is that no single request may end the session.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

from ragyourcode import cli
from ragyourcode.cli import build_parser, main


def _serve(tmp_path: Path, requests: list[dict], capsys, monkeypatch) -> list[dict]:
    """Run the agent loop in-process over a fixed request list."""
    main(["index", str(tmp_path)])
    capsys.readouterr()
    stdin = io.StringIO("".join(json.dumps(request) + "\n" for request in requests))
    monkeypatch.setattr(sys, "stdin", stdin)
    args = build_parser().parse_args(["agent", "--root", str(tmp_path)])
    assert args.func(args) == 0
    out = capsys.readouterr().out
    return [json.loads(line) for line in out.splitlines() if line.strip()]


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "a.py").write_text("def alpha():\n    return 1\n", encoding="utf-8")
    long_line = "    x = '" + "A" * 300_000 + "'\n"
    (tmp_path / "big.py").write_text("def beta():\n" + long_line + "    return 1\n", encoding="utf-8")
    return tmp_path


def test_non_finite_numeric_fields_saturate_instead_of_killing_the_daemon(repo, capsys, monkeypatch):
    """int(1e400) raises OverflowError, which is neither TypeError nor ValueError.

    It escaped the request loop's except clause and terminated the process, so
    every request after the offending one went unanswered.
    """
    replies = _serve(
        repo,
        [
            {"action": "search", "query": "alpha", "limit": 1e400},
            {"action": "search", "query": "alpha", "hops": -1e400, "graph": True},
            {"action": "stats"},
        ],
        capsys,
        monkeypatch,
    )
    assert len(replies) == 3, "the loop must answer every request, not die on the first"
    assert replies[0]["results"], "an infinite limit saturates at the maximum, it does not error"
    assert "units" in replies[2]


def test_a_string_where_a_number_belongs_is_still_invalid_request(repo, capsys, monkeypatch):
    """The pre-existing error code is part of the protocol and must not drift."""
    replies = _serve(repo, [{"action": "search", "query": "a", "limit": "bad"}, {"action": "stats"}], capsys, monkeypatch)
    assert replies[0]["error"] == "invalid_request"
    assert "units" in replies[1]


def test_an_unanticipated_handler_error_is_reported_and_the_loop_continues(repo, capsys, monkeypatch):
    """The catch-all is a structural guarantee, not a list of remembered types.

    RecursionError is neither TypeError nor ValueError, so before the catch-all
    it would have propagated out of the loop and ended the session.
    """
    def explode(*args, **kwargs):
        raise RecursionError("simulated unanticipated failure")

    monkeypatch.setattr(cli, "search", explode)
    replies = _serve(repo, [{"action": "search", "query": "alpha"}, {"action": "stats"}], capsys, monkeypatch)
    assert replies[0]["error"] == "request_failed"
    assert replies[0]["type"] == "RecursionError"
    assert "simulated unanticipated failure" in replies[0]["message"]
    assert "units" in replies[1], "the session survives and serves the next request"


def test_open_bounds_output_by_size_not_only_line_count(repo, capsys, monkeypatch):
    """A line count is not a size: three lines held 300 KB on one of them."""
    replies = _serve(repo, [{"action": "open", "path": "big.py"}], capsys, monkeypatch)
    assert replies[0]["truncated"] is True
    assert len(replies[0]["source"]) == cli.MAX_OPEN_CHARS
    assert replies[0]["end_line"] == 3


def test_open_still_refuses_paths_outside_the_repository(repo, capsys, monkeypatch):
    replies = _serve(repo, [{"action": "open", "path": "../escape.py"}], capsys, monkeypatch)
    assert replies[0]["error"] == "path_outside_root"
