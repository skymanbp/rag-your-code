"""Generate stable, descriptive comments for code units without an LLM."""

from __future__ import annotations

import ast
import re


def _humanize(name: str) -> str:
    words = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name).replace("_", " ").split()
    return " ".join(words).strip().lower() or "anonymous unit"


def describe_python(node: ast.AST, source: str, calls: list[str], imports: list[str]) -> str:
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
        pieces.append("Documented intent: " + " ".join(doc.split()))
    return ". ".join(pieces) + "."


def comment_for(description: str, serial: int, unit_id: str) -> str:
    """A language-neutral comment payload suitable for sidecar files."""
    return f"RAG[{serial:05d}] {unit_id}: {description}"
