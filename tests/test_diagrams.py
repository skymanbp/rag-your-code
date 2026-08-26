"""The diagrams in docs/FLOW.md, checked the way every other claim here is.

A mermaid block that GitHub refuses to render fails silently: the page shows a
grey box, the reader learns nothing, and nothing in the repository notices. The
four diagrams were published in 1.4.2 with no gate at all, so this file is the
same argument the rest of the project makes about numbers, applied to pictures.

It is a structural check, not a renderer. It asserts the properties that
actually break rendering -- an unquoted label carrying a bracket, an arrow
pointing at a node nobody declared, a diagram with no type -- and says nothing
about whether the picture is a good one.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

FLOW = Path(__file__).resolve().parents[1] / "docs" / "FLOW.md"
DIAGRAM_TYPES = ("flowchart", "graph", "sequenceDiagram", "stateDiagram", "classDiagram", "erDiagram")
# `A["label"]`, `A[["label"]]`, `A[("label")]`, `A{"label"}`, `A(["label"])`
NODE = re.compile(r'(?P<id>\b[A-Za-z_][A-Za-z0-9_]*)(?P<open>\[\[|\[\(|\(\[|\[|\{\{|\{|\()(?P<body>[^\n]*?)(?P<close>\]\]|\)\]|\]\)|\]|\}\}|\}|\))(?=\s|$)')
EDGE = re.compile(r'(?P<left>\b[A-Za-z_][A-Za-z0-9_]*)\s*(?:-{2,3}>|-\.->|={2,3}>|-{2,3}|-\.-)\s*(?:\|[^|]*\|\s*)?(?P<right>\b[A-Za-z_][A-Za-z0-9_]*)')


def _outside_labels(line: str) -> str:
    """The line with every quoted label blanked out.

    An edge pattern run over the raw text finds arrows inside labels: the
    sidecar node's own text says `with --compact`, which reads as an edge from
    a node called `with`. Blanking the labels rather than excluding them keeps
    every column index intact for the error messages.
    """
    return re.sub(r'"[^"]*"', lambda m: " " * len(m.group(0)), line)


def _blocks() -> list[tuple[int, list[str]]]:
    """Every ```mermaid fence in FLOW.md, with the line it starts on."""
    lines = FLOW.read_text(encoding="utf-8").splitlines()
    out: list[tuple[int, list[str]]] = []
    start = None
    for number, line in enumerate(lines, 1):
        if line.strip() == "```mermaid":
            start = number
            body: list[str] = []
        elif start is not None and line.strip() == "```":
            out.append((start, body))
            start = None
        elif start is not None:
            body.append(line)
    assert start is None, "an unterminated ```mermaid fence"
    return out


def test_the_document_still_carries_its_diagrams():
    """A gate that passes on zero blocks would not notice them being deleted."""
    assert len(_blocks()) == 4


@pytest.mark.parametrize("index", range(4))
def test_every_diagram_declares_a_type_mermaid_knows(index: int):
    _, body = _blocks()[index]
    first = next(line.strip() for line in body if line.strip())
    assert first.startswith(DIAGRAM_TYPES), f"unknown diagram type: {first!r}"


@pytest.mark.parametrize("index", range(4))
def test_every_label_that_carries_punctuation_is_quoted(index: int):
    """An unquoted bracket, brace or parenthesis inside a label ends the node.

    This is the failure that produces a grey box rather than an error: the
    parser stops where the label was supposed to continue and never recovers.
    """
    start, body = _blocks()[index]
    for offset, line in enumerate(body):
        for match in NODE.finditer(line):
            label = match.group("body")
            if label.startswith('"') and label.endswith('"'):
                continue
            assert not re.search(r'[\[\]{}()<>|]', label), (
                f"docs/FLOW.md:{start + offset + 1}: unquoted label with punctuation: {label!r}"
            )


@pytest.mark.parametrize("index", range(4))
def test_a_line_break_inside_a_label_is_written_the_one_way_that_renders(index: int):
    """`\n` inside a mermaid label is two literal characters, not a break."""
    start, body = _blocks()[index]
    for offset, line in enumerate(body):
        for match in NODE.finditer(line):
            assert "\n" not in match.group("body"), (
                f"docs/FLOW.md:{start + offset + 1}: use <br/>, not a backslash-n"
            )


@pytest.mark.parametrize("index", range(4))
def test_every_arrow_points_at_a_node_the_diagram_declares(index: int):
    """An edge naming an undeclared id renders an empty box with no error."""
    start, body = _blocks()[index]
    declared = {m.group("id") for line in body for m in NODE.finditer(line)}
    declared |= {line.split()[1] for line in body if line.strip().startswith("subgraph ")}
    for offset, line in enumerate(body):
        stripped = line.strip()
        if stripped.startswith(("style ", "subgraph ", "%%", "end", "classDef ")):
            continue
        for match in EDGE.finditer(_outside_labels(line)):
            for side in ("left", "right"):
                name = match.group(side)
                assert name in declared, (
                    f"docs/FLOW.md:{start + offset + 1}: edge names {name!r}, "
                    f"which no node in this diagram declares"
                )


@pytest.mark.parametrize("index", range(4))
def test_every_style_line_names_a_node_that_exists(index: int):
    start, body = _blocks()[index]
    declared = {m.group("id") for line in body for m in NODE.finditer(line)}
    declared |= {line.split()[1] for line in body if line.strip().startswith("subgraph ")}
    for offset, line in enumerate(body):
        if line.strip().startswith("style "):
            target = line.split()[1]
            assert target in declared, (
                f"docs/FLOW.md:{start + offset + 1}: styles {target!r}, which is not a node here"
            )


def test_the_checks_above_actually_fire():
    """A gate nobody has seen fail is a gate nobody has seen work.

    Every assertion above runs over a file that already passes, so the only
    evidence that they check anything is a case each one refuses.
    """
    unquoted = next(NODE.finditer("A[label (with a paren)]"))
    assert re.search(r"[\[\]{}()<>|]", unquoted.group("body"))

    quoted = next(NODE.finditer('A["label (with a paren)"]'))
    body = quoted.group("body")
    assert body.startswith('"') and body.endswith('"')

    literal = next(NODE.finditer('A["first' + chr(92) + 'nsecond"]'))
    assert chr(92) + "n" in literal.group("body")

    assert [m.group("left") for m in EDGE.finditer(_outside_labels("A --> B"))] == ["A"]
    # The case that made the first version of this file wrong: the sidecar
    # node's own label says `with --compact`, which read as an edge from a
    # node called `with`.
    label = 'V --> J[(".rag-your-code<br/>plus a sidecar with --compact")]'
    assert [m.group("left") for m in EDGE.finditer(_outside_labels(label))] == ["V"]
