"""Measure compact index startup in an isolated process."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from benchmarks.large_repo import _memory_mb
from ragyourcode.indexer import read_index
from ragyourcode.search import build_search_index


def main() -> None:
    path = Path(sys.argv[1])
    start = time.perf_counter()
    _, units = read_index(path)
    load_ms = (time.perf_counter() - start) * 1000
    start = time.perf_counter()
    search_index = build_search_index(units)
    search_index_ms = (time.perf_counter() - start) * 1000
    current, peak = _memory_mb()
    print(
        json.dumps(
            {
                "units": len(units),
                "terms": len(search_index.postings),
                "load_ms": load_ms,
                "search_index_ms": search_index_ms,
                "current_rss_mb": current,
                "peak_rss_mb": peak,
            }
        )
    )


if __name__ == "__main__":
    main()
