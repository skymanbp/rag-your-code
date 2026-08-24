"""Code parsers. Python is AST-precise; other languages use a line scanner.

The non-Python path is three separated layers:

    Layer 1  line scanner    one match attempt per line; the line number IS the
                             loop index, so it cannot drift
    Layer 2  rule table      per-language declaration patterns, each anchored
                             inside a single line
    Layer 3  span closer     brace balance, or Ruby's `end`, or the next
                             declaration

The separation is what fixes the defects, not the individual patterns. One
whole-file regex previously did all three jobs at once, and its coupling
produced catastrophic backtracking (a 530-byte file took 12.6 s), an `[^;]*`
that swallowed every declaration up to the last `)` in a file, and a leading
`\\s*` that started matches on preceding blank lines so reported line numbers
and signatures were wrong. A pattern that cannot see a second line cannot
consume one.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
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


@dataclass(frozen=True, slots=True)
class Declaration:
    """One declaration shape for one language family."""

    kind: str
    pattern: re.Pattern[str]


# Horizontal whitespace only, never ``\s``, which also matches a newline. A
# leading ``\s*`` is exactly what let the previous parser begin a match on a
# preceding blank line and report the wrong start_line for 9 declarations in 10.
IND = r"[^\S\r\n]*"
SP = r"[^\S\r\n]+"
ID = r"[A-Za-z_][A-Za-z0-9_]*"
DOLLAR_ID = r"[A-Za-z_$][A-Za-z0-9_$]*"
TYPES = "class|interface|struct|trait|enum|protocol|object|module|record|union"
# Words that open a statement, not a declaration. Without this the bare
# `TYPE name(args)` shape shared by C, C++, Java and C# also matches `if (x) {`.
CONTROL = (
    r"(?!(?:if|for|while|switch|catch|return|else|do|new|throw|sizeof|typedef|using"
    r"|namespace|case|default|delete|goto|await|yield|assert|echo|match|when|guard"
    r"|repeat|defer|select|import|package|export|from|try|finally|with|in|is|as)\b)"
)
# A declaration line ends where its parameters end, its body opens, or its
# parameters continue onto the next line -- `constructor(` and
# `public async Task<string> RenderAsync(` break immediately after the open
# paren, so end-of-line alone has to count. A trailing `;` still cannot match:
# the `[^;]*` ahead of this cannot cross one, which is how a same-line prototype
# or a call statement stays out. Prototypes whose `;` lands on a later line are
# rejected by the span closer instead.
TAIL = r"(?:\{|\(|\)|,|:|=>|->|=)?[^\S\r\n]*$"

RULES: dict[str, tuple[Declaration, ...]] = {}


def _rule(kind: str, body: str) -> Declaration:
    return Declaration(kind, re.compile(body))


def _register(languages: tuple[str, ...], rules: tuple[Declaration, ...]) -> None:
    for language in languages:
        RULES[language] = rules


_register(("javascript", "typescript"), (
    _rule("class", rf"^{IND}(?:export{SP})?(?:default{SP})?(?:abstract{SP})?(?:{TYPES}){SP}(?P<name>{ID})\b"),
    # `function NAME(` anywhere on the line, so a named function expression such
    # as `return function acquire(task) {` is found. An anonymous `function()`
    # carries no identifier and cannot match.
    _rule("function", rf"\bfunction{IND}\*?{IND}(?P<name>{ID}){IND}\("),
    # A binding is a unit only when its right-hand side is *syntactically* a
    # function literal (SPEC.md). `= makeLimiter(4)` is a reference and `= {` is
    # a value, so an arrow or the `function` keyword must appear on the line.
    _rule("function", rf"^{IND}(?:export{SP})?(?:const|let|var){SP}(?P<name>{DOLLAR_ID})[^\S\r\n]*(?::[^=]*)?={IND}(?:async{SP})?function\b"),
    _rule("function", rf"^{IND}(?:export{SP})?(?:const|let|var){SP}(?P<name>{DOLLAR_ID})[^\S\r\n]*(?::[^=]*)?=[^=]*=>"),
    # Class-body and object-literal shorthand carry no `function` keyword at all.
    _rule("method", rf"^{IND}(?:(?:public|private|protected|readonly|static|abstract|override|declare|async|get|set){SP})*{CONTROL}(?P<name>{DOLLAR_ID}){IND}(?:<[^;{{]*>)?{IND}\([^;{{]*(?:\{{|{TAIL})"),
))

_register(("go",), (
    _rule("class", rf"^{IND}type{SP}(?P<name>{ID}){SP}(?:{TYPES})\b"),
    _rule("method", rf"^{IND}func{IND}\([^)]*\){IND}(?P<name>{ID}){IND}[\(\[]"),
    _rule("function", rf"^{IND}func{SP}(?P<name>{ID}){IND}[\(\[]"),
    _rule("function", rf"^{IND}var{SP}(?P<name>{ID}){IND}={IND}func\b"),
))

_register(("rust",), (
    _rule("class", rf"^{IND}(?:pub(?:\([^)]*\))?{SP})?(?:{TYPES}){SP}(?P<name>{ID})\b"),
    _rule("function", rf"^{IND}(?:pub(?:\([^)]*\))?{SP})?(?:const{SP})?(?:async{SP})?(?:unsafe{SP})?fn{SP}(?P<name>{ID})\b"),
))

_JVM = (
    # `case` is deliberately absent: as a modifier it also lets `case Some(m) =>`
    # match the bare TYPE-name-args method shape below. Scala's `case class` is
    # handled by the class rule, which spells `case` out.
    r"(?:public|private|protected|internal|static|final|abstract|override|open|sealed"
    r"|suspend|async|virtual|inline|operator|infix|tailrec|external|partial|readonly"
    r"|lateinit|data|value|implicit|synchronized|native|transient|volatile|strictfp)"
)
_register(("java", "csharp", "kotlin", "scala"), (
    _rule("class", rf"^{IND}(?:case{SP})?(?:{_JVM}{SP})*(?:{TYPES}){SP}(?P<name>{ID})\b"),
    # Kotlin extension functions carry a receiver: `fun String.toDocumentId(...)`.
    _rule("function", rf"^{IND}(?:{_JVM}{SP})*fun{SP}{ID}\.(?P<name>{ID}){IND}\("),
    _rule("method", rf"^{IND}(?:{_JVM}{SP})*(?:fun|def){SP}(?:<[^>]*>{IND})?(?P<name>{ID}){IND}[\(\[:=]"),
    _rule("function", rf"^{IND}(?:{_JVM}{SP})*(?:fun|def){SP}(?P<name>{ID})\b"),
    # `<[^{(]*>` rather than `<[^>]*>`: a Java generic method leads with
    # `public static <T extends Comparable<T>> List<T> sortedCopy(`, whose type
    # parameter list nests, and stopping at the first `>` loses the name. The
    # class is bounded by `{` and `(` so it still cannot leave the declaration.
    _rule("method", rf"^{IND}(?:{_JVM}{SP})+(?:<[^{{(]*>{IND})?(?:[\w.<>\[\],?]+{SP})?{CONTROL}(?P<name>{ID}){IND}\([^;{{]*(?:\{{|{TAIL})"),
))

_C = r"(?:static|inline|extern|const|constexpr|virtual|explicit|friend|public|private|protected|unsigned|signed|struct|enum|union|register|volatile)"
_register(("c", "cpp"), (
    _rule("class", rf"^{IND}(?:typedef{SP})?(?:{TYPES}){SP}(?P<name>{ID}){IND}(?:final{IND})?(?::[^;]*)?{IND}\{{"),
    # A destructor's identifier includes the tilde, which is what keeps it
    # distinct from the constructor of the same class.
    _rule("method", rf"^{IND}(?P<name>~{ID}){IND}\("),
    _rule("method", rf"^{IND}(?:{_C}{SP})*(?:[\w:<>,]+[\s*&]+)?{ID}::(?P<name>~?{ID}){IND}\([^;{{]*(?:\{{|{TAIL})"),
    _rule("function", rf"^{IND}(?:{_C}{SP})*(?:[\w:<>,]+{IND}[*&]?{SP})+[*&]*{CONTROL}(?P<name>{ID}){IND}\([^;{{]*(?:\{{|{TAIL})"),
    _rule("method", rf"^{IND}(?:{_C}{SP})+{CONTROL}(?P<name>{ID}){IND}\([^;{{]*(?:\{{|{TAIL})"),
))

_register(("ruby",), (
    _rule("class", rf"^{IND}(?:class|module){SP}(?P<name>[A-Z][A-Za-z0-9_]*)"),
    _rule("method", rf"^{IND}def{SP}(?:self\.)?(?P<name>[A-Za-z_][A-Za-z0-9_]*[?!=]?)"),
    _rule("function", rf"^{IND}(?P<name>{ID}){IND}={IND}(?:->|lambda|proc|Proc\.new)"),
))

_PHP = r"(?:public|private|protected|static|final|abstract|readonly)"
_register(("php",), (
    _rule("class", rf"^{IND}(?:{_PHP}{SP})*(?:{TYPES}){SP}(?P<name>{ID})\b"),
    _rule("method", rf"^{IND}(?:{_PHP}{SP})+function{SP}&?{IND}(?P<name>{ID}){IND}\("),
    _rule("function", rf"^{IND}function{SP}&?{IND}(?P<name>{ID}){IND}\("),
    _rule("function", rf"^{IND}\$(?P<name>{ID}){IND}={IND}(?:static{SP})?(?:fn|function)\b"),
))

_SWIFT = r"(?:public|private|internal|fileprivate|open|static|class|final|override|mutating|nonmutating|required|convenience|indirect|dynamic|lazy|weak|unowned)"
_register(("swift",), (
    _rule("class", rf"^{IND}(?:{_SWIFT}{SP})*(?:class|struct|enum|protocol|extension|actor){SP}(?P<name>{ID})\b"),
    _rule("method", rf"^{IND}(?:{_SWIFT}{SP})*func{SP}(?P<name>{ID}){IND}[<\(]"),
    _rule("method", rf"^{IND}(?:{_SWIFT}{SP})*(?P<name>init)[\?!]?{IND}\("),
    # A computed property owns a body; a stored one does not (SPEC.md).
    _rule("method", rf"^{IND}(?:{_SWIFT}{SP})*var{SP}(?P<name>{ID}){IND}:[^=]*\{{[^\S\r\n]*$"),
))

_register(("shell",), (
    _rule("function", rf"^{IND}function{SP}(?P<name>[\w.-]+){IND}(?:\(\){IND})?\{{?"),
    _rule("function", rf"^{IND}(?P<name>[\w.-]+){IND}\(\){IND}\{{?[^\S\r\n]*$"),
))

# Lines whose first non-space characters mark them as prose, not code.
COMMENT_PREFIXES: dict[str, tuple[str, ...]] = {
    "ruby": ("#",),
    "shell": ("#",),
    "php": ("//", "#", "*", "/*", "*/"),
}
_DEFAULT_COMMENTS = ("//", "*", "/*", "*/")
# Every language not listed closes a body with braces.
BLOCK_STYLE: dict[str, str] = {"ruby": "end"}


def _line_offsets(source: str) -> list[int]:
    """Character offsets of each line start, counting only newlines Python counts.

    ``str.splitlines`` also breaks on \\x0b, \\x0c, \\x1c-\\x1e, \\x85, U+2028 and
    U+2029, none of which ``ast`` treats as a line break. A single form feed
    inside a string literal therefore shifted every later offset, truncating one
    unit mid-literal and reducing the next to its ``def`` line with no body.
    ``read_text`` has already normalised \\r\\n and \\r to \\n by this point, so
    splitting on \\n is exactly the tokenizer's line model.
    """
    offsets = [0]
    position = 0
    for line in source.split("\n"):
        position += len(line) + 1
        offsets.append(position)
    return offsets


def _snippet(source: str, start: int, end: int) -> str:
    return source[start:end].strip()


# Which characters open a string literal, per language. Rust is the exception:
# `'` there introduces a lifetime far more often than a character literal, and
# treating `&'static str {` as an unterminated string swallowed the brace that
# proves the function has a body.
QUOTES: dict[str, str] = {"rust": '"'}
_DEFAULT_QUOTES = "\"'`"


def _strip_literals(line: str, quotes: str = _DEFAULT_QUOTES) -> str:
    """Blank out string literals and trailing line comments before counting braces.

    A character scanner rather than a regex on purpose: an alternation like
    ``(?:[^"\\\\]|\\\\.)*`` backtracks on an unterminated quote, and reintroducing
    that here would undo the reason this module was rewritten.

    ``quotes`` is language-supplied. Assuming ``'`` always opens a string read
    Rust's ``&'static str {`` as an unterminated literal and blanked out the very
    brace that proves the function has a body, so every lifetime-annotated method
    was dropped as if it were a trait signature.
    """
    out: list[str] = []
    quote = ""
    index = 0
    length = len(line)
    while index < length:
        char = line[index]
        if quote:
            if char == "\\":
                index += 2
                continue
            if char == quote:
                quote = ""
            out.append(" ")
        elif char in quotes:
            quote = char
            out.append(" ")
        elif char == "/" and index + 1 < length and line[index + 1] == "/":
            break
        elif char == "#" and not out[-1:] == ["$"]:
            break
        else:
            out.append(char)
        index += 1
    return "".join(out)


def _brace_depths(lines: list[str], quotes: str) -> list[int]:
    """Running brace depth after each line, literals and comments removed."""
    depths: list[int] = []
    depth = 0
    for line in lines:
        clean = _strip_literals(line, quotes)
        depth += clean.count("{") - clean.count("}")
        depths.append(depth)
    return depths


def _terminates_before_body(lines: list[str], start: int, quotes: str) -> bool:
    """Whether the declaration at ``start`` reaches a `;` before any `{`.

    This is the single question behind both "is it a unit at all" and "how far
    does it reach". A C prototype, a Rust trait method signature, a PHP
    interface method, a Swift protocol requirement and a Rust unit struct
    (``pub struct LineChunker;``) all terminate without opening anything -- and
    the terminator often lands on a later line than the name, which no
    single-line pattern can see.
    """
    if _strip_literals(lines[start], quotes).rstrip().endswith(("=", "=>")):
        return False  # an expression body: Kotlin `... : String =`, JS `... =>`
    for index in range(start, min(len(lines), start + 12)):
        clean = _strip_literals(lines[index], quotes)
        brace, semi = clean.find("{"), clean.find(";")
        if brace != -1 and (semi == -1 or brace < semi):
            return False
        if semi != -1:
            return True
        if index > start and (not clean.strip() or clean.lstrip().startswith("}")):
            # The declaration ended without opening anything. Swift protocol
            # requirements need this: they carry no `;`, so without a bound the
            # scan would reach the next declaration's brace and claim it.
            return True
    return True


def _opens_a_body(lines: list[str], start: int, quotes: str) -> bool:
    """SPEC.md: a unit is a named declaration that owns a body span."""
    return not _terminates_before_body(lines, start, quotes)


def _close_brace_span(lines: list[str], depths: list[int], start: int, limit: int, quotes: str) -> int:
    """Return the 0-based last line of a brace-delimited body starting at ``start``."""
    if _terminates_before_body(lines, start, quotes):
        # `pub struct LineChunker;` owns exactly its own line. Without this the
        # scan ran on to the next `{` in the file -- the following `impl` block --
        # and swallowed its methods into the unit struct's source.
        return start
    opened = next(
        (index for index in range(start, min(len(lines), start + 12)) if "{" in _strip_literals(lines[index], quotes)),
        None,
    )
    if opened is None:
        return limit
    clean = _strip_literals(lines[opened], quotes)
    outer = depths[opened] - clean.count("{") + clean.count("}")
    for index in range(opened, len(lines)):
        if depths[index] <= outer:
            return index
    return len(lines) - 1


# A line opening with one of these continues the previous statement -- a C++
# constructor initialiser list (`: slots_(slots), running_(false) {}`) reads
# exactly like `name(args) {` to a pattern that only sees one line.
CONTINUATION_PREFIXES = (":", ",", "?", ")", "]", "}", "&&", "||", "|", "+", ".", "=>", "->")


_HEREDOC_RE = re.compile(r"<<-?[^\S\r\n]*(?P<quote>[\"']?)(?P<word>[A-Za-z_][A-Za-z0-9_]*)(?P=quote)")


def _close_end_span(lines: list[str], start: int, limit: int) -> int:
    """Ruby: the matching ``end`` at the declaration's own indentation."""
    indent = len(lines[start]) - len(lines[start].lstrip())
    if re.search(r";[^\S\r\n]*end[^\S\r\n]*$", lines[start]):
        return start
    for index in range(start + 1, len(lines)):
        line = lines[index]
        if not line.strip():
            continue
        if len(line) - len(line.lstrip()) == indent and line.strip() in {"end", "end;"}:
            return index
    return limit


def _generic_units(path: Path, source: str, relative: str, language: str) -> list[CodeUnit]:
    del path  # the relative path is what identifies a unit
    lines = source.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    rules = RULES.get(language, ())
    comments = COMMENT_PREFIXES.get(language, _DEFAULT_COMMENTS)
    style = BLOCK_STYLE.get(language, "brace")
    quotes = QUOTES.get(language, _DEFAULT_QUOTES)

    hits: list[tuple[int, str, str]] = []
    heredoc = ""
    for index, line in enumerate(lines):
        stripped = line.strip()
        if heredoc:
            # Text inside a heredoc is data, not code. Without this a shell
            # script that documents a function inside `<<EOF ... EOF` gets that
            # documentation indexed as a declaration.
            if stripped == heredoc:
                heredoc = ""
            continue
        if language == "shell":
            opened = _HEREDOC_RE.search(line)
            if opened:
                heredoc = opened.group("word")
        if not stripped or stripped.startswith(comments) or stripped.startswith(CONTINUATION_PREFIXES):
            continue
        for rule in rules:
            match = rule.pattern.search(line)
            if match:
                if rule.kind != "class" and style == "brace" and not _opens_a_body(lines, index, quotes):
                    # Only brace languages can express a bodyless declaration this
                    # way. Ruby closes with `end` and its `def` always owns a body,
                    # so the brace scan would reject every method in the file.
                    break
                hits.append((index, rule.kind, match.group("name")))
                break

    depths = _brace_depths(lines, quotes) if style == "brace" else []
    offsets = _line_offsets(source)
    units: list[CodeUnit] = []
    for serial, (index, kind, name) in enumerate(hits, 1):
        fallback = hits[serial][0] - 1 if serial < len(hits) else len(lines) - 1
        if style == "end":
            last = _close_end_span(lines, index, fallback)
        else:
            last = _close_brace_span(lines, depths, index, fallback, quotes)
        last = max(index, min(last, len(lines) - 1))
        signature = lines[index].strip()[:500]
        description = (
            f"This {language} {kind} {_humanize_name(name)}. "
            f"Declared as: {signature}"
        )
        units.append(
            CodeUnit(
                f"{relative}:{index + 1}:{name}", relative, language, kind, name, name,
                signature, index + 1, last + 1,
                _snippet(source, offsets[index], offsets[last + 1]),
                description, serial,
            )
        )
    return units


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
