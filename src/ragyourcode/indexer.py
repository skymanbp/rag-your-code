"""Repository walking and index construction."""

from __future__ import annotations

import hashlib
import json
import os
import struct
import sys
import time
from array import array
from dataclasses import dataclass, replace
from pathlib import Path

from . import config as config_module
from .annotate import comment_for
from .config import Config
from .descriptions import DescriptionStore, index_descriptions_fingerprint
from .embeddings import embed, embedding_metadata
from .models import CodeUnit
from .parser import PARSER_FINGERPRINT, parse_file

# These names predate the configuration layer and several tests import them.
# They are derived from the settings table rather than restated, so there is
# still exactly one place a default is written down.
DEFAULT_IGNORES = set(config_module.BY_PATH["index.ignore"].default)
SOURCE_SUFFIXES = set(config_module.BY_PATH["index.suffixes"].default)
MAX_SOURCE_BYTES = config_module.BY_PATH["index.max_file_bytes"].default


def _resolve(root: Path, cfg: Config | None) -> Config:
    """Fall back to the repository's own configuration file.

    Callers that do not pass one get the same settings the CLI would use, so a
    library caller and a command line invocation cannot disagree about which
    files are source.
    """
    return cfg if cfg is not None else config_module.load(root)


class StaleMonitor:
    """Rate-limit repository stat walks while allowing forced checks."""

    def __init__(
        self,
        root: Path,
        payload: dict,
        interval_seconds: float = 1.0,
        assume_checked: bool = False,
        cfg: Config | None = None,
        descriptions_fingerprint: str | None = None,
    ):
        """Prepares the freshness check and settles up front whether the rules
        that built the index have changed since it was published. Neither
        the settings file, nor the written descriptions, nor the parser is
        itself an indexed source file, so no amount of walking the tree
        could notice a change in any of them: different suffixes or size
        caps mean the index describes a different set of files, a different
        parser means its units were carved out differently, and different
        descriptions mean it serves wording nobody wrote any more. All of
        them make it out of date regardless of what the file scan reports.
        """
        self.root = root
        self.payload = payload
        self.cfg = _resolve(root, cfg)
        self.interval_seconds = max(0.0, interval_seconds)
        self.last_checked = time.monotonic() if assume_checked else 0.0
        # Neither authored input is an indexed source, so nothing in the
        # file-stat comparison below can see either one change. An index built
        # under different suffixes, ignores or vector width describes a
        # different corpus; an index built from different descriptions serves
        # text nobody wrote any more. Both are stale regardless of the walk.
        self.config_changed = index_build_fingerprint(payload) != build_fingerprint(self.cfg)
        self.inputs_changed = self.config_changed or (
            descriptions_fingerprint is not None and index_descriptions_fingerprint(payload) != descriptions_fingerprint
        )
        self.value = self.inputs_changed or bool(payload.get("stale", True))

    def check(self, force: bool = False) -> bool:
        """Reports whether anything has changed, comparing recorded file sizes
        and modification times against the repository as it now is, and
        answering from the previous result when asked again within the
        rate-limit window. A changed authored input short-circuits to out of
        date immediately. A directory that cannot be read is treated as
        changed, since not knowing is not the same as knowing nothing moved.
        """
        if self.inputs_changed:
            self.payload["stale"] = True
            return True
        now = time.monotonic()
        if not force and self.last_checked and now - self.last_checked < self.interval_seconds:
            return self.value
        try:
            stored_stats = self.payload.get("file_stats")
            if isinstance(stored_stats, dict):
                self.value = stored_stats != file_stats(self.root, self.cfg)
            else:
                self.value = self.payload.get("fingerprint") != fingerprint(self.root, self.cfg)
        except OSError:
            self.value = True
        self.last_checked = now
        self.payload["stale"] = self.value
        return self.value


def build_fingerprint(cfg: Config) -> str:
    """Digest of everything that decides what a unit *is*.

    Two inputs, one question. The settings under ``[index]`` and
    ``[embedding]`` decide which files are read and how wide a vector is; the
    parser decides what counts as a declaration and where it ends. Units
    produced under either a different configuration or a different parser are
    not stale units of this repository, they are units of something else, and
    the action in both cases is identical: discard them.

    Keeping them as two fields would mean two comparisons, two report flags and
    two chances to add a third input and forget one. The parser was that third
    input, and it went unrecorded for three releases: reuse is keyed on the
    file's bytes, but cached units are a function of the bytes *and* the code
    that parsed them, so upgrading the parser left every unchanged file
    carrying units the old one produced until that file happened to change.
    """
    material = f"{cfg.build_fingerprint}:{PARSER_FINGERPRINT}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def index_build_fingerprint(payload: dict) -> str:
    """The build fingerprint an index was published with.

    An index written before this field existed returns the empty string, which
    matches no current fingerprint and so forces one full rebuild on upgrade.
    That is the correct reading rather than a cost to avoid: such an index was
    built by a different parser, and its units are exactly what a rebuild is
    for.
    """
    stored = payload.get("build_fingerprint")
    return stored if isinstance(stored, str) else ""


