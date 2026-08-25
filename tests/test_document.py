"""Promoting a stored description into the source, as a patch.

The store buys independence from the file with machinery: a digest, a
relocation lookup, a fingerprint, a pruning rule. All of it simulates a
property a docstring has for free. So the promotion exists, and it is offered
as a diff rather than performed, which keeps the project's guarantee that the
tool never writes source.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from ragyourcode import descriptions as descriptions_module
from ragyourcode.cli import main
from ragyourcode.document import DOC_STYLE, plan, render_patch, source_half
from ragyourcode.indexer import build_units
from ragyourcode.parser import EXTENSIONS

ENGLISH = "Retries a failed charge after the gateway times out, with bounded attempts."
BILINGUAL = ENGLISH + " 中文：支付网关超时后按指数退避重新发起扣款，尝试次数有上限。"


def _store(root: Path, units) -> descriptions_module.DescriptionStore:
    store = descriptions_module.load(root)
    for unit in units:
        store.put(unit, BILINGUAL)
    store.save(units)
    return descriptions_module.load(root)


# --- what goes into the source ---------------------------------------------


def test_only_the_half_meant_for_a_reader_is_promoted():
    assert source_half(BILINGUAL) == ENGLISH


def test_the_full_stop_survives():
    """An earlier trim removed a dangling label and ate every sentence's period."""
    assert source_half(BILINGUAL).endswith(".")
    assert source_half("Ends here. 中文：略。").endswith("here.")


def test_a_description_with_no_english_half_is_promoted_whole():
    chinese = "中文：这个函数只有中文描述。"
    assert source_half(chinese) == chinese


def test_every_supported_language_has_a_convention():
    """A language the parser reads but this cannot document is a silent gap."""
    languages = set(EXTENSIONS.values()) - {"python"}
    assert languages <= set(DOC_STYLE), f"no doc convention for {sorted(languages - set(DOC_STYLE))}"


# --- what it does, and does not, touch --------------------------------------


def test_python_gets_a_docstring_inside_the_body(tmp_path):
    (tmp_path / "a.py").write_text("def charge(amount):\n    return amount\n", encoding="utf-8")
    units = build_units(tmp_path)
    insertions = plan(units, _store(tmp_path, units), tmp_path)
    assert len(insertions) == 1
    assert insertions[0].line == 2, "a docstring goes before the first statement, not above the def"
    assert insertions[0].lines[0].startswith('    """')


def test_other_languages_get_a_comment_above_the_declaration(tmp_path):
    (tmp_path / "a.js").write_text("export function charge(id) {\n  return 1;\n}\n", encoding="utf-8")
    units = build_units(tmp_path)
    insertions = plan(units, _store(tmp_path, units), tmp_path)
    assert len(insertions) == 1
    assert insertions[0].line == 1
    assert insertions[0].lines[0] == "/**"
    assert insertions[0].lines[-1] == " */"


def test_an_already_documented_declaration_is_left_alone(tmp_path):
    """The author's words outrank an agent's, and are already indexed."""
    (tmp_path / "a.py").write_text('def charge(amount):\n    """Charges."""\n    return amount\n', encoding="utf-8")
    (tmp_path / "b.js").write_text("/** Charges. */\nexport function charge(id) {\n  return 1;\n}\n", encoding="utf-8")
    units = build_units(tmp_path)
    assert plan(units, _store(tmp_path, units), tmp_path) == []


def test_documented_is_asked_of_the_parser_not_of_the_applied_description(tmp_path):
    """An authored description replaces the generated sentence outright.

    Testing the applied description for the marker made a thoroughly
    documented function read as undocumented, and proposed a hundred and seven
    insertions where seventeen were due.
    """
    (tmp_path / "a.py").write_text('def charge(amount):\n    """Charges an amount."""\n    return amount\n', encoding="utf-8")
    bare = build_units(tmp_path)
    store = _store(tmp_path, bare)
    applied = build_units(tmp_path, descriptions=store)
    assert "Documented intent:" not in applied[0].description, "precondition: the marker is gone"
    assert plan(applied, store, tmp_path) == [], "it is documented; the marker's absence is not evidence"


def test_a_unit_with_no_stored_description_is_skipped(tmp_path):
    (tmp_path / "a.py").write_text("def charge(amount):\n    return amount\n", encoding="utf-8")
    units = build_units(tmp_path)
    assert plan(units, descriptions_module.load(tmp_path), tmp_path) == []


# --- the patch --------------------------------------------------------------


