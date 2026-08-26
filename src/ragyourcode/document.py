"""Promote a stored description into the source, as a patch you apply.

The sidecar store exists so that text about a unit can be written without
touching the file. That independence is bought with machinery: a digest to
decide whether the text still applies, a relocation lookup for when the code
moves, a fingerprint so an index notices the store changed, and pruning for
entries whose code is gone. Every one of those exists to *simulate* a property
that text living in the source has for free -- a docstring cannot come adrift
from the function it is inside.

So the sidecar is the fallback, not the destination. This turns what an agent
already wrote into a doc comment in the language's own convention and emits a
unified diff. The tool still never writes source: the patch is reviewed and
applied by a person, which keeps the guarantee the rest of the project makes
and puts a human between an agent's prose and the repository.

Only declarations with no documentation at all are touched. What the author
wrote outranks what an agent wrote, and `parser` already harvests it.
"""

from __future__ import annotations

import ast
import difflib
import re
from dataclasses import dataclass
from pathlib import Path

from .annotate import DOCUMENTED_MARKER
from .descriptions import DescriptionStore
from .models import CodeUnit
from .parser import EXTENSIONS, parse_file

# How each language family writes a documentation comment. The opening entry is
# empty where the convention is a repeated line prefix rather than a block.
DOC_STYLE: dict[str, tuple[str, str, str]] = {
    "javascript": ("/**", " * ", " */"),
    "typescript": ("/**", " * ", " */"),
    "java": ("/**", " * ", " */"),
    "kotlin": ("/**", " * ", " */"),
    "scala": ("/**", " * ", " */"),
    "php": ("/**", " * ", " */"),
    "swift": ("/**", " * ", " */"),
    "c": ("/**", " * ", " */"),
    "cpp": ("/**", " * ", " */"),
    "csharp": ("", "/// ", ""),
    "rust": ("", "/// ", ""),
    "go": ("", "// ", ""),
    "ruby": ("", "# ", ""),
    "shell": ("", "# ", ""),
}
WRAP_WIDTH = 76
# The phrase both description routes use when a unit already carries the
# author's own words -- a Python docstring or a harvested doc comment. One test
# for all fifteen languages, because both routes phrase it identically.
#
# It has to be looked for in the *generated* description, never in the one an
# index carries: an authored description replaces the generated sentence
# outright, so a thoroughly documented function whose description an agent had
# rewritten read as undocumented. That mistake proposed a hundred and seven
# insertions against a repository with seventeen genuinely undocumented
# declarations.
_CJK = re.compile(r"[一-鿿]")


@dataclass(frozen=True, slots=True)
class Insertion:
    """One doc comment to add, addressed by the line it goes before."""

    path: str
    line: int
    lines: tuple[str, ...]
    unit_id: str


def source_half(text: str) -> str:
    """The part of a description meant for someone reading the code.

    Descriptions are written for retrieval and may carry more than one
    language, because a query only reaches a unit whose indexed text shares its
    words. Source is read by people, so the promoted half stops at the first
    CJK character. A description written entirely in Chinese has no such half
    and is promoted whole rather than dropped.
    """
    match = _CJK.search(text)
    if match is None:
        return text.strip()
    # Only whitespace is trimmed. An earlier version also stripped trailing
    # punctuation to remove a dangling label, and ate the full stop off every
    # promoted sentence -- there is no dangling label to remove, because the
    # split happens at the first CJK character and any marker before it is
    # already part of the English half.
    head = text[: match.start()].rstrip()
    return head or text.strip()


