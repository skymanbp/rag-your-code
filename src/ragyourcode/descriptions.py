"""Agent-authored unit descriptions.

`annotate.py` says it in its own first line: it describes a unit *without an
LLM*. It humanises the identifier, lists parameter and callee names, and
appends the docstring verbatim -- so it introduces no vocabulary that was not
already in the source. That is precisely why retrieval cannot reach a concept
the author never wrote down: the embedder is a feature hash, so cosine measures
token overlap, and a query sharing no token with a unit scores exactly zero
against it.

The agent already consuming this index can write those words. This module
stores what it writes, keyed by unit id **and a digest of the unit's source**,
so a description can never be applied to code it does not describe. When the
source moves, the entry is retained but not used, and the unit reappears in the
pending queue; incremental indexing means only the units in changed files do.

Stored at the repository root as ``rag-your-code.descriptions.json``, beside
``rag-your-code.toml`` and for the same two reasons: it is authored rather than
generated, and ``.rag-your-code/`` is both ignored by Git and the directory
people delete to clear the cache.

What this is, and is not: it moves the semantic work from query time to index
time. Matching stays lexical. A description saying `retry` still cannot answer
a query saying `resend` unless the description also says `resend`, which is why
the guidance handed to the agent asks for the words a reader would search by
rather than a restatement of the code.
"""

from __future__ import annotations

import ast
import hashlib
import json
import textwrap
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .models import CodeUnit

STORE_FILENAME = "rag-your-code.descriptions.json"
SCHEMA = 1


def source_key(unit: CodeUnit) -> str:
    """Digest of the exact text a description was written about."""
    return hashlib.sha256(unit.source.encode("utf-8")).hexdigest()[:16]


def code_only(source: str, language: str) -> str:
    """A unit's source with its own leading documentation removed.

    The digest above exists to stop a description outliving the code it
    describes. Documentation is not code: adding or rewriting a docstring
    changes nothing about what the function does, so invalidating a
    description over it is the guard firing on a change that cannot make the
    description wrong.

    It fired hardest on the one operation meant to help. Promoting a
    description into the source inserts that very description as a docstring,
    the digest changes, and the entry is dropped -- taking with it whatever
    part of the text was not promoted. Measured on this repository, promoting
    the English half of every bilingual description cost Chinese retrieval
    twenty-eight percent of its hit rate, because the Chinese half had nowhere
    left to live.

    Only Python needs this. Every other supported language writes its
    documentation above the declaration, outside the unit's span, so its
    digest never saw it in the first place -- this makes Python consistent
    with the other fourteen rather than special.
    """
    if language != "python" or ('"""' not in source and "'''" not in source):
        return source
    try:
        # Dedented, because a method's source starts indented and would not
        # parse as a module on its own.
        tree = ast.parse(textwrap.dedent(source))
    except SyntaxError:
        return source
    # Every docstring in the span, not only the leading one. A class's source
    # contains its methods, so a docstring added to a method changed the
    # class's digest and superseded its description -- four of them here, all
    # classes, all for documentation added to something nested inside them.
    drop: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            continue
        if not node.body:
            continue
        first = node.body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
            drop.update(range(first.lineno, (first.end_lineno or first.lineno) + 1))
    if not drop:
        return source
    lines = source.split(chr(10))
    return chr(10).join(line for number, line in enumerate(lines, 1) if number not in drop)


def code_key(unit: CodeUnit) -> str:
    """Digest of a unit's code with its own documentation excluded."""
    return hashlib.sha256(code_only(unit.source, unit.language).encode("utf-8")).hexdigest()[:16]


def guidance(languages: tuple[str, ...] | list[str], max_chars: int) -> str:
    """The instruction handed to the agent with every pending batch.

    It is returned by the protocol rather than living only in SKILL.md so that
    an agent reaching this index through any host receives the same brief, and
    so the brief cannot drift away from the ``describe.*`` settings that shape
    it.
    """
    names = {"en": "English", "zh": "Chinese"}
    written = ", ".join(names.get(code, code) for code in languages)
    return (
        f"Write one description per unit, in {written}, at most {max_chars} characters total. "
        "Retrieval over these descriptions is lexical: a query matches a unit only when they "
        "share words. So write the words a person would search by -- what the unit is for in "
        "domain terms, the operation it performs, the failure it handles, and the obvious "
        "synonyms for each. Do not restate the signature, do not name the parameters, and do "
        "not describe behaviour the source does not show; the source is included so you can "
        "check. If a unit is trivial, say so briefly rather than padding it."
    )


