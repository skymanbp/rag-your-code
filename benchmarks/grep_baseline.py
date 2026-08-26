"""The head-to-head in README section 7, as a command instead of a memory.

The comparison this reproduces was published from a script that was never
committed. Its two tables are the strongest claim the project makes -- that
once a repository has been described, retrieval beats an agent driving Grep --
and until now a reader had no way to check either of them, or even to see what
"a Grep loop" meant precisely.

What the baseline does, stated so it can be argued with: take the query's
words, drop the ones the corpus itself shows are everywhere, run one substring
search per remaining word over exactly the files the index was built from, and
rank each file by how many distinct query words hit it. Ties break on path, so
two runs of the same input give the same table -- an earlier version iterated a
set and let string-hash randomisation reorder ties, which moved first-place
accuracy between 34.3% and 22.9% on identical inputs.

Dropping the corpus-common words is deliberately generous to Grep: an agent
that greps `the` gets every file back and no ranking at all. Scoring is at file
granularity for the same reason -- Grep has no declaration spans, so counting
them would penalise it for a distinction it cannot make.

    python -m benchmarks.grep_baseline                  # this repository
    python -m benchmarks.grep_baseline --index <path-to-index.json> \
        --questions benchmarks/cold_queries.json --root <that-repository>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from benchmarks.repo_queries import (  # noqa: E402 -- deferred until src/ is importable, above
    QUERIES_PATH,
    corpus_stamp,
    load_questions,
)
from ragyourcode.embeddings import tokenize  # noqa: E402 -- same reason
from ragyourcode.indexer import read_index  # noqa: E402 -- same reason
from ragyourcode.search import (  # noqa: E402 -- same reason
    COMMON_TERM,
    COMMON_TERM_FLOOR,
    build_search_index,
    context,
    search,
    within_budget,
)

BUDGET = 12000


def _content_words(query: str, search_index, total: int) -> list[str]:
    """The query's words, minus the ones this corpus uses everywhere.

    Uses the index's own posting lengths rather than a stopword list, for the
    same reason `search` does: the rule then works on a repository in any
    language, and the baseline is handed the same courtesy the ranked side
    gets rather than a different definition of "content word".
    """
    kept: list[str] = []
    for word in dict.fromkeys(tokenize(query)):
        postings = search_index.postings.get(word, ())
        if len(postings) > max(COMMON_TERM_FLOOR, COMMON_TERM * total):
            continue
        kept.append(word)
    return kept


def _sources(root: Path, units) -> dict[str, str]:
    """Every file the index was built from, read once, keyed by its repo path."""
    texts: dict[str, str] = {}
    for path in sorted({unit.path for unit in units}):
        try:
            texts[path] = (root / path).read_text(encoding="utf-8", errors="replace").lower()
        except OSError:
            continue
    return texts


def _grep(texts: dict[str, str], words: list[str]) -> tuple[list[str], int, int]:
    """Files ranked by how many distinct query words hit them, and what the
    loop would have printed: matching lines, and their size in characters.

    The payload is what the comparison is really about, and it is counted in
    characters on both sides so the two are comparable. Counting one side in
    lines and the other in characters compares nothing.

    A line holding two query words is counted twice, because one search per
    word is what the loop actually runs and both runs print it.
    """
    hits: dict[str, int] = {}
    lines = 0
    payload = 0
    for path in sorted(texts):
        rows = texts[path].splitlines()
        matched = 0
        for word in words:
            found = [row for row in rows if word in row]
            if found:
                matched += 1
                lines += len(found)
                payload += sum(len(row) + len(path) + 6 for row in found)  # `path:line:` prefix
        if matched:
            hits[path] = matched
    ordered = sorted(hits, key=lambda path: (-hits[path], path))
    return ordered, lines, payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Grade a Grep loop and this tool on the same questions.")
    parser.add_argument("--index", help="index to grade; defaults to this repository's own")
    parser.add_argument("--questions", help=f"question set (default {QUERIES_PATH.name})")
    parser.add_argument("--root", help="repository the index was built from (default: this one)")
    args = parser.parse_args()

    index_path = Path(args.index) if args.index else ROOT / ".rag-your-code" / "index.json"
    root = Path(args.root) if args.root else ROOT
    _, units = read_index(index_path)
    search_index = build_search_index(units)
    questions = load_questions(Path(args.questions) if args.questions else QUERIES_PATH)["queries"]
    texts = _sources(root, units)

    wanted = {"grep_first": 0, "grep_top3": 0, "ours_first": 0, "ours_top3": 0}
    grep_lines = 0
    grep_chars = 0
    ours_chars = 0
    grep_answered = 0
    ours_answered = 0
    for question in questions:
        truth = {path for path, _ in question["acceptable"]}
        ranked, lines, payload = _grep(texts, _content_words(question["query"], search_index, len(units)))
        grep_lines += lines
        grep_chars += payload
        grep_answered += bool(ranked)
        wanted["grep_first"] += bool(ranked[:1]) and ranked[0] in truth
        wanted["grep_top3"] += any(path in truth for path in ranked[:3])

        results = search(units, question["query"], search_index=search_index)
        ours_answered += bool(results)
        ours_chars += len(context(within_budget(results, BUDGET), BUDGET))
        ours_files = list(dict.fromkeys(result.unit.path for result in results))
        wanted["ours_first"] += bool(ours_files[:1]) and ours_files[0] in truth
        wanted["ours_top3"] += any(path in truth for path in ours_files[:3])

    n = len(questions)
    stamp = corpus_stamp(units)
    print(f"corpus: {stamp['units']} units, fingerprint {stamp['fingerprint']}  ({n} questions)")
    print(f"  right file first      grep {wanted['grep_first'] / n:.3f}   rag-your-code {wanted['ours_first'] / n:.3f}")
    print(f"  right file in top 3   grep {wanted['grep_top3'] / n:.3f}   rag-your-code {wanted['ours_top3'] / n:.3f}")
    print(f"  questions answered    grep {grep_answered}         rag-your-code {ours_answered}")
    print(f"  lines Grep hands back {grep_lines}")
    print(f"  characters returned   grep {grep_chars}   rag-your-code {ours_chars}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
