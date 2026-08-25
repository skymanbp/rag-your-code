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

The same runner grades `cold_queries.json`, whose questions are about a
repository nobody here wrote and whose index carries no written descriptions.
Both rulers are needed and neither substitutes for the other: this one measures
the warmest case the project supports, and that one measures what a first-time
user actually gets. A change that helps one and hurts the other is a trade, not
an improvement, and it cannot be seen at all from a single ruler.

It also grades `absent_queries.json`, which measures the failure the other two
are structurally blind to. Both of them ask questions that have an answer, so
both can only score whether it was found; neither can see a query that had no
answer anywhere being handed a confident-looking result regardless. Those
questions are marked `absent`, carry no acceptable answer by construction, and
are scored on silence rather than on hit@k -- there is nothing to hit. They are
kept apart from the aggregate for the same reason: averaging a question that
should return something with one that should return nothing produces a number
that improves when either half gets worse.

Every report carries a fingerprint of the corpus it graded. A score from this
ruler means nothing without one: two runs of an unchanged `search.py` against
the foreign repository returned 0.257 and 0.229 hit@1, because that repository
had grown by ninety units in between. Both numbers were right and comparing
them was meaningless, and nothing in the output said which corpus each came
from.
"""

from __future__ import annotations

import argparse
import hashlib
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

    A question marked ``absent`` asserts the opposite claim: that nothing in
    this index answers it, so naming an acceptable answer would contradict the
    mark. Absence itself is not checkable from the question -- that is done
    against the vocabulary in tests/test_absent_queries.py -- but the two
    halves of the claim are held consistent here, because a set that drifted
    into a mix of the two would be graded by whichever branch it fell down.
    """
    present = {(unit.path, unit.qualified_name) for unit in units}
    problems: list[str] = []
    seen: set[str] = set()
    for entry in questions["queries"]:
        if entry["id"] in seen:
            problems.append(f"{entry['id']}: duplicate question id")
        seen.add(entry["id"])
        if entry.get("absent"):
            if entry["acceptable"]:
                problems.append(f"{entry['id']}: marked absent yet lists an acceptable answer")
            continue
        if not entry["acceptable"]:
            problems.append(f"{entry['id']}: no acceptable answer listed")
        for path, name in entry["acceptable"]:
            if (path, name) not in present:
                problems.append(f"{entry['id']}: {path}::{name} is not in the index")
    return problems


