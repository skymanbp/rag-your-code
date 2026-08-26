"""Repository-scoped configuration.

Every value here was a module constant until 0.4.0, which meant adapting the
tool to a repository meant editing installed source. The settings table below
is the single place a value is named, defaulted, bounded and classified; the
loader, the validator, the fingerprint and the ``config`` subcommand all read
it rather than each carrying their own copy of the field list.

Resolution order is: an explicit argument (a CLI flag) beats the file, and the
file beats the built-in default. There is deliberately no environment-variable
layer -- an index is an artifact of a repository, not of a shell, and a value
that changes what gets indexed has to be visible to everyone who clones it.

The file lives at the repository root as ``rag-your-code.toml``, not inside
``.rag-your-code/``. That directory holds only generated artifacts and is
ignored by Git, so anything authored that lived there would be both
uncommittable and destroyed by the obvious way to clear the cache.
"""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .parser import EXTENSIONS

CONFIG_FILENAME = "rag-your-code.toml"


class ConfigError(ValueError):
    """A configuration file that cannot be applied as written.

    Raised rather than warned about. A setting that is silently dropped is
    indistinguishable, from the outside, from a setting that had no effect, so
    the user has no way to tell a typo from a misunderstanding.
    """


@dataclass(frozen=True, slots=True)
class Setting:
    """One configurable value.

    ``affects_build`` marks the settings that change *what is indexed* or *the
    vector space the index lives in*. Only those enter the fingerprint: forcing
    a full re-index because someone adjusted a default result limit would make
    the fingerprint an obstacle rather than a safeguard.

    ``members``, where present, is the closed set a list value may draw from.
    It exists for one case that used to fail in silence: a suffix the walker
    accepts but the parser has no rules for is read, parsed to nothing, and
    reported as a successful index of zero units.
    """

    path: str
    kind: str
    default: Any
    affects_build: bool = False
    minimum: float | None = None
    maximum: float | None = None
    help: str = ""
    members: frozenset[str] | None = field(default=None)

    @property
    def table(self) -> str:
        """The section a setting belongs to, taken from the part of its name
        before the dot.
        """
        return self.path.split(".", 1)[0]

    @property
    def key(self) -> str:
        """The bare key of a setting within its section, taken from the part of
        its name after the dot.
        """
        return self.path.split(".", 1)[1]


