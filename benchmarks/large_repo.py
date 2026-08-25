"""Generate and measure a deterministic synthetic large repository.

This does not pretend to be a production-scale benchmark, but it exposes the
asymptotic behavior of the current JSON index and incremental reuse path.
"""

from __future__ import annotations

import argparse
import ctypes
import gc
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

try:
    import resource
except ImportError:  # pragma: no cover - Windows does not expose resource
    resource = None

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ragyourcode.indexer import StaleMonitor, build_units, file_stats, read_index, write_index  # noqa: E402
from ragyourcode.search import build_search_index, search  # noqa: E402


def _memory_mb():
    if resource is not None:
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        peak = rss / (1024 * 1024) if sys.platform == "darwin" else rss / 1024
        return None, peak
    if sys.platform == "win32":
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
            ]
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        if psapi.GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            return counters.WorkingSetSize / (1024 * 1024), counters.PeakWorkingSetSize / (1024 * 1024)
    return None, None


def _max_rss_mb():
    return _memory_mb()[1]


def create_repo(root: Path, files: int, functions: int) -> None:
    for index in range(files):
        body = [f"def function_{index}_{offset}(value):\n    return value + {offset}\n" for offset in range(functions)]
        (root / f"module_{index:04d}.py").write_text("\n".join(body), encoding="utf-8")


def measure(root: Path, files: int, functions: int) -> dict[str, object]:
    create_repo(root, files, functions)
    index_path = root / ".rag-your-code" / "index.json"
    start = time.perf_counter()
    full_units = build_units(root)
    full_ms = (time.perf_counter() - start) * 1000
    write_start = time.perf_counter()
    write_index(index_path, root, full_units)
    json_write_ms = (time.perf_counter() - write_start) * 1000
    readable_bytes = index_path.stat().st_size
    compact_write_start = time.perf_counter()
    write_index(index_path, root, full_units, compact=True)
    compact_write_ms = (time.perf_counter() - compact_write_start) * 1000
    compact_payload = json.loads(index_path.read_text(encoding="utf-8"))
    compact_bytes = index_path.stat().st_size + (index_path.parent / compact_payload["vector_store"]["path"]).stat().st_size
    isolated = json.loads(
        subprocess.run(
            [sys.executable, "-m", "benchmarks.measure_index", str(index_path)],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )
    full_unit_count = len(full_units)
    del full_units
    gc.collect()
    load_start = time.perf_counter()
    payload, old_units = read_index(index_path)
    compact_load_ms = (time.perf_counter() - load_start) * 1000
    touched = root / "module_0000.py"
    touched.write_text(touched.read_text(encoding="utf-8") + "\ndef added(value):\n    return value\n", encoding="utf-8")
    start = time.perf_counter()
    incremental_units = build_units(root, previous_units=old_units, previous_files=payload["files"])
    incremental_ms = (time.perf_counter() - start) * 1000
    search_index_start = time.perf_counter()
    search_index = build_search_index(incremental_units)
    search_index_ms = (time.perf_counter() - search_index_start) * 1000
    target_file = min(files - 1, 250)
    target_function = min(functions - 1, 10)
    query = f"function {target_file} {target_function}"
    # Warm up before sampling, and take enough samples that the estimator is
    # sharper than the differences it is used to judge. Ten cold samples of a
    # sub-millisecond call once made an unchanged query path look like a real
    # regression across three runs; a warmed 200-sample probe put the two
    # trees within noise and reversed which was faster between rounds.
    for _ in range(20):
        search(incremental_units, query, limit=8, search_index=search_index)
    query_samples: list[float] = []
    for _ in range(200):
        query_start = time.perf_counter()
        results = search(incremental_units, query, limit=8, search_index=search_index)
        query_samples.append((time.perf_counter() - query_start) * 1000)
    file_stats(root)
    stat_samples: list[float] = []
    for _ in range(20):
        stat_start = time.perf_counter()
        file_stats(root)
        stat_samples.append((time.perf_counter() - stat_start) * 1000)
    monitor = StaleMonitor(root, payload)
    monitor.check(force=True)
    cached_stat_samples: list[float] = []
    for _ in range(20):
        stat_start = time.perf_counter()
        monitor.check()
        cached_stat_samples.append((time.perf_counter() - stat_start) * 1000)
    return {
        "files": files,
        "functions_per_file": functions,
        "full_units": full_unit_count,
        "incremental_units": len(incremental_units),
        "full_build_ms": full_ms,
        "json_index_bytes": readable_bytes,
        "json_write_ms": json_write_ms,
        "compact_index_bytes": compact_bytes,
        "compact_write_ms": compact_write_ms,
        "compact_size_ratio": compact_bytes / max(readable_bytes, 1),
        "compact_load_ms": compact_load_ms,
        "isolated_agent_load": isolated,
        "incremental_build_ms": incremental_ms,
        "speedup": full_ms / max(incremental_ms, 0.001),
        "query_ms_mean": sum(query_samples) / len(query_samples),
        # Recorded beside the mean so a reader can see how much the estimator
        # is worth: a mean over a handful of cold samples is not evidence.
        "query_ms_median": sorted(query_samples)[len(query_samples) // 2],
        "query_samples": len(query_samples),
        "search_index_ms": search_index_ms,
        "stale_stat_ms_mean": sum(stat_samples) / len(stat_samples),
        "stale_cached_ms_mean": sum(cached_stat_samples) / len(cached_stat_samples),
        "query": query,
        "query_top": results[0].unit.id if results else None,
        "max_rss_mb": _max_rss_mb(),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--files", type=int, default=100)
    parser.add_argument("--functions", type=int, default=20)
    parser.add_argument("--output")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="rag-large-") as directory:
        rendered = json.dumps(measure(Path(directory), args.files, args.functions), indent=2) + "\n"
        if args.output:
            Path(args.output).write_text(rendered, encoding="utf-8")
        else:
            print(rendered, end="")


if __name__ == "__main__":
    main()