@dataclass(slots=True)
class DescriptionStore:
    """Authored descriptions, addressed by unit id."""

    path: Path
    entries: dict[str, dict]

    @property
    def fingerprint(self) -> str:
        """Digest of the authored text, so an index can tell when it changed.

        Importing descriptions touches no source file, so nothing the index
        tracks moves and it would go on serving the previous text until someone
        happened to rebuild. This is the same failure the configuration
        fingerprint exists to prevent, in a second authored input.
        """
        # An empty store is the empty string rather than the digest of no
        # bytes, so that it equals what `index_descriptions_fingerprint` reads
        # out of an index written before this field existed. Otherwise every
        # index predating 0.4.0 reports itself permanently stale over
        # descriptions that neither it nor the repository has.
        if not self.entries:
            return ""
        digest = hashlib.sha256()
        for uid, entry in sorted(self.entries.items()):
            digest.update(uid.encode("utf-8"))
            digest.update(str(entry.get("hash", "")).encode("utf-8"))
            digest.update(str(entry.get("text", "")).encode("utf-8"))
        return digest.hexdigest()

    def _relocations(self) -> dict[tuple[str, str], str | None]:
        """Stored text addressed by file and code digest rather than by unit id.

        A unit id embeds the line the declaration starts on, so inserting a
        comment or an import near the top of a file changes the id of
        everything below it while changing none of their code. Keyed only by
        id, every description in that file would be orphaned by an edit that
        did not touch a single one of the things they describe -- which is
        what adding a seven-line comment to config.py did to nineteen of them.

        The digest already answers "is this the same code?"; this uses it to
        answer "where did that code go?" as well. Two units in one file with
        byte-identical source and different stored text are ambiguous, and map
        to nothing rather than to a guess.
        """
        table: dict[tuple[str, str], str | None] = {}
        for entry in self.entries.values():
            path = entry.get("path")
            if not isinstance(path, str):
                continue
            text = entry.get("text")
            # Indexed under both digests, so a unit that both moved and gained
            # a docstring is still found. An entry written before the
            # documentation-excluded digest existed simply has one of them.
            for digest in (entry.get("hash"), entry.get("code_hash")):
                if not isinstance(digest, str):
                    continue
                key = (path, digest)
                if key in table and table[key] != text:
                    table[key] = None
                else:
                    table.setdefault(key, text)
        return table

    def applicable(self, units: list[CodeUnit]) -> dict[str, str]:
        """Descriptions whose digest still matches the unit they describe."""
        relocated = self._relocations()
        usable: dict[str, str] = {}
        for unit in units:
            # The full-source digest first, because it is one hash and it hits
            # for every unit whose file did not change -- which, with
            # incremental indexing, is nearly all of them. The
            # documentation-excluded digest costs a parse and is computed only
            # when the cheap one has already missed, so the parse is paid once
            # per genuinely changed unit rather than once per unit per run.
            entry = self.entries.get(unit.id)
            plain = source_key(unit)
            text = entry.get("text") if entry and entry.get("hash") == plain else None
            if text is None:
                text = relocated.get((unit.path, plain))
            if text is None:
                stripped = code_key(unit)
                if entry and entry.get("code_hash") == stripped:
                    text = entry.get("text")
                else:
                    text = relocated.get((unit.path, stripped))
            if isinstance(text, str) and text.strip():
                usable[unit.id] = text
        return usable

    def classify(self, units: list[CodeUnit]) -> dict[str, list[CodeUnit]]:
        """Split units into described / superseded / missing.

        ``superseded`` is the interesting one: something was written about this
        declaration and the code has since changed, so it is deliberately not
        applied. It is distinguished from ``missing`` by name rather than by
        id, for the same reason applicability is: an id changes when the lines
        above it do.
        """
        usable = self.applicable(units)
        written = {(entry.get("path"), entry.get("name")) for entry in self.entries.values()}
        described: list[CodeUnit] = []
        superseded: list[CodeUnit] = []
        missing: list[CodeUnit] = []
        for unit in units:
            if unit.id in usable:
                described.append(unit)
            elif self.entries.get(unit.id) or (unit.path, unit.qualified_name) in written:
                superseded.append(unit)
            else:
                missing.append(unit)
        return {"described": described, "superseded": superseded, "missing": missing}

    def pending(
        self, units: list[CodeUnit], limit: int, skip: "tuple[str, ...] | list[str]" = ()
    ) -> list[CodeUnit]:
        """Units still needing a description, missing ones before stale ones.

        A unit with no description at all is worth more than a refresh of one
        that exists, so a budget-limited agent spends its first batches where
        retrieval is currently blind.

        ``skip`` withholds the units a repository has measured describing as
        harmful. Offering them is not neutral: an agent following the describe
        command works the queue to the end, so a queue that lists them is an
        instruction to make retrieval worse. The count is reported by
        `declined`, because a silently shortened queue reads as "nothing left".
        """
        groups = self.classify(units)
        queue = groups["missing"] + groups["superseded"]
        withheld = self.declined(queue, skip)
        return [unit for unit in queue if unit not in withheld][: max(0, limit)]

    @staticmethod
    def declined(units: list[CodeUnit], skip: "tuple[str, ...] | list[str]") -> list[CodeUnit]:
        """The units `skip` withholds, so they can be counted rather than lost.

        A pattern is tried against the file and against ``path::name``, so a
        repository can withhold a directory or a single declaration. The second
        form exists because the measurement that produced it was about one
        declaration: `parser.py::_generic_units` carries a docstring that
        already reads like a description, and an authored one *replaces* the
        generated sentence -- the only route by which that docstring reaches
        the weight-3 description field. Three separate attempts to describe it,
        long and short, each cost graded questions and none gained any.

        Matched with `PurePosixPath.match` rather than `fnmatch`, whose `*`
        crosses a directory separator: `tests/*.py` would otherwise also
        withhold `tests/fixtures/**`, and describing the parser fixtures was
        measured to cost nothing at all.
        """
        if not skip:
            return []
        withheld = []
        for unit in units:
            path = unit.path.replace("\\", "/")
            named = f"{path}::{unit.qualified_name}"
            if any(PurePosixPath(path).match(p) or PurePosixPath(named).match(p) for p in skip):
                withheld.append(unit)
        return withheld

    def put(self, unit: CodeUnit, text: str) -> None:
        """Saves one written description together with the file it came from,
        its qualified name, and two digests of the code: the whole source,
        and the source with documentation excluded. The second is what keeps
        the entry alive when a docstring is added, including one promoted
        from this very description. An entry written before that field
        existed keeps working through the first alone, so no store needs
        migrating.
        """
        self.entries[unit.id] = {
            "hash": source_key(unit),
            # Recorded alongside so that adding a docstring -- including one
            # promoted from this very description -- does not discard the
            # entry. An entry written before this field existed keeps working
            # through `hash` alone, so no store needs migrating.
            "code_hash": code_key(unit),
            "path": unit.path,
            "name": unit.qualified_name,
            "text": text,
        }

    def save(self, units: list[CodeUnit] | None = None) -> None:
        """Write the store, dropping entries for units that no longer exist.

        Pruning needs the full unit list to be safe, so it only happens when a
        caller supplies one; a partial list would silently discard the
        descriptions of everything it omitted.

        An entry is kept when its id is still live *or* its code is, since a
        declaration that merely moved down the file has a new id and the same
        digest. Pruning on ids alone would have deleted exactly the entries
        the relocation lookup exists to rescue.
        """
        if units is not None:
            # Entries written before the documentation-excluded digest existed
            # carry only the full-source one. Filling it in here costs one
            # parse per entry, once, and only for entries that currently match
            # -- which means the source is unchanged and the derived digest is
            # certainly the right one. The store upgrades itself on any write
            # rather than needing a migration somebody has to remember.
            by_id = {unit.id: unit for unit in units}
            # Also by file and digest, because an entry whose declaration moved
            # applies through the relocation lookup and is no longer findable
            # by its stored id -- which was two thirds of them here.
            by_code = {(unit.path, source_key(unit)): unit for unit in units}
            for uid, entry in self.entries.items():
                if "code_hash" in entry:
                    continue
                unit = by_id.get(uid)
                if unit is None or entry.get("hash") != source_key(unit):
                    unit = by_code.get((entry.get("path"), entry.get("hash")))
                if unit is not None:
                    entry["code_hash"] = code_key(unit)
            live_ids = {unit.id for unit in units}
            live_code = {(unit.path, source_key(unit)) for unit in units}
            live_code |= {(unit.path, code_key(unit)) for unit in units}
            self.entries = {
                uid: entry
                for uid, entry in self.entries.items()
                if uid in live_ids
                or (entry.get("path"), entry.get("hash")) in live_code
                or (entry.get("path"), entry.get("code_hash")) in live_code
            }
        payload = {
            "schema": SCHEMA,
            "descriptions": dict(sorted(self.entries.items())),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_name(f"{self.path.name}.tmp")
        with temp.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=False)
            stream.write("\n")
        temp.replace(self.path)