# Defaults reproduce the constants they replace exactly, so a repository with
# no configuration file indexes and searches byte-identically to 0.3.0.
SETTINGS: tuple[Setting, ...] = (
    Setting(
        "index.ignore",
        "str_list",
        (".git", ".hg", ".svn", ".venv", "venv", "node_modules", "dist", "build", "__pycache__", ".rag-your-code"),
        affects_build=True,
        help="directory names never descended into",
    ),
    # Derived from the parser's own dispatch table rather than restated. The
    # two lists agreed by coincidence and nothing enforced it; a suffix present
    # here and absent there is walked, read, parsed to nothing, and reported as
    # a clean index. Naming one list makes that state unreachable.
    Setting(
        "index.suffixes",
        "str_list",
        tuple(sorted(EXTENSIONS)),
        affects_build=True,
        members=frozenset(EXTENSIONS),
        help="file suffixes treated as source; only suffixes the parser can read",
    ),
    Setting(
        "index.max_file_bytes",
        "int",
        5 * 1024 * 1024,
        affects_build=True,
        minimum=1024,
        maximum=1024 * 1024 * 1024,
        help="files larger than this are skipped",
    ),
    Setting(
        "embedding.dimensions",
        "int",
        384,
        affects_build=True,
        minimum=32,
        maximum=4096,
        help="vector width; changing it invalidates every vector",
    ),
    # The default keeps the whole pipeline offline and dependency-free. The
    # other value sends each unit's text to an OpenAI-compatible embeddings
    # endpoint, which may be a vendor or a model server on localhost -- one
    # request shape covers both, and the local one keeps source on the machine.
    # Three, and the difference between them is what the vector can know.
    # `signed-feature-hash` is a hash of the same words the lexical half already
    # ranks, so its cosine can reorder but never reach; `sentence-transformers`
    # runs a model on this machine, which is the only one of the three that is
    # both semantic and offline; `openai-compatible` sends text to a service.
    Setting(
        "embedding.provider",
        "str",
        "signed-feature-hash",
        affects_build=True,
        members=frozenset({"signed-feature-hash", "sentence-transformers", "openai-compatible"}),
        help="who computes vectors; the default never opens a socket and needs no dependency",
    ),
    Setting(
        "embedding.endpoint",
        "str",
        "",
        affects_build=True,
        help="OpenAI-compatible embeddings URL, e.g. http://localhost:11434/v1/embeddings",
    ),
    Setting(
        "embedding.model",
        "str",
        "",
        affects_build=True,
        help="model name the endpoint expects; part of what an index records",
    ),
    # The NAME of an environment variable, never a key. Every other setting
    # here is meant to be committed so everyone who clones sees what shaped the
    # index; a credential is the one value with the opposite requirement, so it
    # is the one value this file only points at. `config list` prints whether
    # the variable is set, never what it holds.
    Setting(
        "embedding.api_key_env",
        "str",
        "RAG_YOUR_CODE_API_KEY",
        help="environment variable holding the endpoint's key; empty means no auth header",
    ),
    Setting(
        "embedding.batch",
        "int",
        64,
        minimum=1,
        maximum=512,
        help="units per embeddings request; one request per unit is unusable at scale",
    ),
    Setting("embedding.timeout", "int", 60, minimum=1, maximum=600, help="seconds to wait for one embeddings request"),
    Setting(
        "embedding.retries",
        "int",
        3,
        minimum=0,
        maximum=10,
        help="attempts per request before the build aborts rather than mixing schemes",
    ),
    # Only consulted when the vectors carry real semantics. Under the feature
    # hash a cosine shortlist is noise, and letting it add candidates would
    # dilute a ranking that measured better without it; with a trained model
    # it is the one thing that can make a unit retrievable that shares no word
    # with the query.
    Setting(
        "search.vector_recall",
        "int",
        50,
        minimum=0,
        maximum=500,
        help="units a semantic provider may add to the candidate set by similarity alone",
    ),
    Setting(
        "search.vector_weight",
        "float",
        0.15,
        minimum=0.0,
        maximum=1.0,
        help="how much cosine similarity contributes beside lexical overlap",
    ),
    # How much of a question has to reach the index before an answer counts as
    # evidence rather than as a guess. Measured, not chosen: across two
    # repositories, two languages and every question set under `benchmarks/`,
    # 0.40 is the largest value at which every question that was being answered
    # correctly still is. On its own it silences three fifths of the questions
    # whose answer is not in the repository at all; the rest is what
    # `search.min_concentration` below adds. The command is the claim --
    # `repo_queries --questions benchmarks/absent_queries.json
    # --min-concentration 0` -- because a count typed into a comment is a figure
    # nothing checks, and both numbers this sentence used to carry had rotted.
    # It is a ratio inside the query, so unlike a score threshold it does
    # not move when the corpus or the scale of the ranking does -- the defect
    # that made `confidence_threshold = 0.8` stop meaning anything.
    Setting(
        "search.min_coverage",
        "float",
        0.40,
        minimum=0.0,
        maximum=1.0,
        help="share of a query's words that must appear in the index for results to be returned",
    ),
    # Whether the words that did reach the index reached it *together*. Coverage
    # alone asks whether each word occurs somewhere, and a question about a
    # subject the repository does not implement can satisfy that entirely out of
    # unrelated declarations -- four of six words found in four places with
    # nothing to do with one another or with what was asked. Measured across
    # four rulers, requiring a quarter of a query's rarity to land inside one
    # unit leaves the two rulers over undescribed code unchanged and removes
    # most of what the coverage bar alone still answers; the ablation table
    # carries the numbers, in docs/ROADMAP.md, rather than this line, which
    # said "roughly halves" while that table said an order of magnitude.
    # Rarity-
    # weighted rather than counted, because a unit holding two ordinary words is
    # not better evidence than one holding the rare word the question is about.
    Setting(
        "search.min_concentration",
        "float",
        0.28,
        minimum=0.0,
        maximum=1.0,
        help="share of a query's distinctive weight that must occur within a single unit",
    ),
    Setting("search.limit", "int", 8, minimum=1, maximum=100, help="default result count"),
    Setting("search.max_chars", "int", 12000, minimum=0, maximum=100000, help="default context budget"),
    Setting(
        "agent.max_open_bytes",
        "int",
        5 * 1024 * 1024,
        minimum=1024,
        maximum=1024 * 1024 * 1024,
        help="largest file the agent `open` action will read",
    ),
    Setting(
        "agent.max_open_chars",
        "int",
        100000,
        minimum=1000,
        maximum=10_000_000,
        help="largest source payload one `open` response may carry",
    ),
    Setting(
        "describe.languages",
        "str_list",
        ("en", "zh"),
        help="languages an agent is asked to write unit descriptions in",
    ),
    Setting("describe.batch", "int", 20, minimum=1, maximum=200, help="units per describe_pending response"),
    # 600 was picked before any real corpus existed. Measured against the 119
    # descriptions written for this repository's own src/ tree, the median is
    # 349 characters but the 90th percentile is 662 -- so a 600 cap rejects
    # roughly one good-faith description in eight, and rejects them at the
    # complex units retrieval most needs help with. Nothing is truncated to
    # fit, so a cap set inside the normal range silently leaves those units
    # undescribed. 1000 covers the whole observed range.
    Setting("describe.max_chars", "int", 1000, minimum=40, maximum=4000, help="cap on one stored description"),
)