def evaluate(
    units,
    questions: dict,
    k: int = 3,
    vector_weight: float | None = None,
    min_coverage: float | None = None,
    min_concentration: float | None = None,
) -> dict:
    """Grades one question set. Overrides are passed to `search` rather than
    set on the module, because a default argument is bound when the function is
    defined: assigning `search.DEFAULT_MIN_COVERAGE` afterwards changes nothing
    and produces a sweep in which every threshold scores identically, which is
    indistinguishable from a setting that does not matter.

    Every knob `search` takes has to be reachable from here, and that is not
    tidiness. A knob this cannot vary can only be measured by editing the source
    between runs, which moves the corpus and the setting at the same time -- and
    this repository's own source is one of the graded corpora.
    """
    index = build_search_index(units)
    overrides = {}
    if vector_weight is not None:
        overrides["vector_weight"] = vector_weight
    if min_coverage is not None:
        overrides["min_coverage"] = min_coverage
    if min_concentration is not None:
        overrides["min_concentration"] = min_concentration
    rows = []
    for entry in questions["queries"]:
        results = search(units, entry["query"], limit=k, search_index=index, **overrides)
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
            # Returning nothing is a different thing entirely and must not be
            # counted here: once the coverage gate existed, folding the two
            # together made this number rise as the defect it names went away.
            "no_lexical_evidence": bool(results) and not results[0].matched_terms,
            # Which words the top result matched on, kept because for an
            # unanswerable question that is the whole diagnosis: a set of
            # function words is how noise passes itself off as evidence.
            "matched_terms": list(results[0].matched_terms) if results else [],
            "absent": bool(entry.get("absent")),
            # For a question this index cannot answer, returning nothing is the
            # correct reply and the only one an agent can act on safely. Scored
            # on its own, never folded into hit@k, which measures finding a
            # thing that in these questions does not exist.
            "silent": not results,
            "top": results[0].unit.id if results else None,
        })

    answerable = [row for row in rows if not row["absent"]]
    unanswerable = [row for row in rows if row["absent"]]

    def summarise(subset: list[dict]) -> dict:
        count = len(subset) or 1
        return {
            "questions": len(subset),
            "hit_at_1": round(sum(row["hit_at_1"] for row in subset) / count, 4),
            "hit_at_k": round(sum(row["hit_at_k"] for row in subset) / count, 4),
            "mrr": round(sum(row["reciprocal_rank"] for row in subset) / count, 4),
            "no_lexical_evidence": round(sum(row["no_lexical_evidence"] for row in subset) / count, 4),
            # Answerable questions the coverage gate declined to answer. This is
            # the price side of that gate and belongs beside hit@k, not folded
            # into it: a question answered wrongly and one answered not at all
            # are both misses, and only one of them misleads.
            "declined": round(sum(row["silent"] for row in subset) / count, 4),
        }

    by_language: dict[str, list[dict]] = defaultdict(list)
    by_kind: dict[str, list[dict]] = defaultdict(list)
    for row in answerable:
        by_language[row["language"]].append(row)
        by_kind[row["kind"]].append(row)

    def silence(subset: list[dict]) -> dict:
        return {
            "questions": len(subset),
            "silence": round(sum(row["silent"] for row in subset) / (len(subset) or 1), 4),
        }

    absent_by_language: dict[str, list[dict]] = defaultdict(list)
    for row in unanswerable:
        absent_by_language[row["language"]].append(row)

    return {
        "k": k,
        # Stamped into every report rather than printed only for a human, so a
        # score kept in a file can still be told apart from one taken against a
        # different corpus months later.
        "corpus": corpus_stamp(units),
        "aggregate": summarise(answerable),
        "by_language": {name: summarise(group) for name, group in sorted(by_language.items())},
        "by_kind": {name: summarise(group) for name, group in sorted(by_kind.items())},
        "absent": silence(unanswerable),
        "absent_by_language": {name: silence(group) for name, group in sorted(absent_by_language.items())},
        "misses": [
            {"id": row["id"], "query": row["query"], "top": row["top"]}
            for row in answerable
            if not row["hit_at_k"]
        ],
        # An unanswerable question that came back with something. Named for what
        # it is rather than counted, because the useful question about a wrong
        # answer is always which unit it was and why that one.
        "spoke": [
            {"id": row["id"], "query": row["query"], "top": row["top"], "matched_terms": row.get("matched_terms", [])}
            for row in unanswerable
            if not row["silent"]
        ],
        "rows": rows,
    }


def corpus_stamp(units) -> dict:
    """Which corpus produced a score, as something a reader can compare.

    A number from this ruler is only reproducible against the code it graded,
    and one of the graded corpora is a repository nobody here controls. Between
    two runs of an unchanged `search.py` the foreign ruler moved from 0.257
    hit@1 to 0.229 -- entirely because that repository had grown from 1153 units
    to 1241. The score was right both times and the comparison was worthless,
    and nothing in the output said so. Published figures carry this stamp now,
    so a mismatch is visible instead of being read as a regression.
    """
    digest = hashlib.sha256()
    for unit in sorted(units, key=lambda item: item.id):
        digest.update(unit.id.encode("utf-8"))
        digest.update(unit.searchable_text.encode("utf-8"))
    return {"units": len(units), "fingerprint": digest.hexdigest()[:12]}


