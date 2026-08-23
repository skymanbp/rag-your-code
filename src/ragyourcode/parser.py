"""Code parsers. Python is AST-precise; common other languages use a safe fallback."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from .annotate import describe_python
from .models import CodeUnit

EXTENSIONS = {
    ".py": "python", ".pyi": "python", ".js": "javascript", ".jsx": "javascript",
    ".ts": "typescript", ".tsx": "typescript", ".go": "go", ".rs": "rust",
    ".java": "java", ".c": "c", ".h": "c", ".cpp": "cpp", ".cc": "cpp",
    ".php": "php", ".rb": "ruby", ".swift": "swift", ".kt": "kotlin", ".kts": "kotlin",
    ".cs": "csharp", ".scala": "scala", ".sh": "shell", ".bash": "shell",
}
FUNCTION_RE = re.compile(
    r"(?m)^(?:\s*(?:async\s+)?def\s+([A-Za-z_]\w*)|\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_]\w*)|\s*(?:func|fun)\s+([A-Za-z_]\w*)|\s*fn\s+([A-Za-z_]\w*)|\s*(?:public|private|protected|static|async|inline|virtual|\s)+[\w<>\[\], ]+\s+([A-Za-z_]\w*)\s*\([^;]*\))"
)


def _line_offsets(source: str) -> list[int]:
    offsets = [0]
    for line in source.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line)
)
    return offsets


def _snippet(source: str, start: int, end: int) -> str:
    return source[start:end].strip()


def _python_units(path: Path, source: str, relative: str, diagnostics: list[dict] | None = None) -> list[CodeUnit]:
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        if diagnostics is not None:
            diagnostics.append({"path": relative, "code": "syntax_error", "line": exc.lineno, "message": exc.msg})
        return []
    offsets = _line_offsets(source)
    units: list[CodeUnit] = []
    serial = 0
    module_imports = sorted(
        {
            item.module or (item.names[0].name if item.names else "")
            for item in tree.body
            if isinstance(item, ast.ImportFrom)
        }
        | {alias.name for item in tree.body if isinstance(item, ast.Import) for alias in item.names}
        - {""}
    )

    def visit(node: ast.AST, parent: str | None = None) -> None:
        nonlocal serial
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            serial += 1
            name = node.name
            qualified = f"{parent}.{name}" if parent else name
            start_line = node.lineno
            end_line = getattr(node, "end_lineno", node.lineno)
            calls = sorted(
                {
                    call.func.id
                    if isinstance(call.func, ast.Name)
                    else ast.unparse(call.func)
                    for call in ast.walk(node)
                    if isinstance(call, ast.Call) and isinstance(call.func, (ast.Name, ast.Attribute))
                }
            )
            imports = sorted(
                set(module_imports)
                | {
                    item.module or (item.names[0].name if item.names else "")
                    for item in ast.walk(node)
                    if isinstance(item, ast.ImportFrom)
                }
                | {alias.name for item in ast.walk(node) if isinstance(item, ast.Import) for alias in item.names}
            )
            imports = sorted(set(imports) - {""})
            rendered = ast.unparse(node).splitlines()
            signature = next(
                (line.strip() for line in rendered if line.lstrip().startswith(("def ", "async def ", "class "))),
                rendered[0].strip(),
            )[:500]
            description = describe_python(node, source, calls, imports)
            unit_id = f"{relative}:{start_line}:{qualified}"
            units.append(CodeUnit(unit_id, relative, "python", "class" if isinstance(node, ast.ClassDef) else "function", name, qualified, signature, start_line, end_line, _snippet(source, offsets[start_line - 1], offsets[end_line]), description, serial, parent, calls, imports))
            for child in node.body:
                visit(child, qualified)
            return
        for child in ast.iter_child_nodes(node):
            visit(child, parent)

    visit(tree)
    return units


def _generic_units(path: Path, source: str, relative: str, language: str) -> list[CodeUnit]:
    lines = source.splitlines()
    matches = list(FUNCTION_RE.finditer(source))
    units: list[CodeUnit] = []
    for serial, match in enumerate(matches, 1):
        name = next((group for group in match.groups() if group), "anonymous")
        start_line = source.count("\n", 0, match.start()) + 1
        if serial < len(matches):
            next_start = matches[serial].start()
            boundary_line = source.count("\n", 0, next_start) + 1
            end_line = max(start_line, boundary_line - 1)
        else:
            # ``splitlines`` does not add a phantom line for a file without a
            # trailing newline, so use the actual final line.
            end_line = len(lines)
        body = "\n".join(lines[start_line - 1:end_line]).strip()
        qualified = name
        description = f"This {language} function {_humanize_name(name)}. Searchable source span contains its declaration and implementation."
        unit_id = f"{relative}:{start_line}:{qualified}"
        units.append(CodeUnit(unit_id, relative, language, "function", name, qualified, lines[start_line - 1][:500], start_line, end_line, body, description, serial))
    return units


def _humanize_name(name: str) -> str:
    return re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name).replace("_", " ").lower()


def parse_file(path: Path, root: Path, diagnostics: list[dict] | None = None) -> list[CodeUnit]:
    language = EXTENSIONS.get(path.suffix.lower())
    if not language:
        return []
    relative = path.relative_to(root).as_posix()
    try:
        source = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        if diagnostics is not None:
            diagnostics.append({"path": relative, "code": "decode_error", "line": None, "message": str(exc)})
        return []
    except OSError as exc:
        if diagnostics is not None:
            diagnostics.append({"path": relative, "code": "read_error", "line": None, "message": str(exc)})
        return []
    return _python_units(path, source, relative, diagnostics) if language == "python" else _generic_units(path, source, relative, language)