BY_PATH: dict[str, Setting] = {setting.path: setting for setting in SETTINGS}
TABLES: tuple[str, ...] = tuple(dict.fromkeys(setting.table for setting in SETTINGS))


def _coerce(setting: Setting, value: Any) -> Any:
    """Validate one value against its setting, or raise ConfigError.

    ``bool`` is rejected for the numeric kinds on purpose: it is a subclass of
    ``int`` in Python, so ``max_file_bytes = true`` would otherwise be accepted
    and silently mean one byte.
    """
    if setting.kind == "str_list":
        if not isinstance(value, (list, tuple)) or any(not isinstance(item, str) for item in value):
            raise ConfigError(f"{setting.path} must be a list of strings")
        items = tuple(dict.fromkeys(value))
        if setting.members is not None:
            unknown = [item for item in items if item not in setting.members]
            if unknown:
                raise ConfigError(
                    f"{setting.path}: {', '.join(unknown)} has no parser rules, so files matching it "
                    f"would be read and yield nothing. Supported: {', '.join(sorted(setting.members))}. "
                    f"Adding a language means adding a rule table entry in parser.py."
                )
        return items
    if setting.kind == "str":
        if not isinstance(value, str):
            raise ConfigError(f"{setting.path} must be a string")
        text = value.strip()
        if setting.members is not None and text not in setting.members:
            raise ConfigError(
                f"{setting.path}: {text!r} is not one of {', '.join(sorted(setting.members))}"
            )
        return text
    if setting.kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ConfigError(f"{setting.path} must be an integer")
        number: float = value
    elif setting.kind == "float":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ConfigError(f"{setting.path} must be a number")
        if value != value or value in (float("inf"), float("-inf")):
            raise ConfigError(f"{setting.path} must be finite")
        number = float(value)
    else:  # pragma: no cover - the table above defines every kind in use
        raise ConfigError(f"{setting.path} has an unknown kind {setting.kind!r}")
    if setting.minimum is not None and number < setting.minimum:
        raise ConfigError(f"{setting.path} must be at least {setting.minimum}")
    if setting.maximum is not None and number > setting.maximum:
        raise ConfigError(f"{setting.path} must be at most {setting.maximum}")
    return int(number) if setting.kind == "int" else number


@dataclass(frozen=True, slots=True)
class Config:
    """Resolved settings, addressed by their dotted path."""

    values: dict[str, Any]
    source: Path | None = None

    def __getitem__(self, path: str) -> Any:
        """Reads one resolved setting by its dotted name."""
        return self.values[path]

    @property
    def build_fingerprint(self) -> str:
        """Digest of the settings that determine what an index contains.

        An index built with different suffixes, ignores, size cap or vector
        width is not a stale index -- it is an index of something else. The
        dimension case in particular fails silently otherwise: ``search`` skips
        the cosine term when the widths disagree, so the only symptom of
        searching new-width queries against old vectors is quietly worse
        ranking.
        """
        material = {setting.path: self.values[setting.path] for setting in SETTINGS if setting.affects_build}
        canonical = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=list)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def with_overrides(self, **overrides: Any) -> "Config":
        """Apply explicit arguments on top, ignoring the ones left unset.

        Argparse gives ``None`` for a flag the caller did not pass, and ``None``
        has to mean "no opinion" rather than "set this to nothing", or every
        flag would need a sentinel default duplicating the table above.
        """
        merged = dict(self.values)
        for name, value in overrides.items():
            if value is None:
                continue
            path = name.replace("__", ".")
            setting = BY_PATH.get(path)
            if setting is None:
                raise ConfigError(f"unknown setting {path}")
            merged[path] = _coerce(setting, value)
        return Config(merged, self.source)