def _report(report: dict) -> None:
    stamp = report.get("corpus")
    if stamp:
        print(f"corpus               {stamp['units']} units, fingerprint {stamp['fingerprint']}")
    aggregate, k = report["aggregate"], report["k"]
    if aggregate["questions"]:
        print(f"questions            {aggregate['questions']}")
        print(f"hit@1                {aggregate['hit_at_1']:.3f}")
        print(f"hit@{k}                {aggregate['hit_at_k']:.3f}")
        print(f"mrr                  {aggregate['mrr']:.3f}")
        print(f"no lexical evidence  {aggregate['no_lexical_evidence']:.3f}")
        print(f"declined             {aggregate['declined']:.3f}")
        for label, group in (("language", report["by_language"]), ("kind", report["by_kind"])):
            print()
            for name, stats in group.items():
                print(
                    f"  {label:8} {name:10} n={stats['questions']:3d}"
                    f"  hit@1={stats['hit_at_1']:.3f}  hit@{k}={stats['hit_at_k']:.3f}  mrr={stats['mrr']:.3f}"
                )
    absent = report["absent"]
    if absent["questions"]:
        print(f"\nunanswerable         {absent['questions']}")
        print(f"silence              {absent['silence']:.3f}")
        for name, stats in report["absent_by_language"].items():
            print(f"  language {name:10} n={stats['questions']:3d}  silence={stats['silence']:.3f}")
    if report["misses"]:
        print(f"\nmisses ({len(report['misses'])} of {aggregate['questions']}):")
        for miss in report["misses"]:
            print(f"  {miss['id']:18} {miss['query'][:46]:48} -> {miss['top']}")
    if report["spoke"]:
        print(f"\nanswered anyway ({len(report['spoke'])} of {absent['questions']}):")
        for row in report["spoke"]:
            terms = ",".join(row["matched_terms"]) or "-"
            print(f"  {row['id']:22} on [{terms[:28]:30}] -> {row['top']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Grade retrieval on a set of questions about a repository.")
    parser.add_argument("--index", help="an existing index to grade; defaults to this repository's own")
    parser.add_argument("--questions", help=f"question set to grade against (default {QUERIES_PATH.name})")
    parser.add_argument(
        "--cold",
        action="store_true",
        help="parse this repository ignoring any written descriptions, which is what a first-time user's index contains",
    )
    parser.add_argument("--output", help="write the full report here as JSON")
    parser.add_argument("--vector-weight", type=float, default=None)
    parser.add_argument(
        "--min-coverage",
        type=float,
        default=None,
        help="override search.min_coverage; 0 restores answering every query, which is what the absent ruler grades against",
    )
    parser.add_argument(
        "--min-concentration",
        type=float,
        default=None,
        help="override search.min_concentration; 0 stops requiring the matched words to occur together",
    )
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    if args.index and args.cold:
        print("ruler: --cold parses this repository, so it cannot also grade a prebuilt --index", file=sys.stderr)
        return 2
    if args.index:
        # `--index` names the index file, and the obvious thing to type is the
        # repository. This is the path the project points anyone with an API
        # key at, and it answered a directory with a raw PermissionError
        # traceback out of pathlib -- so the one instruction the docs give a
        # stranger failed in a way that reads like a bug in the tool.
        chosen = Path(args.index)
        if chosen.is_dir():
            chosen = chosen / ".rag-your-code" / "index.json"
            if not chosen.is_file():
                print(f"ruler: {args.index} holds no index; run `rag-your-code index {args.index}` first", file=sys.stderr)
                return 2
        try:
            _, units = read_index(chosen)
        except OSError as exc:
            print(f"ruler: cannot read {chosen}: {exc}", file=sys.stderr)
            return 2
    elif args.cold:
        # No description store is passed, so every unit carries only the
        # sentence the parser generated. That is the state of a repository
        # nobody has run `describe` on yet.
        units = build_units(ROOT)
    else:
        default = ROOT / ".rag-your-code" / "index.json"
        _, units = read_index(default) if default.is_file() else (None, build_units(ROOT))

    questions = load_questions(Path(args.questions) if args.questions else QUERIES_PATH)
    problems = check_ruler(questions, units)
    if problems:
        for problem in problems:
            print(f"ruler: {problem}", file=sys.stderr)
        return 2

    report = evaluate(
        units,
        questions,
        k=questions.get("k", 3),
        vector_weight=args.vector_weight,
        min_coverage=args.min_coverage,
        min_concentration=args.min_concentration,
    )
    if args.output:
        Path(args.output).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if not args.quiet:
        _report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