def iter_source_files(root: Path, cfg: Config | None = None):
    """Walks a repository and yields the files that count as source, skipping
    configured directories, hidden ones, unsupported suffixes, anything
    above the size cap, and symbolic links. Links are skipped so a link
    pointing outside the repository cannot pull foreign files into the
    index.
    """
    cfg = _resolve(root, cfg)
    ignored = set(cfg["index.ignore"])
    suffixes = {suffix.lower() for suffix in cfg["index.suffixes"]}
    max_bytes = cfg["index.max_file_bytes"]
    for directory, dirs, files in os.walk(root):
        dirs[:] = sorted(name for name in dirs if name not in ignored and not name.startswith("."))
        for filename in sorted(files):
            path = Path(directory) / filename
            if path.suffix.lower() not in suffixes or path.is_symlink():
                continue
            try:
                if path.stat().st_size > max_bytes:
                    continue
            except OSError:
                continue
            yield path


@dataclass(frozen=True, slots=True)
class RepositorySnapshot:
    """One walk of the repository, shared by parsing and by publication.

    Parsing from one walk while publishing hashes from a second is what let an
    index record a file's NEW hash beside units parsed from its OLD content: a
    save landing between the two walks was invisible, `fingerprint` then
    reported the index fresh, and every later incremental run reused the stale
    units forever. Taking the snapshot once removes the window rather than
    narrowing it, and drops a run from four tree walks to two.
    """

    paths: tuple[Path, ...]
    fingerprints: dict[str, str]
    stats: dict[str, list[int]]

    @property
    def fingerprint(self) -> str:
        """A single digest standing for the whole repository content at the
        moment it was read.
        """
        return _fingerprint_files(self.fingerprints)


def snapshot_repository(root: Path, cfg: Config | None = None) -> RepositorySnapshot:
    """Hash, stat and collect every source file in a single pass."""
    paths: list[Path] = []
    fingerprints: dict[str, str] = {}
    stats: dict[str, list[int]] = {}
    for path in iter_source_files(root, cfg):
        try:
            stat = path.stat()
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            # A file that vanished or became unreadable between the walk and the
            # read simply is not in this snapshot. Recording a half-read entry
            # would reintroduce exactly the parse/publish mismatch this type exists
            # to prevent.
            continue
        relative = path.relative_to(root).as_posix()
        paths.append(path)
        fingerprints[relative] = digest
        stats[relative] = [stat.st_size, stat.st_mtime_ns]
    return RepositorySnapshot(tuple(paths), fingerprints, stats)


def file_fingerprints(root: Path, cfg: Config | None = None) -> dict[str, str]:
    """The content hash of every source file, used to decide which files can be
    reused unchanged on the next run.
    """
    return snapshot_repository(root, cfg).fingerprints


def file_stats(root: Path, cfg: Config | None = None) -> dict[str, list[int]]:
    """Size and mtime only -- deliberately NOT routed through the snapshot.

    StaleMonitor asks "has anything changed?" many times per session and needs
    no content consistency with a parse. Routing it through snapshot_repository
    made every stale check SHA-256 the whole repository, which measured a 2.5x
    regression (69 ms -> 172 ms at 10k units).
    """
    result: dict[str, list[int]] = {}
    for path in iter_source_files(root, cfg):
        try:
            stat = path.stat()
        except OSError:
            # A file that disappeared mid-walk is simply absent from this
            # reading; the next check will see the directory as it then is.
            continue
        result[path.relative_to(root).as_posix()] = [stat.st_size, stat.st_mtime_ns]
    return result


def _assign_global_serials(units: list[CodeUnit], previous: dict[str, int] | None = None) -> None:
    """Gives every unit a repository-wide number, keeping the number a unit
    already had so that references written down in an earlier session still
    point at the same code. New units take the lowest numbers not already in
    use.
    """
    previous = previous or {}
    used: set[int] = set()
    assigned: set[str] = set()
    next_serial = max(previous.values(), default=0) + 1
    for unit in sorted(units, key=lambda item: (item.path, item.start_line, item.qualified_name, item.id)):
        old = previous.get(unit.id)
        if old is not None and old > 0 and old not in used:
            unit.serial = old
            used.add(old)
            assigned.add(unit.id)
    for unit in sorted(units, key=lambda item: (item.path, item.start_line, item.qualified_name, item.id)):
        if unit.id in assigned:
            continue
        while next_serial in used:
            next_serial += 1
        unit.serial = next_serial
        used.add(next_serial)
        next_serial += 1


