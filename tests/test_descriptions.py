"""Contracts for agent-authored descriptions.

The feature exists for one measurable reason and is guarded by it here: the
embedder is a feature hash, so a query sharing no token with a unit scores
exactly zero against it, and the generated description introduces no vocabulary
the source did not already contain. Everything else in this file protects the
guarantee that makes that safe -- a description is never applied to code it was
not written about.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

from ragyourcode import descriptions as descriptions_module
from ragyourcode.cli import build_parser, main
from ragyourcode.descriptions import DescriptionStore, source_key
from ragyourcode.indexer import build_units, read_index

AUTHORED = (
    "Retries a failed payment charge after the upstream gateway times out, using exponential "
    "backoff with a bounded number of attempts. Idempotent: a retry never double-bills. "
    "中文：支付网关超时后按指数退避重新发起扣款，幂等，不会重复扣费。"
)
SOURCE = (
    "def retry_charge(gateway, invoice_id, max_attempts=3):\n"
    '    """Retry a failed card charge after a gateway timeout."""\n'
    "    for attempt in range(max_attempts):\n"
    "        try:\n"
    "            return gateway.charge(invoice_id)\n"
    "        except TimeoutError:\n"
    "            continue\n"
    "    raise ChargeFailed(invoice_id)\n"
)
UNIT_ID = "billing.py:1:retry_charge"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "billing.py").write_text(SOURCE, encoding="utf-8")
    return tmp_path


def _search(root: Path, query: str, capsys) -> list[dict]:
    assert main(["search", query, "--root", str(root), "--json"]) == 0
    return json.loads(capsys.readouterr().out)["results"]


def _write_store(root: Path, unit_id: str, text: str, digest: str) -> None:
    payload = {"schema": 1, "descriptions": {unit_id: {"hash": digest, "path": "billing.py", "text": text}}}
    (root / descriptions_module.STORE_FILENAME).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _serve(root: Path, requests: list[dict], capsys, monkeypatch) -> list[dict]:
    stdin = io.StringIO("".join(json.dumps(request, ensure_ascii=False) + "\n" for request in requests))
    monkeypatch.setattr(sys, "stdin", stdin)
    args = build_parser().parse_args(["agent", "--root", str(root)])
    assert args.func(args) == 0
    return [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]


# --- the reason the feature exists -----------------------------------------


@pytest.mark.parametrize("query", ["exponential backoff", "double billing", "支付网关超时"])
def test_an_authored_description_reaches_queries_the_generated_one_cannot(repo, capsys, query):
    """Each query shares no token with the source or the generated sentence.

    The measure is lexical evidence, not whether anything came back: with no
    overlap anywhere, `search` deliberately falls back to pure cosine so a
    paraphrase still retrieves something, and on a small corpus that fallback
    returns the unit with an empty `matched_terms` and a score near zero. The
    contract being tested is that the query goes from no evidence to real
    evidence.

    The Chinese case is why descriptions are bilingual by default: the
    tokenizer emits CJK bigrams, so a Chinese query can only ever match a unit
    whose indexed text contains Chinese.
    """
    assert main(["index", str(repo)]) == 0
    capsys.readouterr()
    before = _search(repo, query, capsys)
    assert all(not result["matched_terms"] for result in before)
    assert all(result["score"] < 0.05 for result in before)

    units = build_units(repo)
    _write_store(repo, UNIT_ID, AUTHORED, source_key(units[0]))
    assert main(["index", str(repo)]) == 0
    capsys.readouterr()

    after = _search(repo, query, capsys)
    assert after and after[0]["unit"]["id"] == UNIT_ID
    assert after[0]["matched_terms"], "the match must rest on shared words, not the cosine fallback"
    assert after[0]["score"] > 0.3


def test_the_authored_text_replaces_the_description_that_is_served(repo, capsys):
    units = build_units(repo)
    _write_store(repo, UNIT_ID, AUTHORED, source_key(units[0]))
    assert main(["index", str(repo)]) == 0
    capsys.readouterr()
    _, indexed = read_index(repo / ".rag-your-code" / "index.json")
    assert indexed[0].description == AUTHORED


# --- a description is never applied to code it does not describe ------------


def test_a_source_change_supersedes_the_description(repo, capsys):
    units = build_units(repo)
    _write_store(repo, UNIT_ID, AUTHORED, source_key(units[0]))
    assert main(["index", str(repo)]) == 0
    capsys.readouterr()
    assert _search(repo, "exponential backoff", capsys)

    (repo / "billing.py").write_text(SOURCE.replace("max_attempts=3", "max_attempts=5"), encoding="utf-8")
    assert main(["index", str(repo)]) == 0
    capsys.readouterr()

    assert _search(repo, "exponential backoff", capsys) == [], "stale text must not survive the code it described"
    _, indexed = read_index(repo / ".rag-your-code" / "index.json")
    assert indexed[0].description != AUTHORED

    assert main(["describe", "status", "--root", str(repo)]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["described"] == 0 and status["superseded"] == 1
    # The entry stays on disk so a re-describe can see what was there before.
    assert descriptions_module.load(repo).entries[UNIT_ID]["text"] == AUTHORED


def test_a_description_survives_the_code_moving_down_the_file(repo, capsys):
    """An edit above a declaration changes its id but not its code.

    Unit ids embed the line a declaration starts on, so inserting a comment or
    an import near the top of a file gives every declaration below it a new id
    while changing none of them. Keyed on id alone, every description in that
    file is orphaned by an edit that touched nothing they describe -- which is
    what a seven-line comment added to this project's own config.py did to
    nineteen of them.
    """
    units = build_units(repo)
    _write_store(repo, UNIT_ID, AUTHORED, source_key(units[0]))
    assert main(["index", str(repo)]) == 0
    capsys.readouterr()
    assert _search(repo, "exponential backoff", capsys), "precondition: the description applies"

    (repo / "billing.py").write_text("# a comment nobody asked about\n\n" + SOURCE, encoding="utf-8")
    assert main(["index", str(repo)]) == 0
    capsys.readouterr()

    _, indexed = read_index(repo / ".rag-your-code" / "index.json")
    assert indexed[0].id != UNIT_ID, "precondition: the id really did change"
    assert indexed[0].description == AUTHORED, "the code is byte-identical; the description must follow it"
    assert _search(repo, "exponential backoff", capsys)

    assert main(["describe", "status", "--root", str(repo)]) == 0
    assert json.loads(capsys.readouterr().out)["described"] == 1


def test_relocation_never_guesses_between_identical_declarations(repo, capsys):
    """Two byte-identical declarations in one file resolve to nothing.

    The relocation lookup is keyed on file and code digest. When one file holds
    two declarations with identical source and different stored text, there is
    no way to tell which description belongs where, so neither is applied.
    """
    body = "def alpha():\n    return 1\n\n\ndef beta():\n    return 1\n"
    (repo / "twins.py").write_text(body, encoding="utf-8")
    units = [unit for unit in build_units(repo) if unit.path == "twins.py"]
    assert len(units) == 2 and source_key(units[0]) != source_key(units[1]), "the sources differ by name"

    store = descriptions_module.load(repo)
    for unit, text in zip(units, ("first description", "second description")):
        store.put(unit, text)
    # Force the ambiguity the guard exists for: same file, same digest, two texts.
    for entry, text in zip(store.entries.values(), ("first description", "second description")):
        entry["hash"] = "identical-digest"
        entry["text"] = text
    store.entries = {f"twins.py:99:{name}": entry for name, entry in zip(("alpha", "beta"), store.entries.values())}
    assert store._relocations()[("twins.py", "identical-digest")] is None


def test_a_mismatched_digest_is_not_applied(repo):
    _write_store(repo, UNIT_ID, AUTHORED, "0" * 16)
    units = build_units(repo, descriptions=descriptions_module.load(repo))
    assert units[0].description != AUTHORED


def test_a_malformed_store_costs_quality_not_availability(repo, capsys):
    (repo / descriptions_module.STORE_FILENAME).write_text("{ not json", encoding="utf-8")
    assert descriptions_module.load(repo).entries == {}
    assert main(["index", str(repo)]) == 0
    capsys.readouterr()
    assert _search(repo, "retry charge", capsys)


def test_saving_prunes_entries_for_units_that_no_longer_exist(repo):
    units = build_units(repo)
    store = descriptions_module.load(repo)
    store.put(units[0], AUTHORED)
    store.entries["gone.py:1:removed"] = {"hash": "x", "text": "y"}
    store.save(units)
    assert set(descriptions_module.load(repo).entries) == {UNIT_ID}


def test_saving_without_a_unit_list_prunes_nothing(repo):
    """A partial list would silently discard the descriptions it omitted."""
    units = build_units(repo)
    store = descriptions_module.load(repo)
    store.put(units[0], AUTHORED)
    store.entries["gone.py:1:removed"] = {"hash": "x", "text": "y"}
    store.save()
    assert set(descriptions_module.load(repo).entries) == {UNIT_ID, "gone.py:1:removed"}


# --- the fingerprint, and the migration it has to survive -------------------


def test_importing_descriptions_alone_makes_the_index_stale(repo, capsys):
    assert main(["index", str(repo)]) == 0
    capsys.readouterr()
    units = build_units(repo)
    # No source file is touched, so nothing the file fingerprint tracks moves.
    _write_store(repo, UNIT_ID, AUTHORED, source_key(units[0]))
    assert main(["search", "retry", "--root", str(repo), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["stale"] is True


def test_an_index_predating_the_feature_is_not_reported_stale(repo, capsys):
    """A missing `descriptions_fingerprint` means "no descriptions", not "unknown".

    Read as unknown, every index written before 0.4.0 would report itself
    permanently stale over descriptions the repository does not have.
    """
    assert main(["index", str(repo)]) == 0
    capsys.readouterr()
    index_path = repo / ".rag-your-code" / "index.json"
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    del payload["descriptions_fingerprint"]
    index_path.write_text(json.dumps(payload), encoding="utf-8")

    assert main(["search", "retry", "--root", str(repo), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["stale"] is False


def test_an_empty_store_and_an_absent_one_agree(tmp_path):
    assert DescriptionStore(tmp_path / "s.json", {}).fingerprint == ""
    assert descriptions_module.load(tmp_path).fingerprint == ""


# --- the write path validates instead of truncating -------------------------


def test_describe_put_reports_every_rejection(repo, capsys, monkeypatch):
    assert main(["index", str(repo)]) == 0
    capsys.readouterr()
    replies = _serve(
        repo,
        [{
            "action": "describe_put",
            "descriptions": [
                {"id": "does.py:1:not_exist", "text": "x"},
                {"id": UNIT_ID, "text": "   "},
                {"id": UNIT_ID, "text": "y" * 5000},
                "not an object",
            ],
        }],
        capsys,
        monkeypatch,
    )
    reasons = [item["reason"] for item in replies[0]["rejected"]]
    assert reasons == ["unknown_unit", "empty", "too_long", "not_an_object"]
    assert replies[0]["stored"] == 0
    assert not (repo / descriptions_module.STORE_FILENAME).exists(), "a batch that stored nothing must not write"


def test_a_stored_description_takes_effect_within_the_same_session(repo, capsys, monkeypatch):
    assert main(["index", str(repo)]) == 0
    capsys.readouterr()
    replies = _serve(
        repo,
        [
            {"action": "search", "query": "exponential backoff"},
            {"action": "describe_pending", "limit": 5},
            {"action": "describe_put", "descriptions": [{"id": UNIT_ID, "text": AUTHORED}]},
            {"action": "search", "query": "exponential backoff"},
            {"action": "stats"},
        ],
        capsys,
        monkeypatch,
    )
    assert replies[0]["results"] == []
    assert [unit["id"] for unit in replies[1]["units"]] == [UNIT_ID]
    assert replies[1]["languages"] == ["en", "zh"] and replies[1]["guidance"]
    assert replies[2]["stored"] == 1 and replies[2]["applied"] == 1
    assert replies[2]["reindex_required"] is True
    assert replies[3]["results"], "the live units must serve the new text without a refresh"
    assert replies[3]["results"][0]["unit"]["id"] == UNIT_ID
    # The published index is behind the store; `stale` answers a different
    # question -- whether the index still describes the repository -- and is
    # correctly False here.
    assert replies[4]["index_behind"] is True and replies[4]["stale"] is False


def test_pending_offers_undescribed_units_before_superseded_ones(tmp_path):
    (tmp_path / "billing.py").write_text(SOURCE, encoding="utf-8")
    (tmp_path / "other.py").write_text("def helper():\n    return 2\n", encoding="utf-8")
    units = build_units(tmp_path)
    store = DescriptionStore(tmp_path / "s.json", {})
    described = next(unit for unit in units if unit.id == UNIT_ID)
    store.put(described, AUTHORED)
    store.entries[UNIT_ID]["hash"] = "0" * 16  # now superseded

    pending = store.pending(units, limit=5)
    assert [unit.id for unit in pending][0] != UNIT_ID, "a unit with no description at all comes first"
    assert {unit.id for unit in pending} == {unit.id for unit in units}


def test_describe_export_and_import_round_trip(tmp_path, capsys):
    (tmp_path / "billing.py").write_text(SOURCE, encoding="utf-8")
    assert main(["index", str(tmp_path)]) == 0
    capsys.readouterr()

    batch_path = tmp_path / "batch.json"
    assert main(["describe", "export", "--root", str(tmp_path), "--output", str(batch_path)]) == 0
    capsys.readouterr()
    batch = json.loads(batch_path.read_text(encoding="utf-8"))
    assert batch["units"][0]["source"] == SOURCE.rstrip("\n")

    written = tmp_path / "written.json"
    written.write_text(json.dumps({"descriptions": [{"id": batch["units"][0]["id"], "text": AUTHORED}]}, ensure_ascii=False), encoding="utf-8")
    assert main(["describe", "import", str(written), "--root", str(tmp_path)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["stored"] == 1 and report["reindex_required"] is True and report["remaining"] == 0

    assert main(["describe", "status", "--root", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)["coverage"] == 1.0