def index_descriptions_fingerprint(payload: dict) -> str:
    """The descriptions digest an index was published with.

    An index written before 0.4.0 has no such key, which means the same thing
    as an empty store: no authored description was applied.
    """
    stored = payload.get("descriptions_fingerprint")
    return stored if isinstance(stored, str) else ""


def store_path(root: Path) -> Path:
    """Where the written descriptions live: at the repository root beside the
    settings file, not inside the generated artifacts directory, because
    they are authored work that must survive a cache clear and must be
    committable.
    """
    return root / STORE_FILENAME


def load(root: Path) -> DescriptionStore:
    """Read the store, treating an unusable file as empty rather than fatal.

    This file is committed, so it will meet merge conflicts and hand-editing. A
    malformed one costs retrieval quality, which is recoverable by describing
    again; refusing to search until it is repaired would not be.
    """
    path = store_path(root)
    entries: dict[str, dict] = {}
    if path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            stored = payload.get("descriptions") if isinstance(payload, dict) else None
            if isinstance(stored, dict):
                entries = {
                    str(uid): entry
                    for uid, entry in stored.items()
                    if isinstance(entry, dict) and isinstance(entry.get("text"), str)
                }
        except (OSError, ValueError):
            entries = {}
    return DescriptionStore(path, entries)