def build_units(
    root: Path,
    previous_units: list[CodeUnit] | None = None,
    previous_files: dict[str, str] | None = None,
    diagnostics: list[dict] | None = None,
    snapshot: RepositorySnapshot | None = None,
    cfg: Config | None = None,
    previous_build: str | None = None,
    descriptions: "DescriptionStore | None" = None,
) -> list[CodeUnit]:
    """Build units, reusing unchanged files and stable serials when possible.

    Pass the same ``snapshot`` to ``write_index`` so the hashes published
    describe exactly the bytes these units were parsed from.

    ``previous_build`` is the fingerprint the previous index was published
    with. When it disagrees, the previous units were produced under different
    rules -- different suffixes, ignores, size cap, vector width, or a
    different parser -- so they are discarded rather than reused. Reuse is
    keyed on file content, which cannot notice that the rules changed.
    """
    cfg = _resolve(root, cfg)
    if previous_build is not None and previous_build != build_fingerprint(cfg):
        previous_units, previous_files = None, None
    dimensions = cfg["embedding.dimensions"]
    snapshot = snapshot or snapshot_repository(root, cfg)
    current_files = snapshot.fingerprints
    old_by_path: dict[str, list[CodeUnit]] = {}
    for unit in previous_units or []:
        old_by_path.setdefault(unit.path, []).append(unit)
    units: list[CodeUnit] = []
    for path in snapshot.paths:
        relative = path.relative_to(root).as_posix()
        if previous_files and previous_files.get(relative) == current_files.get(relative) and relative in old_by_path:
            units.extend(replace(unit) for unit in old_by_path[relative])
        else:
            units.extend(parse_file(path, root, diagnostics))
    previous_serials = {unit.id: unit.serial for unit in previous_units or []}
    _assign_global_serials(units, previous_serials)
    # Authored descriptions are checked against the units they describe, which
    # is why the store is filtered here rather than by the caller: the digest
    # comparison needs the parsed units, and the parsed units do not exist
    # until this point.
    authored = descriptions.applicable(units) if descriptions is not None else {}
    for unit in units:
        # The generated description is replaced before the vector is computed.
        # `description` is part of `searchable_text`, so embedding first would
        # produce a vector for the sentence the agent replaced.
        text = authored.get(unit.id)
        if text and unit.description != text:
            unit.description = text
            unit.vector = []
        if previous_serials.get(unit.id, unit.serial) != unit.serial or len(unit.vector) != dimensions:
            unit.vector = []
        if not unit.vector:
            # Embed the numbered sidecar comment together with source/context so
            # retrieval is grounded in the same records users can review.
            unit.vector = embed(comment_for(unit.description, unit.serial, unit.id) + "\n" + unit.searchable_text, dimensions)
    return sorted(units, key=lambda item: (item.serial, item.id))


def fingerprint(root: Path, cfg: Config | None = None) -> str:
    """A single digest standing for the whole repository content right now,
    used to tell a published index apart from the current state.
    """
    return _fingerprint_files(file_fingerprints(root, cfg))


def _fingerprint_files(files: dict[str, str]) -> str:
    """Combines per-file hashes into one repository-wide digest in a fixed
    order, so the same content always yields the same value.
    """
    digest = hashlib.sha256()
    for relative, file_hash in sorted(files.items()):
        digest.update(relative.encode())
        digest.update(file_hash.encode())
    return digest.hexdigest()


