"""Measure what the vectors cost in a published index.

The share of an index that is vectors is a number this project publishes in
three places at once -- its own corpus in README sections 3.2 and 11, with
Flask and cobra beside it -- so it needs a command that reproduces it. The rule
the other rulers follow applies here too: a figure is meaningless without the
corpus it was taken on, so the share prints on the same line as the
fingerprint of the corpus it was measured against.

The unit is **bytes of the index file as written**, UTF-8. The measurement is a
difference rather than a pattern match: the payload is re-serialized with
`write_index`'s own `json.dump(..., ensure_ascii=False, indent=2)`, then again
with every `vector` field dropped, and the gap between the two is what the
vectors cost. The first of those is compared against the bytes on disk before
either is reported, so the difference is the on-disk cost and not an
approximation of it.

Bytes and characters are different measurements here. This repository's own
index carries about 45,000 bytes of multi-byte UTF-8 -- its sources quote prose
as well as code -- so a character count puts the share about 0.6 points above
the byte figure. The two vendored corpora are almost pure ASCII and agree to
within 0.001 points, which is why the basis has to be stated rather than
inferred from them.

Under `index.compact` the vectors are a float32 side file instead of a span
inside the JSON. The share then compares that file against the pair of files
the index actually occupies, and the report says which basis produced it.

    python -m benchmarks.vector_share
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from benchmarks.repo_queries import corpus_stamp  # noqa: E402 -- deferred until src/ is importable, because this runs from a clone where the package is not installed
from ragyourcode.indexer import read_index  # noqa: E402 -- same reason

# The three corpora the README publishes a share for, in the order it uses.
CORPORA = (
    ("own", ROOT),
    ("flask", ROOT / "benchmarks" / "corpus" / "flask"),
    ("cobra", ROOT / "benchmarks" / "corpus" / "cobra"),
)

# Exactly the arguments write_index serializes with. Anything else measures a
# file this project does not publish.
DUMP = {"ensure_ascii": False, "indent": 2}


def measure(index_path: Path) -> dict:
    """What the vectors occupy in one published index, in bytes."""
    raw = index_path.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    store = payload.get("vector_store")
    if isinstance(store, dict):
        sidecar = index_path.parent / str(store.get("path", ""))
        vector_bytes = sidecar.stat().st_size
        return {
            "basis": "compact",
            "vector_bytes": vector_bytes,
            "total_bytes": len(raw) + vector_bytes,
            "reproduces_file": True,
        }
    whole = json.dumps(payload, **DUMP).encode("utf-8")
    for unit in payload.get("units", []):
        unit.pop("vector", None)
    without = json.dumps(payload, **DUMP).encode("utf-8")
    return {
        "basis": "readable",
        "vector_bytes": len(whole) - len(without),
        "total_bytes": len(whole),
        # A round trip that does not reproduce the file byte for byte means the
        # difference above is an estimate of the on-disk cost, not the cost.
        "reproduces_file": whole == raw,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--index", help="one repository to measure; defaults to all three published corpora")
    parser.add_argument("--output", help="write the full table here as JSON")
    args = parser.parse_args()

    corpora = ((Path(args.index).name or "index", Path(args.index)),) if args.index else CORPORA
    table, absent = [], []
    for label, root in corpora:
        index_path = root / ".rag-your-code" / "index.json"
        if not index_path.is_file():
            absent.append((label, root))
            continue
        row = measure(index_path)
        row["corpus"] = corpus_stamp(read_index(index_path)[1])
        row["label"] = label
        row["share"] = row["vector_bytes"] / row["total_bytes"]
        table.append(row)

    if table:
        width = max(len(row["label"]) for row in table)
        print(f"{'corpus':<{width}} {'units':>6} {'fingerprint':>13} {'index bytes':>13} {'vector bytes':>13} {'share':>7}  basis")
        for row in table:
            stamp = row["corpus"]
            print(f"{row['label']:<{width}} {stamp['units']:>6} {stamp['fingerprint']:>13} "
                  f"{row['total_bytes']:>13,} {row['vector_bytes']:>13,} {row['share']:>7.1%}  {row['basis']}")
            if not row["reproduces_file"]:
                print(f"{'':<{width}}   re-serialization does not reproduce this file; the share is an estimate")

    for label, root in absent:
        print(f"{label}: no index under {root}; run `python -m ragyourcode.cli index {root}` first")
    if not table:
        return 1

    if args.output:
        Path(args.output).write_text(json.dumps({"corpora": table}, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
