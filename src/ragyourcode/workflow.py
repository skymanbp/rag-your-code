"""The vocabulary ladder as operations, separate from how they are invoked.

Every rung -- what the parser generated, what an agent still has to write,
what can be moved into the source -- is a function of the units, the store and
the settings, and of nothing else. Keeping them here rather than beside the
argument parsing is what lets the command line and the agent protocol run the
same code instead of two implementations that drift.
"""

from __future__ import annotations

from pathlib import Path

from .annotate import comment_for
from .config import Config
from .descriptions import DescriptionStore, guidance
from .document import plan as plan_documentation, summarise as summarise_documentation
from .embeddings import embedder

def describe_batch(units: list, store: DescriptionStore, cfg: Config, limit: int) -> dict:
    """The work packet handed to an agent: what to describe, and how.

    The source is included because the brief forbids describing behaviour the
    source does not show, and an agent cannot honour that without seeing it.
    The generated description goes along so the agent can tell what retrieval
    already has and add what it lacks rather than paraphrasing it.
    """
    groups = store.classify(units)
    skip = cfg["describe.skip"]
    pending = store.pending(units, limit, skip)
    declined = store.declined(groups["missing"] + groups["superseded"], skip)
    languages = cfg["describe.languages"]
    return {
        "languages": list(languages),
        "max_chars": cfg["describe.max_chars"],
        "guidance": guidance(languages, cfg["describe.max_chars"]),
        "described": len(groups["described"]),
        "superseded": len(groups["superseded"]),
        "missing": len(groups["missing"]),
        # Said out loud rather than subtracted quietly. A queue that shrinks
        # without explanation reads as "nothing left to do", which is the same
        # failure mode as a silently truncated result.
        "declined": len(declined),
        "remaining": len(groups["missing"]) + len(groups["superseded"]) - len(declined),
        "units": [
            {
                "id": unit.id,
                "path": unit.path,
                "language": unit.language,
                "kind": unit.kind,
                "qualified_name": unit.qualified_name,
                "signature": unit.signature,
                "start_line": unit.start_line,
                "end_line": unit.end_line,
                "generated_description": unit.description,
                "source": unit.source,
            }
            for unit in pending
        ],
    }


def store_descriptions(units: list, store: DescriptionStore, cfg: Config, items) -> dict:
    """Validate and persist a batch, reporting every rejection with a reason.

    Nothing is truncated to fit. A description silently cut at the limit would
    lose exactly the trailing synonyms that make it worth writing, and the
    agent would have no way to learn that it had happened.
    """
    if not isinstance(items, list):
        raise ValueError("descriptions must be a list of {id, text} objects")
    by_id = {unit.id: unit for unit in units}
    max_chars = cfg["describe.max_chars"]
    stored: list[str] = []
    rejected: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            rejected.append({"id": None, "reason": "not_an_object"})
            continue
        unit_id = str(item.get("id", ""))
        text = str(item.get("text", "")).strip()
        unit = by_id.get(unit_id)
        if unit is None:
            rejected.append({"id": unit_id, "reason": "unknown_unit"})
        elif not text:
            rejected.append({"id": unit_id, "reason": "empty"})
        elif len(text) > max_chars:
            rejected.append({"id": unit_id, "reason": "too_long", "length": len(text), "limit": max_chars})
        else:
            store.put(unit, text)
            stored.append(unit_id)
    if stored:
        store.save(units)
    return {
        "stored": len(stored),
        "stored_ids": stored,
        "rejected": rejected,
        # Net of what `describe.skip` withholds, so this agrees with the number
        # `describe_batch` and `bootstrap` report. Two counts of "remaining"
        # that disagree is how an agent decides the queue is unfinished and
        # keeps asking for a batch that will always come back empty.
        "remaining": len(store.pending(units, len(units), cfg["describe.skip"])),
        # The store is written but the published index still holds the previous
        # text. Said as its own field rather than folded into `stale`, which
        # answers a different question -- whether the index still describes the
        # repository -- and is correctly False here.
        "reindex_required": len(stored) > 0,
        "path": str(store.path),
    }


def apply_descriptions(units: list, store: DescriptionStore, cfg: Config) -> int:
    """Push newly stored text into the in-memory units, re-embedding as needed.

    Without this an agent would describe a unit and keep retrieving against the
    sentence it replaced until the next `refresh`, which is the slowest way to
    discover that the work had an effect.
    """
    authored = store.applicable(units)
    changed = []
    for unit in units:
        text = authored.get(unit.id)
        if text and unit.description != text:
            unit.description = text
            changed.append(unit)
    if changed:
        # One batched call rather than one per unit. A described batch is
        # twenty units by default, and against a remote provider that is the
        # difference between one round trip and twenty.
        texts = [comment_for(unit.description, unit.serial, unit.id) + "\n" + unit.searchable_text for unit in changed]
        for unit, vector in zip(changed, embedder(cfg).many(texts)):
            unit.vector = vector
    return len(changed)


def bootstrap(units: list, store: DescriptionStore, cfg: Config, root: Path, index_report: dict, limit: int | None = None) -> dict:
    """Report how far this repository is from being searchable, and hand over
    the next step's work.

    Indexing a repository is not the same as making it searchable, and nothing
    used to say so. A fresh index retrieves against the sentence the parser
    generated, which adds no word the source did not already have, so a
    question phrased in domain terms reaches nothing. Whoever ran `index` had
    to know that, find `describe` in the documentation, and work out how many
    rounds it would take.

    Idempotent and resumable by construction, because it reports the state
    rather than remembering a position: run it, do the step it names, run it
    again. Nothing here decides anything the other rungs did not already
    decide; it reads which rung this repository is on and says so.
    """
    batch = describe_batch(units, store, cfg, cfg["describe.batch"] if limit is None else limit)
    promotion = summarise_documentation(units, store, plan_documentation(units, store, root), root)

    if batch["remaining"]:
        step = {
            "action": "describe",
            "remaining": batch["remaining"],
            "rounds_at_this_batch_size": -(-batch["remaining"] // max(len(batch["units"]), 1)),
            "why": (
                "Retrieval can only match words that exist somewhere in the index, and a generated "
                "description restates the signature. Until somebody writes what a unit is for, a "
                "question phrased in domain terms reaches nothing."
            ),
            "how": [
                "read `guidance`, then write one description for each unit in `batch`",
                'send them back: {"action":"describe_put","descriptions":[{"id":...,"text":...}]}',
                "or from a shell: rag-your-code describe import written.json",
                "then run bootstrap again for the next batch",
            ],
        }
    elif promotion["insertions"]:
        step = {
            "action": "promote",
            "insertions": promotion["insertions"],
            "files": promotion["files"],
            "why": (
                "A description kept beside the code needs a digest, a relocation lookup and a "
                "pruning rule to survive an edit. The same sentence written into the source needs "
                "none of them."
            ),
            "how": ["rag-your-code describe promote | git apply    # review it first"],
        }
    else:
        step = {
            "action": "ready",
            "why": "Every unit carries a written description, and every declaration that can hold one does.",
            "how": ['rag-your-code search "<concept or behaviour>" --json'],
        }
    return {
        "index": index_report,
        "described": batch["described"],
        "superseded": batch["superseded"],
        "missing": batch["missing"],
        "already_documented": promotion["already_documented"],
        "next": step,
        # Only the rung that needs it carries a work packet, so a caller on any
        # other rung is not handed a batch it has no use for.
        "batch": batch if step["action"] == "describe" else None,
    }
