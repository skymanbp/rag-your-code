"""Documentation written above a declaration is indexed, and only that.

Fourteen of the fifteen supported languages put documentation immediately above
a declaration rather than inside its body, and a unit's span begins at the
declaration -- so every JSDoc, Javadoc, KDoc, rustdoc and Go doc comment sat
outside the indexed text entirely. The same sentence reached thirteen
searchable words as a Python docstring and two as a JavaScript comment.

The other half of the contract is what must *not* be picked up: a licence
header, code somebody commented out, a row of dashes. Retrieval over those
invents vocabulary the author disowned, which is worse than missing a line.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ragyourcode.cli import main
from ragyourcode.embeddings import tokenize
from ragyourcode.indexer import build_units, read_index
from ragyourcode.parser import PARSER_FINGERPRINT, parse_file

DOC_TEXT = (
    "Retries a failed payment charge after the upstream gateway times out,\n"
    "using exponential backoff. Idempotent: a retry never double-bills."
)
DOC_WORDS = {
    "retries", "failed", "payment", "charge", "upstream", "gateway", "times",
    "exponential", "backoff", "idempotent", "retry", "never", "double", "bills",
}


def _documented(unit) -> str:
    parts = unit.description.split("Documented intent: ", 1)
    return parts[1] if len(parts) > 1 else ""


def _reachable(unit) -> set[str]:
    return DOC_WORDS & set(tokenize(unit.searchable_text))


@pytest.mark.parametrize(
    "name,body",
    [
        ("billing.js", "/**\n * {doc}\n */\nexport function retryCharge(gateway, invoiceId) {{\n  return 1;\n}}\n"),
        ("billing.ts", "/**\n * {doc}\n */\nexport function retryCharge(gateway: string): number {{\n  return 1;\n}}\n"),
        ("billing.go", "// {doc}\nfunc RetryCharge(gateway string) int {{\n\treturn 1\n}}\n"),
        ("billing.rs", "/// {doc}\npub fn retry_charge(gateway: &str) -> u32 {{\n    1\n}}\n"),
        ("Billing.java", "/**\n * {doc}\n */\npublic int retryCharge(String gateway) {{\n    return 1;\n}}\n"),
        ("billing.rb", "# {doc}\ndef retry_charge(gateway)\n  1\nend\n"),
        ("billing.sh", "# {doc}\nretry_charge() {{\n  return 1\n}}\n"),
    ],
)
def test_documentation_above_a_declaration_becomes_searchable(tmp_path, name, body):
    """Every language family puts it in a different place; all of them count."""
    lines = DOC_TEXT.splitlines()
    prefix = body.split("{doc}")[0].splitlines()[-1] if "{doc}" in body else ""
    rendered = body.format(doc=("\n" + prefix).join(lines))
    (tmp_path / name).write_text(rendered, encoding="utf-8")
    units = parse_file(tmp_path / name, tmp_path)
    assert units, f"{name}: nothing parsed"
    assert _documented(units[0]), f"{name}: the comment above the declaration was dropped"
    reached = _reachable(units[0])
    assert len(reached) >= 10, f"{name}: only {sorted(reached)} of the documentation is searchable"


def test_a_python_docstring_and_a_doc_comment_reach_the_same_words(tmp_path):
    """The measurement that motivated this: thirteen words against two."""
    (tmp_path / "a.py").write_text(
        f'def retry_charge(gateway):\n    """{DOC_TEXT}"""\n    return 1\n', encoding="utf-8"
    )
    (tmp_path / "a.js").write_text(
        "/**\n * " + DOC_TEXT.replace("\n", "\n * ") + "\n */\nexport function retryCharge(gateway) {\n  return 1;\n}\n",
        encoding="utf-8",
    )
    python_words = _reachable(parse_file(tmp_path / "a.py", tmp_path)[0])
    javascript_words = _reachable(parse_file(tmp_path / "a.js", tmp_path)[0])
    assert javascript_words == python_words


# --- and only that ----------------------------------------------------------


def test_a_licence_header_is_not_read_as_documentation(tmp_path):
    """A blank line separates a file header from the first declaration."""
    (tmp_path / "a.js").write_text(
        "// Copyright 2026 Somebody Incorporated\n"
        "// Licensed under the Apache License, Version 2.0\n"
        "\n"
        "export function charge(invoiceId) {\n  return 1;\n}\n",
        encoding="utf-8",
    )
    unit = parse_file(tmp_path / "a.js", tmp_path)[0]
    assert not _documented(unit)
    assert "apache" not in set(tokenize(unit.searchable_text))


def test_commented_out_code_is_not_read_as_documentation(tmp_path):
    (tmp_path / "a.js").write_text(
        "// const legacyCharge = (id) => {\n"
        "//   return oldGateway.bill(id);\n"
        "// };\n"
        "// ----------------------------------\n"
        "// Charges one invoice.\n"
        "export function charge(invoiceId) {\n  return 1;\n}\n",
        encoding="utf-8",
    )
    documented = _documented(parse_file(tmp_path / "a.js", tmp_path)[0])
    assert "Charges one invoice." in documented
    assert "oldGateway" not in documented and "legacyCharge" not in documented
    assert "---" not in documented


def test_prose_wrapping_on_a_comma_survives(tmp_path):
    """A comma once counted as a code ending and ate the first line of a block.

    Prose wraps on a comma far more often than code ends on one, which the
    measurement showed by dropping five of thirteen documentation words.
    """
    (tmp_path / "a.js").write_text(
        "/**\n"
        " * Retries a failed payment charge after the upstream gateway times out,\n"
        " * using exponential backoff.\n"
        " */\n"
        "export function retryCharge(gateway) {\n  return 1;\n}\n",
        encoding="utf-8",
    )
    documented = _documented(parse_file(tmp_path / "a.js", tmp_path)[0])
    assert documented.startswith("Retries a failed payment charge")


def test_an_annotation_does_not_hide_the_block_above_it(tmp_path):
    """`@Override` between Javadoc and its method is the normal Java shape."""
    (tmp_path / "A.java").write_text(
        "/**\n * Charges one invoice through the payment gateway.\n */\n"
        "@Override\n"
        "public int charge(String invoiceId) {\n    return 1;\n}\n",
        encoding="utf-8",
    )
    documented = _documented(parse_file(tmp_path / "A.java", tmp_path)[0])
    assert "payment gateway" in documented


def test_a_block_is_bounded(tmp_path):
    """A very long comment cannot flood one unit's indexed text."""
    from ragyourcode.parser import DOC_MAX_CHARS

    filler = "\n".join(f"// paragraph number {n} explaining something at length" for n in range(60))
    (tmp_path / "a.js").write_text(filler + "\nexport function charge(id) {\n  return 1;\n}\n", encoding="utf-8")
    assert len(_documented(parse_file(tmp_path / "a.js", tmp_path)[0])) <= DOC_MAX_CHARS