def defaults() -> Config:
    """The built-in settings, used when a repository supplies no file of its
    own. They reproduce the previously hardcoded constants exactly, so a
    repository with no configuration behaves identically to before the
    settings layer existed.
    """
    return Config({setting.path: setting.default for setting in SETTINGS})


def config_path(root: Path) -> Path:
    """Where a repository settings file lives: at the repository root, not
    inside the generated artifacts directory. That directory is ignored by
    version control and is what people delete to clear the cache, so
    anything authored there would be both uncommittable and destroyed by the
    obvious cleanup.
    """
    return root / CONFIG_FILENAME


def load(root: Path) -> Config:
    """Read ``rag-your-code.toml`` from a repository root, if it has one."""
    path = config_path(root)
    if not path.is_file():
        return defaults()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"{path.name} is unreadable: {exc}") from exc
    return from_text(text, source=path)


def from_text(text: str, source: Path | None = None) -> Config:
    """Parses settings text and validates every entry against the table,
    starting from the defaults. An unrecognised section or key is refused
    with a message listing what that section actually accepts, so a
    misspelling is caught at load time instead of appearing as a setting
    that mysteriously does nothing.
    """
    parsed = parse_toml(text)
    values: dict[str, Any] = {setting.path: setting.default for setting in SETTINGS}
    for table, entries in parsed.items():
        if table not in TABLES:
            raise ConfigError(f"unknown section [{table}]; known sections are {', '.join(TABLES)}")
        if not isinstance(entries, dict):
            raise ConfigError(f"[{table}] must be a table")
        for key, value in entries.items():
            setting = BY_PATH.get(f"{table}.{key}")
            if setting is None:
                known = ", ".join(item.key for item in SETTINGS if item.table == table)
                raise ConfigError(f"unknown setting {table}.{key}; [{table}] accepts {known}")
            values[setting.path] = _coerce(setting, value)
    return Config(values, source)


# ---------------------------------------------------------------------------
# TOML reading
#
# `tomllib` is standard library from 3.11. On 3.10 the alternative was adding
# `tomli` as a runtime dependency, which would falsify the claim README and
# CONTRIBUTING both make about this package having none. The reader below
# covers the subset the settings table can express -- tables, strings,
# integers, floats, booleans, and arrays of those -- and rejects everything
# else with a line number rather than guessing at it. `tests/test_config.py`
# checks it against `tomllib` on every version that ships one, so the two
# cannot drift apart silently.
# ---------------------------------------------------------------------------

_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "f": "\f", "b": "\b", '"': '"', "\\": "\\"}
_NON_FINITE = {
    "inf": float("inf"), "+inf": float("inf"), "-inf": float("-inf"),
    "nan": float("nan"), "+nan": float("nan"), "-nan": float("nan"),
}


def parse_toml(text: str) -> dict[str, Any]:
    """Reads settings text, using the standard library parser where it exists
    and the built-in fallback reader below it. The fallback exists so that
    supporting older interpreters does not require adding a runtime
    dependency, which would contradict what this package claims about having
    none.
    """
    if sys.version_info >= (3, 11):
        import tomllib

        try:
            return tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"{CONFIG_FILENAME} is not valid TOML: {exc}") from exc
    return parse_toml_subset(text)


def _strip_comment(line: str) -> str:
    """Remove a trailing comment, respecting quotes.

    Splitting on the first ``#`` would corrupt any value containing one, and
    directory names and file suffixes are exactly the kind of value that might.
    """
    quote = ""
    for index, character in enumerate(line):
        if quote:
            if character == quote:
                quote = ""
        elif character in "\"'":
            quote = character
        elif character == "#":
            return line[:index]
    return line