def write_index(
    path: Path,
    root: Path,
    units: list[CodeUnit],
    graph: dict | None = None,
    compact: bool = False,
    diagnostics: list[dict] | None = None,
    snapshot: RepositorySnapshot | None = None,
    cfg: Config | None = None,
    descriptions_fingerprint: str | None = None,
) -> None:
    """Publishes the index atomically: vector data goes to a content-addressed
    side file first, then the readable metadata is swapped into place in one
    step, so a reader never sees a half-written index. Alongside the content
    hashes it records digests of the two authored inputs, the settings and
    the descriptions, and of the rules that built the units, because none of
    those is an indexed file and a change in any of them would otherwise be
    invisible. Compact storage moves vectors out of verbose text numbers
    into a binary side file while the metadata stays readable.
    """
    cfg = _resolve(root, cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    snapshot = snapshot or snapshot_repository(root, cfg)
    files = snapshot.fingerprints
    repository_fingerprint = snapshot.fingerprint
    dimensions = len(units[0].vector) if units and units[0].vector else cfg["embedding.dimensions"]
    serialized_units = [unit.to_dict(include_vector=not compact) for unit in units]
    vector_store = None
    if compact and units:
        vector_temp = path.with_name(f"{path.stem}.vectors.{os.getpid()}.tmp")
        vector_digest = hashlib.sha256()
        with vector_temp.open("wb") as stream:
            for unit in units:
                vector = unit.vector or [0.0] * dimensions
                if len(vector) != dimensions:
                    raise ValueError("all vectors must have the same dimensions")
                packed = struct.pack(f"<{dimensions}f", *vector)
                vector_digest.update(packed)
                stream.write(packed)
        vector_path = path.with_name(
            f"{path.stem}.{repository_fingerprint[:8]}.{vector_digest.hexdigest()[:16]}.vectors.bin"
        )
        vector_temp.replace(vector_path)
        vector_store = {
            "path": vector_path.name,
            "dimensions": dimensions,
            "dtype": "float32-le",
            "count": len(units),
        }
    payload = {
        "schema": 2,
        "root": str(root.resolve()),
        "fingerprint": repository_fingerprint,
        "build_fingerprint": build_fingerprint(cfg),
        "descriptions_fingerprint": descriptions_fingerprint,
        "files": files,
        "file_stats": snapshot.stats,
        "dimensions": dimensions,
        "embedding": embedding_metadata(dimensions),
        "units": serialized_units,
        "graph": graph or {"edges": []},
        "diagnostics": diagnostics or [],
    }
    if vector_store:
        payload["vector_store"] = vector_store
    index_temp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    with index_temp.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
    index_temp.replace(path)
    _remove_superseded_vectors(path, vector_store["path"] if vector_store else None)


def _remove_superseded_vectors(path: Path, active_name: str | None) -> None:
    """Delete this index's own outdated vector sidecars.

    The set of files to remove is derived from the naming scheme ``write_index``
    itself uses (``<stem>.<fingerprint>.<digest>.vectors.bin``) and never from a
    path read back out of the index being replaced. That index lives inside the
    repository being scanned, so a repository can ship one; trusting its
    ``vector_store.path`` turned publication into an arbitrary in-tree delete.
    Enumerating instead of trusting also reclaims sidecars orphaned by an
    earlier run whose index.json was unreadable or absent.
    """
    prefix, suffix = f"{path.stem}.", ".vectors.bin"
    try:
        candidates = list(path.parent.iterdir())
    except OSError:
        # The directory was just written to successfully, so an unreadable
        # parent here means a concurrent removal. Cleanup is best-effort by
        # design; the freshly published index is already valid without it.
        return
    for candidate in candidates:
        if candidate.name == active_name or not candidate.name.startswith(prefix) or not candidate.name.endswith(suffix):
            continue
        try:
            candidate.unlink()
        except OSError:
            # Sidecars are content-addressed, so one that cannot be unlinked
            # (a concurrent reader holding it open on Windows) is inert: no
            # index points at it. Leaking a file beats failing the publish.
            continue


def read_index(path: Path) -> tuple[dict, list[CodeUnit]]:
    """Loads a published index back into memory, attaching vectors from the
    compact side file when one is used. Everything about that side file is
    verified before it is trusted: it must sit inside the index directory,
    its declared width must be within bounds, and its length must match the
    number of units. Any failure degrades to metadata without vectors and
    says so explicitly, rather than raising, so a damaged side file costs
    ranking quality instead of availability.
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("index root must be a JSON object")
    stored_units = payload.get("units", [])
    if not isinstance(stored_units, list) or any(not isinstance(item, dict) for item in stored_units):
        raise ValueError("index units must be a list of objects")
    raw_units = [dict(item) for item in stored_units]
    vector_store = payload.get("vector_store")
    payload["degraded"] = None
    if isinstance(vector_store, dict):
        vector_path = (path.parent / str(vector_store.get("path", ""))).resolve()
        dimensions = int(vector_store.get("dimensions", payload.get("dimensions", 384)))
        count = len(raw_units)
        try:
            vector_path.relative_to(path.parent.resolve())
            if not 32 <= dimensions <= 4096:
                raise ValueError("invalid vector dimensions")
            raw_vectors = vector_path.read_bytes()
            expected = count * dimensions * 4
            if len(raw_vectors) != expected:
                raise ValueError("vector sidecar length does not match index")
            if sys.byteorder == "little":
                values = memoryview(raw_vectors).cast("f")
            else:  # The sidecar contract is explicitly little-endian.
                native_values = array("f")
                native_values.frombytes(raw_vectors)
                native_values.byteswap()
                values = memoryview(native_values)
            for index, item in enumerate(raw_units):
                start = index * dimensions
                item["vector"] = values[start : start + dimensions]
        except (OSError, ValueError, struct.error):
            payload["degraded"] = "vector_store_unavailable"
            for item in raw_units:
                item["vector"] = []
    return payload, [CodeUnit.from_dict(item) for item in raw_units]
