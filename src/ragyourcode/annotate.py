"""Generate stable, descriptive comments for code units without an LLM."""

from __future__ import annotations

import ast
import re

# Where a generated description stops describing the signature and starts
# quoting what the author wrote. Three modules needed to recognise it and all
# three spelled it out: this one writes it, the parser writes it again for the
# other fourteen languages, and `document` looked for it. A string literal
# duplicated across modules that must agree is a rename away from a silent
# disagreement.
DOCUMENTED_MARKER = "Documented intent:"


def _humanize(name: str) -> str:
    """Turns a programmer identifier into ordinary words: splits camelCase
    apart, replaces underscores with spaces, lowercases the result. Empty
    input becomes a placeholder rather than an empty string.
    """
    words = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name).replace("_", " ").split()
    return " ".join(words).strip().lower() or "anonymous unit"


def describe_python(node: ast.AST, source: str, calls: list[str], imports: list[str]) -> str:
    """Builds a readable sentence about a Python function or class without
    using a language model: the humanised name, the arguments it accepts,
    the functions it calls, the modules it uses, and the docstring appended
    verbatim as stated intent. Because it only rearranges words already in
    the source, it adds no vocabulary the code did not have, which is why
    retrieval cannot reach a concept nobody wrote down.
    """
    name = getattr(node, "name", "anonymous")
    kind = "method" if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) else "class"
    args = []
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        args = [arg.arg for arg in node.args.args]
    pieces = [f"This {kind} {_humanize(name)}"]
    if args:
        pieces.append("accepts " + ", ".join(args))
    if calls:
        pieces.append("and calls " + ", ".join(calls[:8]))
    if imports:
        pieces.append("using " + ", ".join(imports[:8]))
    doc = ast.get_docstring(node)
    if doc:
        pieces.append(f"{DOCUMENTED_MARKER} " + " ".join(doc.split()))
    return ". ".join(pieces) + "."


def comment_for(description: str, serial: int, unit_id: str) -> str:
    """A language-neutral comment payload suitable for sidecar files."""
    return f"RAG[{serial:05d}] {unit_id}: {description}"