def _parse_string(token: str, line_number: int) -> str:
    """Reads a quoted text value, expanding the standard escape sequences
    including Unicode ones in the escaping form, and leaving the literal
    form untouched as its own rules require. An unsupported or truncated
    escape is refused with its line number rather than guessed at.
    """
    body = token[1:-1]
    if token[0] == "'":
        return body  # A TOML literal string performs no escape processing.
    out: list[str] = []
    index = 0
    while index < len(body):
        character = body[index]
        if character != "\\":
            out.append(character)
            index += 1
            continue
        index += 1
        if index >= len(body):
            raise ConfigError(f"line {line_number}: string ends in an escape")
        code = body[index]
        if code in _ESCAPES:
            out.append(_ESCAPES[code])
            index += 1
        elif code in "uU":
            width = 4 if code == "u" else 8
            digits = body[index + 1 : index + 1 + width]
            if len(digits) != width:
                raise ConfigError(f"line {line_number}: truncated unicode escape")
            try:
                out.append(chr(int(digits, 16)))
            except ValueError as exc:
                raise ConfigError(f"line {line_number}: invalid unicode escape") from exc
            index += 1 + width
        else:
            raise ConfigError(f"line {line_number}: unsupported escape \\{code}")
    return "".join(out)


def _parse_scalar(raw: str, line_number: int) -> Any:
    """Reads one single value: quoted text, a boolean, an integer in any
    supported base, a decimal or exponential number, or the non-finite float
    names. Anything else this reader cannot handle, such as a date or a
    multi-line form, is refused with its line number and a note of what is
    supported, rather than being misread. Recognising the non-finite names
    matters for agreement: omitting them once made this reader refuse a
    value the standard parser accepted, so the same file produced two
    different errors on two interpreters.
    """
    token = raw.strip()
    if not token:
        raise ConfigError(f"line {line_number}: missing value")
    if token[0] in "\"'":
        if len(token) < 2 or token[-1] != token[0]:
            raise ConfigError(f"line {line_number}: unterminated string")
        return _parse_string(token, line_number)
    if token in ("true", "false"):
        return token == "true"
    # TOML floats include the non-finite literals. Omitting them made this
    # reader refuse `nan` as unparseable while `tomllib` accepted it and let
    # the range check reject it, so the two disagreed about the grammar and
    # gave different errors for the same file -- caught only by the 3.10 leg
    # of CI, which is the whole reason that leg exists.
    if token in _NON_FINITE:
        return _NON_FINITE[token]
    cleaned = token.replace("_", "")
    try:
        if any(character in cleaned for character in ".eE") and not cleaned.lower().startswith("0x"):
            return float(cleaned)
        return int(cleaned, 0)
    except ValueError as exc:
        # Everything TOML allows that this reader does not -- dates, times,
        # multi-line strings, inline tables -- lands here. Reporting the line
        # and what is supported beats a stack trace from int().
        raise ConfigError(
            f"line {line_number}: {token!r} is not a value this reader supports. It accepts "
            f"strings, integers, floats, booleans and arrays of those; Python 3.11 and later "
            f"read the full TOML grammar."
        ) from exc


def _split_array(body: str, line_number: int) -> list[str]:
    """Splits a bracketed list into its entries, respecting quotes and nesting
    so that a separator inside a quoted value or an inner list does not
    split it. An unclosed quote or bracket is refused with its line number.
    """
    items: list[str] = []
    current: list[str] = []
    quote = ""
    depth = 0
    for character in body:
        if quote:
            current.append(character)
            if character == quote:
                quote = ""
            continue
        if character in "\"'":
            quote = character
            current.append(character)
        elif character == "[":
            depth += 1
            current.append(character)
        elif character == "]":
            depth -= 1
            current.append(character)
        elif character == "," and depth == 0:
            items.append("".join(current))
            current = []
        else:
            current.append(character)
    if quote or depth:
        raise ConfigError(f"line {line_number}: unterminated array")
    items.append("".join(current))
    return [item for item in items if item.strip()]


