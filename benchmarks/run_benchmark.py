"""Compare lexical baseline and hybrid retrieval on the golden query set.

Run with ``python -m benchmarks.run_benchmark``. The benchmark is deliberately
stdlib-only and emits JSON so results can be archived in CI artifacts.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ragyourcode.embeddings import tokenize  # noqa: E402
from ragyourcode.graph import build_graph, graph_search  # noqa: E402
from ragyourcode.indexer import build_units, iter_source_files  # noqa: E402
from ragyourcode.models import CodeUnit, SearchResult  # noqa: E402
from ragyourcode.parser import parse_file  # noqa: E402
from ragyourcode.search import build_search_index, search as hybrid_search  # noqa: E402

BENCHMARK_ROOT = Path(__file__).resolve().parent
FIXTURE_ROOT = BENCHMARK_ROOT / "fixture"
GOLDEN_PATH = BENCHMARK_ROOT / "golden.json"


def lexical_search(units: list[CodeUnit], query: str, limit: int) -> list[SearchResult]:
    """Simple exact-token baseline with no vector similarity."""
    query_tokens = set(tokenize(query))
    ranked: list[SearchResult] = []
    for unit in units:
        matched = sorted(query_tokens & set(tokenize(unit.searchable_text)))
        if matched:
            ranked.append(SearchResult(unit, len(matched) / max(1, len(query_tokens)), matched))
    ranked.sort(key=lambda result: (-result.score, result.unit.id))
    return ranked[: max(1, limit)]


def _is_relevant(unit: CodeUnit, expected: list[dict[str, str]]) -> bool:
    return any(unit.path == item["path"] and unit.name == item["name"] for item in expected)


def _metrics(results: list[SearchResult], expected: list[dict[str, str]], k: int) -> dict[str, float]:
    top = results[:k]
    hits = sum(_is_relevant(result.unit, expected) for result in top)
    first_rank = next((index for index, result in enumerate(results, 1) if _is_relevant(result.unit, expected)), None)
    return {
        "precision_at_k": hits / max(1, k),
        "recall_at_k": hits / max(1, len(expected)),
        "top1_accuracy": float(bool(results) and _is_relevant(results[0].unit, expected)),
        "mrr": 1 / first_rank if first_rank else 0.0,
    }


def evaluate(name: str, fn, units: list[CodeUnit], queries: list[dict], k: int, repetitions: int = 20) -> dict:
    timings: list[float] = []
    per_query: list[dict] = []
    for item in queries:
        for _ in range(3):
            fn(units, item["query"], k)
        samples = []
        results = []
        for _ in range(repetitions):
            start = time.perf_counter()
            results = fn(units, item["query"], k)
            samples.append((time.perf_counter() - start) * 1000)
        timings.extend(samples)
        per_query.append({"id": item["id"], "metrics": _metrics(results, item["relevant"], k), "top": [result.unit.id for result in results]})
    aggregate = {
        key: statistics.mean(item["metrics"][key] for item in per_query)
        for key in ("precision_at_k", "recall_at_k", "top1_accuracy", "mrr")
    }
    ordered = sorted(timings)
    aggregate.update(
        {
            "query_ms_mean": statistics.mean(timings),
            "query_ms_p95": ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))],
            "queries": len(queries),
            "repetitions": repetitions,
        }
    )
    return {"name": name, "aggregate": aggregate, "per_query": per_query}


def run() -> dict:
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    parse_start = time.perf_counter()
    parsed_units: list[CodeUnit] = []
    for path in iter_source_files(FIXTURE_ROOT):
        parsed_units.extend(parse_file(path, FIXTURE_ROOT))
    baseline_index_ms = (time.perf_counter() - parse_start) * 1000
    start = time.perf_counter()
    units = build_units(FIXTURE_ROOT)
    optimized_index_ms = (time.perf_counter() - start) * 1000
    search_index_start = time.perf_counter()
    search_index = build_search_index(units)
    search_index_ms = (time.perf_counter() - search_index_start) * 1000

    def optimized_search(indexed_units, query, limit):
        return hybrid_search(indexed_units, query, limit, search_index=search_index)
    graph = build_graph(units)
    graph_query = "checkout orchestration"
    graph_expected = [{"path": "payments.py", "name": "retry_charge"}]
    hybrid_graph_samples: list[float] = []
    graph_samples: list[float] = []
    hybrid_graph_results = []
    graph_results = []
    for _ in range(20):
        query_start = time.perf_counter()
        hybrid_graph_results = hybrid_search(units, graph_query, 3, search_index=search_index)
        hybrid_graph_samples.append((time.perf_counter() - query_start) * 1000)
        query_start = time.perf_counter()
        graph_results = graph_search(units, graph_query, 3, 1, graph, search_index)
        graph_samples.append((time.perf_counter() - query_start) * 1000)
    result = {
        "golden": golden["name"],
        "fixture": str(FIXTURE_ROOT),
        "units": len(units),
        "index_ms": optimized_index_ms,
        "index_ms_baseline_parse_only": baseline_index_ms,
        "index_ms_optimized_parse_and_embed": optimized_index_ms,
        "search_index_ms": search_index_ms,
        "k": golden["k"],
        "baseline": evaluate("lexical", lexical_search, units, golden["queries"], golden["k"]),
        "optimized": evaluate("cached hybrid lexical+vector", optimized_search, units, golden["queries"], golden["k"]),
        "graph": {
            "query": graph_query,
            "edges": len(graph.edges),
            "hybrid_related_recall_at_3": _metrics(hybrid_graph_results, graph_expected, 3)["recall_at_k"],
            "graph_related_recall_at_3": _metrics(graph_results, graph_expected, 3)["recall_at_k"],
            "hybrid_query_ms_mean": statistics.mean(hybrid_graph_samples),
            "graph_query_ms_mean": statistics.mean(graph_samples),
            "graph_top": [result.unit.id for result in graph_results],
        },
    }
    result["delta"] = {
        key: result["optimized"]["aggregate"][key] - result["baseline"]["aggregate"][key]
        for key in ("precision_at_k", "recall_at_k", "top1_accuracy", "mrr", "query_ms_mean", "query_ms_p95")
    }
    result["delta"]["index_ms"] = optimized_index_ms - baseline_index_ms
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output")
    args = parser.parse_args()
    rendered = json.dumps(run(), ensure_ascii=False, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
