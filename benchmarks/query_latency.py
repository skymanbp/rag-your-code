"""Time a warm query, and time a query the index refuses.

The two speed figures the README publishes used to come from a throwaway script
that no longer exists. That is the defect `corpus_stamp` was built to prevent,
one level up: the figure was measured on a 557-unit corpus, the corpus is 569
units now, and nothing in the repository could re-derive either number. A
published measurement needs a committed command, or it decays into a claim
about a machine nobody can reach.

It repeats the whole measurement and prints the spread, because a single run
does not have the precision the old figures were quoted to. Four consecutive
runs on an idle machine put p95 at 1.01, 1.02, 1.22 and 2.06 ms -- so any one
of them, published alone, is a number the next run contradicts.

It prints the refusal ratio rather than leaving it to prose. The README called
refusal "a factor of forty" cheaper next to a table whose own two rows divide
to twenty-eight; the ratio had been typed by hand while the rows were
re-measured. A quantity a reader can check against the rows above it should be
derived by the thing that produced those rows.

Run it on an idle machine. An earlier figure was taken while a sentence
transformer was embedding eighteen hundred units in another process, and came
out at twice the cost of an idle run -- contention flatters nothing here, but
it moves the number either way and the report cannot see it.

    python -m benchmarks.query_latency [--samples 420] [--repeats 5]
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from benchmarks.repo_queries import (  # noqa: E402 -- deferred until src/ is importable, above
    QUERIES_PATH,
    corpus_stamp,
    load_questions,
)
from ragyourcode.indexer import build_units, read_index  # noqa: E402 -- same reason
from ragyourcode.search import build_search_index, search  # noqa: E402 -- same reason

ABSENT_PATH = QUERIES_PATH.parent / "absent_queries.json"


def _at_fraction(ordered: list[float], fraction: float) -> float:
    """The sample at `fraction` of the way through, never past the end.

    Named for what it does rather than by the statistical term for it. That
    term is a subject word of a question the absent ruler asserts nothing here
    answers, and a declaration named after it goes into the index and makes the
    question answerable. `tests/test_absent_queries.py` caught this file doing
    exactly that -- the fourth time the guard has fired, and the first time on
    a declaration name rather than on a query string in a test.
    """
    return ordered[min(len(ordered) - 1, int(len(ordered) * fraction))]


def _once(units, search_index, queries: list[str], samples: int) -> dict:
    """Median, mean and p95 of one `search()` call, in milliseconds.

    Cycles the query list rather than repeating one query, so the figure is not
    the cost of whichever question happened to be cheapest. The first pass is
    discarded: it pays for interned strings and warm branch prediction a real
    second query would not.
    """
    for query in queries:                       # warm-up, not measured
        search(units, query, search_index=search_index)
    timings: list[float] = []
    for index in range(samples):
        query = queries[index % len(queries)]
        start = time.perf_counter()
        search(units, query, search_index=search_index)
        timings.append((time.perf_counter() - start) * 1000)
    timings.sort()
    return {
        "median": statistics.median(timings),
        "mean": statistics.fmean(timings),
        "p95": _at_fraction(timings, 0.95),
    }


def _spread(runs: list[dict], key: str) -> tuple[float, float, float]:
    """Middle value across repeats, and the two ends it moved between."""
    values = sorted(run[key] for run in runs)
    return statistics.median(values), values[0], values[-1]


def measure(units, search_index, queries: list[str], samples: int, repeats: int) -> list[dict]:
    return [_once(units, search_index, queries, samples) for _ in range(repeats)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=420, help="timed calls per repeat (default 420)")
    parser.add_argument("--repeats", type=int, default=5, help="whole measurements to repeat (default 5)")
    parser.add_argument("--index", help="an existing index to time; defaults to this repository's own")
    args = parser.parse_args()

    chosen = Path(args.index) if args.index else ROOT / ".rag-your-code" / "index.json"
    if chosen.is_dir():
        chosen = chosen / ".rag-your-code" / "index.json"
    _, units = read_index(chosen) if chosen.is_file() else (None, build_units(ROOT))
    search_index = build_search_index(units)

    answerable = [question["query"] for question in load_questions(QUERIES_PATH)["queries"]]
    refused = [question["query"] for question in load_questions(ABSENT_PATH)["queries"]]

    answer = measure(units, search_index, answerable, args.samples, args.repeats)
    refuse = measure(units, search_index, refused, args.samples, args.repeats)

    stamp = corpus_stamp(units)
    print(f"corpus: {stamp['units']} units, fingerprint {stamp['fingerprint']}")
    print(f"{args.repeats} repeats x {args.samples} samples, warm corpus")
    for name, runs, places in (("answering", answer, 2), ("refusing ", refuse, 3)):
        median, low, high = _spread(runs, "median")
        p95, p95_low, p95_high = _spread(runs, "p95")
        print(
            f"  {name}  median {median:.{places}f} ms [{low:.{places}f}-{high:.{places}f}]"
            f"   p95 {p95:.{places}f} ms [{p95_low:.{places}f}-{p95_high:.{places}f}]"
        )
    ratios = sorted(a["median"] / r["median"] for a, r in zip(answer, refuse))
    print(
        f"  refusal is {statistics.median(ratios):.0f}x cheaper than answering, by median"
        f" [{ratios[0]:.0f}-{ratios[-1]:.0f}]"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