def _wrap(text: str, width: int) -> list[str]:
    """Breaks a paragraph into lines that fit a comment's available width,
    accounting for the indentation and the marker each line carries.
    """
    words, lines, current = text.split(), [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and len(candidate) > width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def render_comment(text: str, indent: str, language: str) -> tuple[str, ...]:
    """Renders text as a documentation comment in one language's own
    convention: a block opened and closed for the C family, a repeated line
    prefix for Rust, Go, Ruby and shell. Indentation matches the declaration
    it will sit above.
    """
    opening, prefix, closing = DOC_STYLE[language]
    body = _wrap(text, WRAP_WIDTH - len(indent) - len(prefix))
    rendered = []
    if opening:
        rendered.append(f"{indent}{opening}")
    rendered.extend(f"{indent}{prefix}{line}".rstrip() for line in body)
    if closing:
        rendered.append(f"{indent}{closing}")
    return tuple(rendered)


def render_docstring(text: str, indent: str) -> tuple[str, ...]:
    """A Python docstring goes inside the body, not above the declaration."""
    body = _wrap(text, WRAP_WIDTH - len(indent))
    if len(body) == 1 and len(body[0]) + len(indent) + 6 <= WRAP_WIDTH:
        return (f'{indent}"""{body[0]}"""',)
    return (f'{indent}"""{body[0]}',) + tuple(f"{indent}{line}" for line in body[1:]) + (f'{indent}"""',)


def _python_body_start(source: str, unit: CodeUnit) -> tuple[int, str] | None:
    """Where a docstring would go, and at what indentation.

    Found through the syntax tree rather than by looking for a trailing colon,
    because a signature can span lines and carry colons in its annotations.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if node.lineno != unit.start_line or node.name != unit.name:
            continue
        if not node.body:
            return None
        first = node.body[0]
        return first.lineno, " " * first.col_offset
    return None


def plan(units: list[CodeUnit], store: DescriptionStore, root: Path) -> list[Insertion]:
    """Which declarations would gain a doc comment, and what it would say.

    Skips anything already documented, anything with no stored description,
    and any language whose convention is not known. Returned in reverse line
    order per file so that applying them cannot shift the lines still to come.
    """
    authored = store.applicable(units)
    insertions: list[Insertion] = []
    sources: dict[str, str] = {}
    generated: dict[str, str] = {}
    for unit in units:
        text = source_half(authored.get(unit.id, ""))
        if not text:
            continue
        if unit.language != "python" and unit.language not in DOC_STYLE:
            continue
        if unit.path not in sources:
            try:
                sources[unit.path] = (root / unit.path).read_text(encoding="utf-8")
            except OSError:
                sources[unit.path] = ""
            # Ask the parser what it would say about this file with no store
            # applied. Re-parsing costs one pass per touched file and removes
            # any chance of a second, subtly different notion of "documented".
            for fresh in parse_file(root / unit.path, root):
                generated[fresh.id] = fresh.description
        source = sources[unit.path]
        if not source or DOCUMENTED_MARKER in generated.get(unit.id, ""):
            continue
        lines = source.split("\n")
        if unit.language == "python":
            found = _python_body_start(source, unit)
            if found is None:
                continue
            line, indent = found
            rendered = render_docstring(text, indent)
        else:
            declaration = lines[unit.start_line - 1] if unit.start_line <= len(lines) else ""
            indent = declaration[: len(declaration) - len(declaration.lstrip())]
            line = unit.start_line
            rendered = render_comment(text, indent, unit.language)
        insertions.append(Insertion(unit.path, line, rendered, unit.id))
    insertions.sort(key=lambda item: (item.path, -item.line))
    return insertions


def render_patch(root: Path, insertions: list[Insertion]) -> str:
    """A unified diff, applyable with `git apply` or `patch -p1`.

    Newlines are taken from the file rather than assumed, so a patch against a
    CRLF checkout does not silently rewrite every line ending it touches.
    """
    by_path: dict[str, list[Insertion]] = {}
    for item in insertions:
        by_path.setdefault(item.path, []).append(item)
    chunks: list[str] = []
    for path, group in sorted(by_path.items()):
        # open(newline="") rather than read_text(newline=...), because that
        # keyword only exists from Python 3.13 and the declared floor is 3.10.
        with (root / path).open(encoding="utf-8", newline="") as handle:
            original = handle.read()
        newline = '\r\n' if '\r\n' in original else '\n'
        # keepends, not split-and-rejoin: splitting on the newline yields a
        # phantom empty final element for a file that ends with one, and
        # appending a newline to it invented a trailing blank line the file
        # does not have. `git apply` rejected every patch whose last hunk
        # reached the end of the file.
        lines = original.splitlines(keepends=True)
        updated = list(lines)
        for item in sorted(group, key=lambda entry: -entry.line):
            updated[item.line - 1 : item.line - 1] = [f"{text}{newline}" for text in item.lines]
        diff = difflib.unified_diff(
            lines, updated, fromfile=f"a/{path}", tofile=f"b/{path}", n=3
        )
        chunks.append("".join(diff))
    return "".join(chunks)


def summarise(units: list[CodeUnit], store: DescriptionStore, insertions: list[Insertion], root: Path) -> dict:
    """Counts what a promotion run would do: how many declarations already
    carry the author's own documentation, how many have a stored
    description, how many insertions the patch contains, and whether any
    supported language lacks a documentation convention here.
    """
    already = 0
    for path in sorted({unit.path for unit in units}):
        for fresh in parse_file(root / path, root):
            already += DOCUMENTED_MARKER in fresh.description
    unknown = sorted(
        {unit.language for unit in units if unit.language != "python" and unit.language not in DOC_STYLE}
    )
    return {
        "units": len(units),
        "already_documented": already,
        "described": len(store.applicable(units)),
        "insertions": len(insertions),
        "files": len({item.path for item in insertions}),
        "languages_without_a_convention": unknown,
        "extensions_known": len(EXTENSIONS),
    }
