"""Measure retrieval against natural-language questions about this repository.

`golden.json` grades ranking over a five-file synthetic fixture: small, stable,
and useful as a regression tripwire. It cannot answer whether a change to how
vocabulary reaches the index actually helps, because seven queries over sixty
units have no resolution. Four candidate scoring changes measured over an
eight-question set all landed between five and six correct, which is a range
that cannot distinguish a real improvement from noise.

This grades the real thing: natural-language questions over this repository's
own source, each listing every unit that genuinely answers it. The count lives
in the JSON rather than in this sentence, because a figure in prose is a claim
nothing checks. Keyed on file path and
declaration name rather than line number, so an edit above a declaration does
not silently invalidate the ruler.

Every acceptable answer is checked against the index before anything is scored.
A ruler that quietly stopped referring to real code would report improvement by
losing its own questions.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from ragyourcode.indexer import build_units, read_index  # noqa: E402 -- must follow the sys.path insert above, because this runs from a clone where the package is not installed
from ragyourcode.search import build_search_index, search  # noqa: E402 -- deferred for the same reason, because src/ only becomes importable on the line above

QUERIES_PATH = Path(__file__).resolve().parent / "repo_queries.json"


def load_questions(path: Path = QUERIES_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def check_ruler(questions: dict, units) -> list[str]:
    """Every acceptable answer must name a unit that exists.

    Run before scoring, not after: a renamed declaration would otherwise make
    its question unanswerable and read as a retrieval regression, or -- worse,
    if the question were then quietly dropped -- as an improvement.
    """
    present = {(unit.path, unit.qualified_name) for unit in units}
    problems: list[str] = []
    seen: set[str] = set()
    for entry in questions["queries"]:
        if entry["id"] in seen:
            problems.append(f"{entry['id']}: duplicate question id")
        seen.add(entry["id"])
        if not entry["acceptable"]:
            problems.append(f"{entry['id']}: no acceptable answer listed")
        for path, name in entry["acceptable"]:
            if (path, name) not in present:
                problems.append(f"{entry['id']}: {path}::{name} is not in the index")
    return problems


def evaluate(units, questions: dict, k: int = 3, vector_weight: float | None = None) -> dict:
    index = build_search_index(units)
    weight = {} if vector_weight is None else {"vector_weight": vector_weight}
    rows = []
    for entry in questions["queries"]:
        results = search(units, entry["query"], limit=k, search_index=index, **weight)
        wanted = {tuple(pair) for pair in entry["acceptable"]}
        ranks = [
            position
            for position, result in enumerate(results, 1)
            if (result.unit.path, result.unit.qualified_name) in wanted
        ]
        rows.append({
            "id": entry["id"],
            "language": entry.get("language", "en"),
            "kind": entry.get("kind", "concept"),
            "query": entry["query"],
            "hit_at_1": bool(ranks and ranks[0] == 1),
            "hit_at_k": bool(ranks),
            "reciprocal_rank": (1.0 / ranks[0]) if ranks else 0.0,
            # A top result whose matched terms are empty came back through the
            # no-overlap cosine fallback, which means nothing actually matched.
            "no_lexical_evidence": not (results and results[0].matched_terms),
            "top": results[0].unit.id if results else None,
        })

    def summarise(subset: list[dict]) -> dict:
        count = len(subset) or 1
        return {
            "questions": len(subset),
            "hit_at_1": round(sum(row["hit_at_1"] for row in subset) / count, 4),
            "hit_at_k": round(sum(row["hit_at_k"] for row in subset) / count, 4),
            "mrr": round(sum(row["reciprocal_rank"] for row in subset) / count, 4),
            "no_lexical_evidence": round(sum(row["no_lexical_evidence"] for row in subset) / count, 4),
        }

    by_language: dict[str, list[dict]] = defaultdict(list)
    by_kind: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_language[row["language"]].append(row)
        by_kind[row["kind"]].append(row)

    return {
        "k": k,
        "aggregate": summarise(rows),
        "by_language": {name: summarise(group) for name, group in sorted(by_language.items())},
        "by_kind": {name: summarise(group) for name, group in sorted(by_kind.items())},
        "misses": [
            {"id": row["id"], "query": row["query"], "top": row["top"]}
            for row in rows
            if not row["hit_at_k"]
        ],
        "rows": rows,
    }


def _report(report: dict) -> None:
    aggregate, k = report["aggregate"], report["k"]
    print(f"questions            {aggregate['questions']}")
    print(f"hit@1                {aggregate['hit_at_1']:.3f}")
    print(f"hit@{k}                {aggregate['hit_at_k']:.3f}")
    print(f"mrr                  {aggregate['mrr']:.3f}")
    print(f"no lexical evidence  {aggregate['no_lexical_evidence']:.3f}")
    for label, group in (("language", report["by_language"]), ("kind", report["by_kind"])):
        print()
        for name, stats in group.items():
            print(
                f"  {label:8} {name:10} n={stats['questions']:3d}"
                f"  hit@1={stats['hit_at_1']:.3f}  hit@{k}={stats['hit_at_k']:.3f}  mrr={stats['mrr']:.3f}"
            )
    if report["misses"]:
        print(f"\nmisses ({len(report['misses'])} of {aggregate['questions']}):")
        for miss in report["misses"]:
            print(f"  {miss['id']:18} {miss['query'][:46]:48} -> {miss['top']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Grade retrieval on questions about this repository.")
    parser.add_argument("--index", help="an existing index to grade; defaults to this repository's own")
    parser.add_argument("--output", help="write the full report here as JSON")
    parser.add_argument("--vector-weight", type=float, default=None)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    if args.index:
        _, units = read_index(Path(args.index))
    else:
        default = ROOT / ".rag-your-code" / "index.json"
        _, units = read_index(default) if default.is_file() else (None, build_units(ROOT))

    questions = load_questions()
    problems = check_ruler(questions, units)
    if problems:
        for problem in problems:
            print(f"ruler: {problem}", file=sys.stderr)
        return 2

    report = evaluate(units, questions, k=questions.get("k", 3), vector_weight=args.vector_weight)
    if args.output:
        Path(args.output).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if not args.quiet:
        _report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