# --- the parser is an input to the index, and the index now records it -------


def test_upgrading_the_parser_invalidates_reuse(tmp_path, capsys, monkeypatch):
    """Cached units are a function of the bytes *and* of the code that parsed them.

    Reuse was keyed on the bytes alone, so a parser change reached no existing
    index until the file itself happened to change.
    """
    (tmp_path / "a.js").write_text("export function charge(id) {\n  return 1;\n}\n", encoding="utf-8")
    assert main(["index", str(tmp_path)]) == 0
    capsys.readouterr()
    assert main(["index", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)["incremental"] is True

    monkeypatch.setattr("ragyourcode.indexer.PARSER_FINGERPRINT", "a-different-parser")
    assert main(["index", str(tmp_path)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["rebuilt_for_inputs"] is True
    assert report["incremental"] is False


def test_the_fingerprint_is_derived_from_the_module_not_declared():
    """A hand-maintained version number is a claim nobody checks."""
    assert PARSER_FINGERPRINT and not PARSER_FINGERPRINT.startswith("declared-")
    assert len(PARSER_FINGERPRINT) == 16


def test_an_index_predating_the_field_rebuilds_once(tmp_path, capsys):
    """Missing means 'built by something else', which is what a rebuild is for."""
    (tmp_path / "a.py").write_text("def charge(amount):\n    return amount\n", encoding="utf-8")
    assert main(["index", str(tmp_path)]) == 0
    capsys.readouterr()
    index_path = tmp_path / ".rag-your-code" / "index.json"
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    del payload["build_fingerprint"]
    index_path.write_text(json.dumps(payload), encoding="utf-8")

    assert main(["index", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)["rebuilt_for_inputs"] is True


def test_doc_comments_do_not_disturb_the_python_path(tmp_path):
    """Python keeps its docstring route; nothing is harvested twice."""
    (tmp_path / "a.py").write_text(
        '# a note to the reader\ndef charge(amount):\n    """Charges an amount."""\n    return amount\n',
        encoding="utf-8",
    )
    unit = build_units(tmp_path)[0]
    assert "Documented intent: Charges an amount." in unit.description
    assert "note to the reader" not in unit.description


def test_the_index_records_which_parser_built_it(tmp_path, capsys):
    (tmp_path / "a.py").write_text("def charge(amount):\n    return amount\n", encoding="utf-8")
    assert main(["index", str(tmp_path)]) == 0
    capsys.readouterr()
    payload, _ = read_index(tmp_path / ".rag-your-code" / "index.json")
    assert payload["build_fingerprint"]
    assert "config_fingerprint" not in payload, "the two fingerprints were merged into one"