@pytest.mark.parametrize("name,body", [
    ("a.py", "def charge(amount):\n    return amount\n"),
    ("a.js", "export function charge(id) {\n  return 1;\n}\n"),
    ("a.go", "func Charge(id string) int {\n\treturn 1\n}\n"),
    ("a.rb", "def charge(id)\n  1\nend\n"),
])
def test_the_patch_applies_with_git(tmp_path, name, body):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / name).write_text(body, encoding="utf-8")
    units = build_units(tmp_path)
    patch = render_patch(tmp_path, plan(units, _store(tmp_path, units), tmp_path))
    (tmp_path / "p.diff").write_text(patch, encoding="utf-8", newline="")
    subprocess.run(["git", "apply", "p.diff"], cwd=tmp_path, check=True)
    assert ENGLISH.split(",")[0] in (tmp_path / name).read_text(encoding="utf-8")


def test_promoting_a_description_does_not_discard_it(tmp_path):
    """Promotion must not cost the half of the text it did not promote.

    A Python docstring goes inside the body, so promoting used to change the
    unit's own digest and supersede its entry -- discarding whatever was not
    promoted. Measured on this repository, that cost Chinese retrieval
    twenty-eight percent of its hit rate. Documentation is now excluded from
    the digest, because documentation is not code and cannot make a
    description wrong.
    """
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "a.py").write_text("def charge(amount):\n    return amount\n", encoding="utf-8")
    (tmp_path / "a.js").write_text("export function charge(id) {\n  return 1;\n}\n", encoding="utf-8")
    units = build_units(tmp_path)
    store = _store(tmp_path, units)
    (tmp_path / "p.diff").write_text(render_patch(tmp_path, plan(units, store, tmp_path)), encoding="utf-8", newline="")
    subprocess.run(["git", "apply", "p.diff"], cwd=tmp_path, check=True)

    after = build_units(tmp_path, descriptions=descriptions_module.load(tmp_path))
    still = descriptions_module.load(tmp_path).applicable(after)
    by_language = {unit.language: unit for unit in after}

    # Both survive, for different reasons, and that is the point: a promoted
    # docstring is documentation, and documentation is excluded from the digest
    # that decides whether a description still applies. Before that, promoting
    # discarded the entry and took the un-promoted half of the text with it.
    for unit in after:
        assert unit.id in still, f"{unit.language}: promoting its own text must not discard the entry"
        assert "gateway times out" in unit.description
        assert "支付网关超时" in still[unit.id], "the half that stayed behind is still served"


def test_crlf_line_endings_are_preserved(tmp_path):
    """A patch against a CRLF checkout must not rewrite every line it touches."""
    (tmp_path / "a.js").write_text("export function charge(id) {\r\n  return 1;\r\n}\r\n", encoding="utf-8", newline="")
    units = build_units(tmp_path)
    patch = render_patch(tmp_path, plan(units, _store(tmp_path, units), tmp_path))
    added = [line for line in patch.splitlines(keepends=True) if line.startswith("+") and not line.startswith("+++")]
    assert added and all(line.endswith("\r\n") for line in added)


def test_several_insertions_in_one_file_do_not_shift_each_other(tmp_path):
    source = "def alpha():\n    return 1\n\n\ndef beta():\n    return 2\n\n\ndef gamma():\n    return 3\n"
    (tmp_path / "a.py").write_text(source, encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    units = build_units(tmp_path)
    insertions = plan(units, _store(tmp_path, units), tmp_path)
    assert len(insertions) == 3
    (tmp_path / "p.diff").write_text(render_patch(tmp_path, insertions), encoding="utf-8", newline="")
    subprocess.run(["git", "apply", "p.diff"], cwd=tmp_path, check=True)
    rebuilt = build_units(tmp_path)
    assert len(rebuilt) == 3
    assert all("Documented intent:" in unit.description for unit in rebuilt)


# --- the command ------------------------------------------------------------


def test_the_command_puts_the_patch_on_stdout(tmp_path, capsys):
    (tmp_path / "a.py").write_text("def charge(amount):\n    return amount\n", encoding="utf-8")
    assert main(["index", str(tmp_path)]) == 0
    capsys.readouterr()
    units = build_units(tmp_path)
    _store(tmp_path, units)

    assert main(["describe", "promote", "--root", str(tmp_path)]) == 0
    captured = capsys.readouterr()
    assert captured.out.startswith("--- a/"), "stdout must be pipeable into `git apply`"
    assert json.loads(captured.err)["insertions"] == 1


def test_the_command_reports_json_when_writing_a_file(tmp_path, capsys):
    (tmp_path / "a.py").write_text("def charge(amount):\n    return amount\n", encoding="utf-8")
    assert main(["index", str(tmp_path)]) == 0
    capsys.readouterr()
    _store(tmp_path, build_units(tmp_path))

    out = tmp_path / "p.diff"
    assert main(["describe", "promote", "--root", str(tmp_path), "--output", str(out)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["insertions"] == 1 and report["files"] == 1
    assert out.read_text(encoding="utf-8").startswith("--- a/")
