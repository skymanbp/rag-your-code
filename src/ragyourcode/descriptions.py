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

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from .models import CodeUnit

STORE_FILENAME = "rag-your-code.descriptions.json"
SCHEMA = 1


def source_key(unit: CodeUnit) -> str:
    """Digest of the exact text a description was written about."""
    return hashlib.sha256(unit.source.encode("utf-8")).hexdigest()[:16]


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
            path, digest = entry.get("path"), entry.get("hash")
            if not isinstance(path, str) or not isinstance(digest, str):
                continue
            text = entry.get("text")
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
            digest = source_key(unit)
            entry = self.entries.get(unit.id)
            text = entry.get("text") if entry and entry.get("hash") == digest else None
            if text is None:
                text = relocated.get((unit.path, digest))
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

    def pending(self, units: list[CodeUnit], limit: int) -> list[CodeUnit]:
        """Units still needing a description, missing ones before stale ones.

        A unit with no description at all is worth more than a refresh of one
        that exists, so a budget-limited agent spends its first batches where
        retrieval is currently blind.
        """
        groups = self.classify(units)
        return (groups["missing"] + groups["superseded"])[: max(0, limit)]

    def put(self, unit: CodeUnit, text: str) -> None:
        self.entries[unit.id] = {
            "hash": source_key(unit),
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
            live_ids = {unit.id for unit in units}
            live_code = {(unit.path, source_key(unit)) for unit in units}
            self.entries = {
                uid: entry
                for uid, entry in self.entries.items()
                if uid in live_ids or (entry.get("path"), entry.get("hash")) in live_code
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
