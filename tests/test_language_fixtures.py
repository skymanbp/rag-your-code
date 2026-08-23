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

# Known-gap ledger: the 57 of 75 parametrised cases the current parser cannot
# satisfy. P3 empties it. The marks are strict, so a case that starts passing
# fails as XPASS and cannot be quietly left behind; the ledger can only shrink.
# It is keyed per (test, fixture) rather than per fixture because 18 cases
# already pass -- marking those pending would have hidden working behaviour.
#
# Baseline over the 91 core entries: 28 found (31%), 4 with the correct
# start_line (4%), 5 with a usable signature (5%), 24 phantom units invented
# from control flow, string literals and commented-out code.
PENDING_PARSER_REWRITE = frozenset({
    "test_core_declarations_are_found[FeedStore.swift]",
    "test_core_declarations_are_found[Invoice.php]",
    "test_core_declarations_are_found[PriceCatalog.scala]",
    "test_core_declarations_are_found[ReportBuilder.cs]",
    "test_core_declarations_are_found[SyncEngine.kt]",
    "test_core_declarations_are_found[delivery.rb]",
    "test_core_declarations_are_found[deploy.sh]",
    "test_core_declarations_are_found[ringbuf.c]",
    "test_core_declarations_are_found[ringbuf.h]",
    "test_core_declarations_are_found[sample.go]",
    "test_core_declarations_are_found[sample.js]",
    "test_core_declarations_are_found[sample.rs]",
    "test_core_declarations_are_found[sample.ts]",
    "test_core_declarations_are_found[scheduler.cpp]",
    "test_core_declarations_carry_a_usable_signature[FeedStore.swift]",
    "test_core_declarations_carry_a_usable_signature[InventoryService.java]",
    "test_core_declarations_carry_a_usable_signature[Invoice.php]",
    "test_core_declarations_carry_a_usable_signature[ReportBuilder.cs]",
    "test_core_declarations_carry_a_usable_signature[SyncEngine.kt]",
    "test_core_declarations_carry_a_usable_signature[delivery.rb]",
    "test_core_declarations_carry_a_usable_signature[deploy.sh]",
    "test_core_declarations_carry_a_usable_signature[ringbuf.c]",
    "test_core_declarations_carry_a_usable_signature[sample.go]",
    "test_core_declarations_carry_a_usable_signature[sample.js]",
    "test_core_declarations_carry_a_usable_signature[sample.ts]",
    "test_core_declarations_carry_a_usable_signature[scheduler.cpp]",
    "test_core_declarations_report_the_right_line[FeedStore.swift]",
    "test_core_declarations_report_the_right_line[InventoryService.java]",
    "test_core_declarations_report_the_right_line[Invoice.php]",
    "test_core_declarations_report_the_right_line[ReportBuilder.cs]",
    "test_core_declarations_report_the_right_line[SyncEngine.kt]",
    "test_core_declarations_report_the_right_line[delivery.rb]",
    "test_core_declarations_report_the_right_line[deploy.sh]",
    "test_core_declarations_report_the_right_line[ringbuf.c]",
    "test_core_declarations_report_the_right_line[sample.go]",
    "test_core_declarations_report_the_right_line[sample.js]",
    "test_core_declarations_report_the_right_line[sample.ts]",
    "test_core_declarations_report_the_right_line[scheduler.cpp]",
    "test_no_phantom_units_are_invented[FeedStore.swift]",
    "test_no_phantom_units_are_invented[InventoryService.java]",
    "test_no_phantom_units_are_invented[Invoice.php]",
    "test_no_phantom_units_are_invented[PriceCatalog.scala]",
    "test_no_phantom_units_are_invented[ReportBuilder.cs]",
    "test_no_phantom_units_are_invented[delivery.rb]",
    "test_no_phantom_units_are_invented[deploy.sh]",
    "test_no_phantom_units_are_invented[ringbuf.c]",
    "test_no_phantom_units_are_invented[ringbuf.h]",
    "test_no_phantom_units_are_invented[sample.go]",
    "test_no_phantom_units_are_invented[sample.js]",
    "test_no_phantom_units_are_invented[sample.rs]",
    "test_no_phantom_units_are_invented[sample.ts]",
    "test_no_phantom_units_are_invented[scheduler.cpp]",
    "test_spec_excluded_constructs_are_not_indexed[FeedStore.swift]",
    "test_spec_excluded_constructs_are_not_indexed[Invoice.php]",
    "test_spec_excluded_constructs_are_not_indexed[ringbuf.h]",
    "test_spec_excluded_constructs_are_not_indexed[sample.rs]",
    "test_spec_excluded_constructs_are_not_indexed[scheduler.cpp]",
})


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
