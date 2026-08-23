"""Repository walking and index construction."""

from __future__ import annotations

import hashlib
import json
import os
import struct
import sys
import time
from array import array
from dataclasses import replace
from pathlib import Path

from .annotate import comment_for
from .embeddings import DEFAULT_DIMENSIONS, embed, embedding_metadata
from .models import CodeUnit
from .parser import parse_file

DEFAULT_IGNORES = {".git", ".hg", ".svn", ".venv", "venv", "node_modules", "dist", "build", "__pycache__", ".rag-your-code"}
SOURCE_SUFFIXES = {".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java", ".c", ".h", ".cpp", ".cc", ".php", ".rb", ".swift", ".kt", ".kts", ".cs", ".scala", ".sh", ".bash"}
MAX_SOURCE_BYTES = 5 * 1024 * 1024


class StaleMonitor:
    """Rate-limit repository stat walks while allowing forced checks."""

    def __init__(self, root: Path, payload: dict, interval_seconds: float = 1.0, assume_checked: bool = False):
        self.root = root
        self.payload = payload
        self.interval_seconds = max(0.0, interval_seconds)
        self.last_checked = time.monotonic() if assume_checked else 0.0
        self.value = bool(payload.get("stale", True))

    def check(self, force: bool = False) -> bool:
        now = time.monotonic()
        if not force and self.last_checked and now - self.last_checked < self.interval_seconds:
            return self.value
        try:
            stored_stats = self.payload.get("file_stats")
            self.value = stored_stats != file_stats(self.root) if isinstance(stored_stats, dict) else self.payload.get("fingerprint") != fingerprint(self.root)
        except OSError:
            self.value = True
        self.last_checked = now
        self.payload["stale"] = self.value
        return self.value


def iter_source_files(root: Path, ignores: set[str] | None = None):
    ignored = DEFAULT_IGNORES | (ignores or set())
    for directory, dirs, files in os.walk(root):
        dirs[:] = sorted(name for name in dirs if name not in ignored and not name.startswith("."))
        for filename in sorted(files):
            path = Path(directory) / filename
            if path.suffix.lower() not in SOURCE_SUFFIXES or path.is_symlink():
                continue
            try:
                if path.stat().st_size > MAX_SOURCE_BYTES:
                    continue
            except OSError:
                continue
            yield path


def file_fingerprints(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in iter_source_files(root):
        digest = hashlib.sha256()
        try:
            digest.update(path.read_bytes())
        except OSError:
            continue
        result[path.relative_to(root).as_posix()] = digest.hexdigest()
    return result


def file_stats(root: Path) -> dict[str, list[int]]:
    result: dict[str, list[int]] = {}
    for path in iter_source_files(root):
        try:
            stat = path.stat()
        except OSError:
            continue
        result[path.relative_to(root).as_posix()] = [stat.st_size, stat.st_mtime_ns]
    return result


def _assign_global_serials(units: list[CodeUnit], previous: dict[str, int] | None = None) -> None:
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
) -> list[CodeUnit]:
    """Build units, reusing unchanged files and stable serials when possible."""
    current_files = file_fingerprints(root)
    old_by_path = {}
    for unit in previous_units or []:
        old_by_path.setdefault(unit.path, []).append(unit)
    units: list[CodeUnit] = []
    for path in iter_source_files(root):
        relative = path.relative_to(root).as_posix()
        if previous_files and previous_files.get(relative) == current_files.get(relative) and relative in old_by_path:
            units.extend(replace(unit) for unit in old_by_path[relative])
        else:
            units.extend(parse_file(path, root, diagnostics))
    previous_serials = {unit.id: unit.serial for unit in previous_units or []}
    _assign_global_serials(units, previous_serials)
    for unit in units:
        # Embed the numbered sidecar comment together with source/context so
        # semantic retrieval is grounded in the same records users can review.
        if previous_serials.get(unit.id, unit.serial) != unit.serial:
            unit.vector = []
        if not unit.vector:
            unit.vector = embed(comment_for(unit.description, unit.serial, unit.id) + "\n" + unit.searchable_text)
    return sorted(units, key=lambda item: (item.serial, item.id))


def fingerprint(root: Path) -> str:
    return _fingerprint_files(file_fingerprints(root))


def _fingerprint_files(files: dict[str, str]) -> str:
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
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    files = file_fingerprints(root)
    repository_fingerprint = _fingerprint_files(files)
    dimensions = len(units[0].vector) if units and units[0].vector else DEFAULT_DIMENSIONS
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
        "files": files,
        "file_stats": file_stats(root),
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
        dimensions = int(vector_store.get("dimensions", payload.get("dimensions", DEFAULT_DIMENSIONS)))
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
