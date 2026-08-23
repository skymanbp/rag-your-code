from __future__ import annotations

import json
import subprocess
import sys


def test_large_repo_incremental_benchmark_smoke():
    proc = subprocess.run(
        [sys.executable, "-m", "benchmarks.large_repo", "--files", "12", "--functions", "8"],
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(proc.stdout)
    assert result["full_units"] == 96
    assert result["incremental_units"] == 97
    assert result["incremental_build_ms"] < result["full_build_ms"] * 2
    assert result["query_top"].endswith(":function_11_7")
