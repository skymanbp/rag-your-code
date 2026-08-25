"""The non-Python parser graded against tests/fixtures/languages/.

Written BEFORE the parser rewrite it grades, deliberately. Authored after, these
expectations would encode whatever the new parser happened to do; the golden set
that existed before this one resolved entirely to Python, which is why a
regression that gave TypeScript zero units never turned the suite red.

Eligibility ("what is a unit") is defined once in fixtures/languages/SPEC.md.
Every entry below was derived from that spec and re-verified against the source.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ragyourcode.parser import parse_file

FIXTURES = Path(__file__).parent / "fixtures" / "languages"
EXPECTED = json.loads((FIXTURES / "expected.json").read_text(encoding="utf-8"))

# Known-gap ledger, emptied by the P3 parser rewrite. The marks it carried
# were strict, so every one of its 57 entries had to be removed by a case
# that actually started passing. Baseline before the rewrite, over the 91
# core entries: 28 found (31%), 4 with the correct start_line (4%), 5 with a
# usable signature (5%), 24 phantom units invented from control flow, string
# literals and commented-out code. After: 91 / 91 / 91, 0 phantoms, 0 leaks.
PENDING_PARSER_REWRITE: frozenset[str] = frozenset()


def _mark_pending(request: pytest.FixtureRequest, fixture: str) -> None:
    del fixture  # the ledger is keyed by the full parametrised node name
    if request.node.name in PENDING_PARSER_REWRITE:
        request.node.add_marker(pytest.mark.xfail(strict=True, reason="P3 parser rewrite pending"))


def _units_by_name(fixture: str) -> dict[str, list]:
    grouped: dict[str, list] = {}
    for unit in parse_file(FIXTURES / fixture, FIXTURES):
        grouped.setdefault(unit.name, []).append(unit)
    return grouped


@pytest.mark.parametrize("fixture", sorted(EXPECTED))
def test_core_declarations_are_found(fixture: str, request: pytest.FixtureRequest):
    _mark_pending(request, fixture)
    found = _units_by_name(fixture)
    missing = [entry["name"] for entry in EXPECTED[fixture]["expected"] if entry["tier"] == "core" and entry["name"] not in found]
    assert missing == [], f"{fixture}: core declarations not indexed: {missing}"


@pytest.mark.parametrize("fixture", sorted(EXPECTED))
def test_core_declarations_report_the_right_line(fixture: str, request: pytest.FixtureRequest):
    """An agent follows the reported location; a wrong line sends it to wrong code."""
    _mark_pending(request, fixture)
    found = _units_by_name(fixture)
    wrong = [
        (entry["name"], entry["start_line"], [unit.start_line for unit in found[entry["name"]]])
        for entry in EXPECTED[fixture]["expected"]
        if entry["tier"] == "core" and entry["name"] in found
        and not any(unit.start_line == entry["start_line"] for unit in found[entry["name"]])
    ]
    assert wrong == [], f"{fixture}: wrong start_line (name, expected, got): {wrong}"


@pytest.mark.parametrize("fixture", sorted(EXPECTED))
def test_core_declarations_carry_a_usable_signature(fixture: str, request: pytest.FixtureRequest):
    """CodeUnit.searchable_text leads with the signature; an empty one is dead weight."""
    _mark_pending(request, fixture)
    found = _units_by_name(fixture)
    bad = [
        (entry["name"], [unit.signature for unit in found[entry["name"]]])
        for entry in EXPECTED[fixture]["expected"]
        if entry["tier"] == "core" and entry["name"] in found
        and not any(entry["signature_contains"] in unit.signature for unit in found[entry["name"]])
    ]
    assert bad == [], f"{fixture}: signature missing its declaration text: {bad}"


@pytest.mark.parametrize("fixture", sorted(EXPECTED))
def test_no_phantom_units_are_invented(fixture: str, request: pytest.FixtureRequest):
    """Control flow, string literals and commented-out code are not declarations."""
    _mark_pending(request, fixture)
    phantoms = sorted(set(_units_by_name(fixture)) & set(EXPECTED[fixture]["negatives"]))
    assert phantoms == [], f"{fixture}: invented units from non-declarations: {phantoms}"


@pytest.mark.parametrize("fixture", sorted(EXPECTED))
def test_spec_excluded_constructs_are_not_indexed(fixture: str, request: pytest.FixtureRequest):
    """Fields, prototypes, type aliases and macros are excluded by SPEC.md, not by accident."""
    _mark_pending(request, fixture)
    excluded = {item["name"] for item in EXPECTED[fixture]["spec_exclusions"]}
    leaked = sorted(set(_units_by_name(fixture)) & excluded)
    assert leaked == [], f"{fixture}: SPEC-excluded constructs were indexed: {leaked}"


# Every entry re-verified by reading the fixture source: the enclosing
# declaration, the line it opens on, and where its body closes. Spot checks
# across nine files and two block styles -- braces and Ruby's `end` -- rather
# than an exhaustive table, because the exhaustive claim is made structurally
# by the test below it and a second copy of it would rot independently.
QUALIFIED = {
    "sample.ts": {"getOrLoad": "TtlCache.getOrLoad", "prune": "TtlCache.prune"},
    "SyncEngine.kt": {"enqueue": "SyncEngine.enqueue", "flush": "SyncEngine.flush"},
    # module Webhooks > class Delivery > def perform!, three levels deep.
    "delivery.rb": {"perform!": "Webhooks.Delivery.perform!", "handler": "Webhooks.handler"},
    "FeedStore.swift": {"isEmpty": "Page.isEmpty", "refresh": "FeedStore.refresh"},
    "PriceCatalog.scala": {"plus": "Money.plus", "lookup": "PriceCatalog.lookup"},
    "InventoryService.java": {"adjust": "InventoryService.adjust"},
    "ReportBuilder.cs": {"RenderAsync": "ReportBuilder.RenderAsync"},
    "Invoice.php": {"addLine": "Invoice.addLine"},
    # Nothing encloses it, so the qualified name is the name.
    "sample.js": {"computeBackoff": "computeBackoff"},
}


@pytest.mark.parametrize("fixture", sorted(QUALIFIED))
def test_a_declaration_is_named_by_what_encloses_it(fixture: str):
    """`CodeUnit.qualified_name` carries the enclosing scope in every language.

    The Python path built `Svc.helper` from the syntax tree while the line
    scanner set `qualified_name = name`, so for fourteen of fifteen languages a
    method could not be told from a free function of the same name, `contains`
    edges had nothing to key on, and two same-named methods in one file were
    one symbol as far as the graph was concerned.
    """
    found = _units_by_name(fixture)
    for name, expected in QUALIFIED[fixture].items():
        assert name in found, f"{fixture}: {name} was not parsed at all"
        assert [unit.qualified_name for unit in found[name]] == [expected], f"{fixture}:{name}"


@pytest.mark.parametrize("fixture", sorted(EXPECTED))
def test_every_qualified_name_is_derived_from_a_real_enclosing_span(fixture: str, request: pytest.FixtureRequest):
    """The exhaustive half: no unit may claim an owner that does not contain it.

    A hand-written table only checks the cases somebody thought of. This checks
    every unit in every fixture against the spans the parser itself produced,
    so a resolver that began inventing owners, or attaching them to the wrong
    declaration, fails here whether or not anyone extended the table.
    """
    _mark_pending(request, fixture)
    units = parse_file(FIXTURES / fixture, FIXTURES)
    for unit in units:
        owners = unit.qualified_name.split(".")
        assert owners[-1] == unit.name, f"{fixture}: {unit.qualified_name} does not end in {unit.name}"
        enclosing = [
            other
            for other in units
            if other.kind == "class"
            and other.start_line <= unit.start_line
            and unit.end_line <= other.end_line
            and (other.start_line, other.end_line) != (unit.start_line, unit.end_line)
        ]
        assert owners[:-1] == [other.name for other in enclosing], (
            f"{fixture}: {unit.qualified_name} names owners that do not enclose lines "
            f"{unit.start_line}-{unit.end_line}"
        )


def test_the_ruler_itself_is_well_formed():
    """A fixture whose expectations do not match its own source proves nothing."""
    for fixture, spec in EXPECTED.items():
        lines = (FIXTURES / fixture).read_text(encoding="utf-8").splitlines()
        for entry in spec["expected"]:
            assert 1 <= entry["start_line"] <= len(lines), f"{fixture}:{entry['name']} line out of range"
            assert entry["signature_contains"] in lines[entry["start_line"] - 1], (
                f"{fixture}:{entry['name']} claims {entry['signature_contains']!r} on line "
                f"{entry['start_line']}, which reads {lines[entry['start_line'] - 1]!r}"
            )
        for negative in spec["negatives"]:
            assert any(negative in line for line in lines), f"{fixture}: negative {negative!r} absent from source"
