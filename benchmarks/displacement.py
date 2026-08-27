"""Measure how often a test declaration takes rank 1 from real code.

This figure has been published since 0.6.0 and has been wrong twice, both
times for the same reason: it had no committed command, so each re-derivation
invented its own idea of what a test unit is.

The second time is the instructive one. The sentence "none of cobra's 324 test
units reaches rank 1" carried two incompatible definitions inside itself. The
324 came from a basename rule, because Go writes `command_test.go` beside the
code; the "none reaches rank 1" came from a directory rule, which in a Go
repository matches nothing at all. The claim was true only because the
detector could not see a single one of the units it was naming.

So the definition lives here, in one place, and it is language-aware:
a unit is a test if any directory above it is `test`, `tests` or `testdata`,
or if its file name is one the language marks -- `test_*.py`, `*_test.py`,
`*_test.go`. Under that one rule the whole table below is self-consistent.

Two numbers come out of it and they are not the same number:

  * **at rank 1** -- a test is the top result. Often legitimate: sometimes the
    test *is* the best answer to the question asked.
  * **displacing** -- a test is the top result *and* an accepted answer is
    sitting at rank 2..k. This is the cost, and it is what the published
    figure means.

    python -m benchmarks.displacement
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from benchmarks.repo_queries import evaluate, load_questions  # noqa: E402 -- deferred until src/ is importable, because this runs from a clone where the package is not installed
from ragyourcode.indexer import build_units, read_index  # noqa: E402 -- same reason

TEST_DIRS = {"test", "tests", "testdata"}

# Each ruler as (label, index root or None for a cold parse of this repository,
# question set). The order is the one every published table uses.
RULERS = (
    ("C described", ROOT, "repo_queries.json"),
    ("B cold", None, "repo_queries.json"),
    ("A flask", ROOT / "benchmarks" / "corpus" / "flask", "cold_queries.json"),
    ("E cobra", ROOT / "benchmarks" / "corpus" / "cobra", "cobra_queries.json"),
)


def is_test(path: str) -> bool:
    """Whether a unit's file is a test, under one rule for every language."""
    parts = path.replace("\\", "/").split("/")
    if TEST_DIRS.intersection(parts[:-1]):
        return True
    name = parts[-1]
    return name.startswith("test_") or name.endswith(("_test.py", "_test.go"))


def _units(index_root: Path | None):
    if index_root is None:
        # No description store, so every unit carries only the generated
        # sentence -- the state of a repository nobody has run `describe` on.
        return build_units(ROOT)
    index = index_root / ".rag-your-code" / "index.json"
    if not index.is_file():
        sys.exit(f"displacement: {index_root} holds no index; run `rag-your-code index {index_root}` first")
    return read_index(index)[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--k", type=int, default=3, help="an answer at rank 2..k counts as displaced")
    parser.add_argument("--output", help="write the full table here as JSON")
    args = parser.parse_args()

    table, questions_total, at_one_total, displaced_total = [], 0, 0, 0
    for label, index_root, question_file in RULERS:
        units = _units(index_root)
        report = evaluate(units, load_questions(ROOT / "benchmarks" / question_file), k=args.k)
        rows = [row for row in report["rows"] if not row.get("absent")]
        at_one = [row for row in rows if is_test((row.get("top") or "").split(":")[0])]
        # `hit_at_k and not hit_at_1` is exactly "an accepted answer is at
        # rank 2..k while something else holds rank 1".
        displaced = [row for row in at_one if row["hit_at_k"] and not row["hit_at_1"]]
        questions_total += len(rows)
        at_one_total += len(at_one)
        displaced_total += len(displaced)
        table.append({
            "ruler": label,
            "corpus": report["corpus"],
            "questions": len(rows),
            "test_units": sum(1 for unit in units if is_test(unit.path)),
            "at_rank_1": len(at_one),
            "displacing": len(displaced),
            "cases": [{"id": row["id"], "top": row["top"]} for row in displaced],
        })

    width = max(len(row["ruler"]) for row in table)
    print(f"{'ruler':<{width}} {'n':>4} {'test units':>11} {'at rank 1':>10} {'displacing':>11}  corpus")
    for row in table:
        stamp = f"{row['corpus']['units']} {row['corpus']['fingerprint']}"
        print(f"{row['ruler']:<{width}} {row['questions']:>4} {row['test_units']:>11} "
              f"{row['at_rank_1']:>10} {row['displacing']:>11}  {stamp}")
        for case in row["cases"]:
            print(f"{'':<{width}}   - {case['id']}: {case['top']}")

    print(f"\n{displaced_total} of {questions_total} questions across "
          f"{len(table)} positive rulers have a test at rank 1 displacing an "
          f"accepted answer at rank 2-{args.k}.")
    print(f"Tests reach rank 1 on {at_one_total} of the {questions_total}; the rest are legitimate answers.")

    summary = {
        "k": args.k,
        "questions": questions_total,
        "at_rank_1": at_one_total,
        "displacing": displaced_total,
        "rulers": table,
    }
    if args.output:
        Path(args.output).write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