def parse_toml_subset(text: str) -> dict[str, Any]:
    """The 3.10 reader. Exported so the differential test can drive it directly."""
    result: dict[str, Any] = {}
    table: dict[str, Any] = result
    pending: list[str] = []
    pending_key = ""
    pending_start = 0
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = _strip_comment(raw_line).strip()
        if pending:
            pending.append(line)
            if "]" in line:
                joined = " ".join(pending)
                body = joined[joined.index("[") + 1 : joined.rindex("]")]
                table[pending_key] = [_parse_scalar(item, pending_start) for item in _split_array(body, pending_start)]
                pending = []
            continue
        if not line:
            continue
        if line.startswith("["):
            if not line.endswith("]"):
                raise ConfigError(f"line {line_number}: unterminated table header")
            name = line[1:-1].strip()
            if not name or name.startswith("["):
                raise ConfigError(f"line {line_number}: this reader supports only simple [table] headers")
            node: dict[str, Any] = result
            for part in name.split("."):
                child = node.setdefault(part.strip().strip('"').strip("'"), {})
                if not isinstance(child, dict):
                    raise ConfigError(f"line {line_number}: {name} is already a value")
                node = child
            table = node
            continue
        if "=" not in line:
            raise ConfigError(f"line {line_number}: expected key = value")
        key, _, value = line.partition("=")
        key = key.strip().strip('"').strip("'")
        value = value.strip()
        if not key:
            raise ConfigError(f"line {line_number}: empty key")
        if value.startswith("{"):
            raise ConfigError(f"line {line_number}: inline tables are not supported by this reader")
        if value.startswith("["):
            if "]" in value:
                body = value[1 : value.rindex("]")]
                table[key] = [_parse_scalar(item, line_number) for item in _split_array(body, line_number)]
            else:
                pending, pending_key, pending_start = [value], key, line_number
            continue
        table[key] = _parse_scalar(value, line_number)
    if pending:
        raise ConfigError(f"line {pending_start}: unterminated array")
    return result


def render_template() -> str:
    """A commented file listing every setting at its default.

    Written by ``rag-your-code config init``. Everything is commented out, so
    the file documents the surface without changing behaviour by existing.
    """
    lines = [
        "# rag-your-code configuration.",
        "# Every value below is the built-in default; uncomment one to change it.",
        "#",
        "# [index] and [embedding] settings determine what the index contains, so",
        "# changing one forces a full rebuild on the next run. The rest take effect",
        "# immediately and never invalidate an index.",
    ]
    for table in TABLES:
        lines.append("")
        lines.append(f"[{table}]")
        for setting in SETTINGS:
            if setting.table != table:
                continue
            if setting.help:
                lines.append(f"# {setting.help}")
            lines.append(f"# {setting.key} = {render_value(setting.default)}")
    return "\n".join(lines) + "\n"


def render_value(value: Any) -> str:
    """Formats one value back into the settings file syntax, for the generated
    template and for writing a changed value back.
    """
    if isinstance(value, (tuple, list)):
        return "[" + ", ".join(json.dumps(item, ensure_ascii=False) for item in value) + "]"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    return repr(value)


def parse_literal(setting: Setting, raw: str) -> Any:
    """Read one command-line value the way the file would read it.

    Routed through the same reader rather than through ``int``/``float``/
    ``split(',')`` so that ``config set`` and an edited file cannot disagree
    about what a value means, and so the same error text explains both.
    """
    parsed = parse_toml(f"{setting.key} = {raw.strip()}")
    return _coerce(setting, parsed[setting.key])


def update_file(path: Path, dotted: str, value: Any) -> None:
    """Set one key in place, preserving comments, order and unrelated tables.

    A round trip through a parser and a serializer would be shorter and would
    silently delete every comment in the file, including the explanations
    ``config init`` writes. So this walks lines: it replaces the key's existing
    assignment where there is one, uncomments the template line where there is
    one, and otherwise inserts under the right table header.
    """
    setting = BY_PATH[dotted]
    rendered = f"{setting.key} = {render_value(value)}"
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else render_template().splitlines()
    table = ""
    active: int | None = None
    commented: int | None = None
    table_end: int | None = None
    for number, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            table = stripped[1:-1].strip()
            continue
        if table != setting.table:
            continue
        table_end = number
        body = stripped.lstrip("#").strip()
        if not body.startswith(f"{setting.key} ") and not body.startswith(f"{setting.key}="):
            continue
        if stripped.startswith("#"):
            commented = number if commented is None else commented
        else:
            active = number
            break
    if active is not None:
        lines[active] = rendered
    elif commented is not None:
        lines[commented] = rendered
    elif table_end is not None:
        lines.insert(table_end + 1, rendered)
    else:
        lines.extend(["", f"[{setting.table}]", rendered])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
