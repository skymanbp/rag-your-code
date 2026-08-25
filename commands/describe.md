---
description: Write the searchable vocabulary this repository does not contain — agent-authored descriptions for undescribed declarations, the single biggest lever on retrieval quality.
argument-hint: "[batch size]   (default 20 per round)"
---

# /rag-your-code:describe

Write descriptions for declarations that have none. This is the work that
turns an index into something worth searching, and **nobody but a model that
has read the code can do it.**

## Why this exists

Every unit's description is indexed. By default it is generated without a
model: the identifier humanised, parameters and callees listed, the docstring
appended. It introduces **no vocabulary the source did not already have** —
which is exactly why a query for a concept nobody wrote down finds nothing.

Measured on this project's own four rulers, moving from generated to
agent-written descriptions took first-place accuracy from 0.314 to 0.443 and
top-3 from 0.471 to 0.614, and against a Grep loop it is the difference between
losing (31.4% vs 34.3% on an undescribed repository) and winning decisively
(57.1% vs 25.7% once described).

## What to do

1. See what is pending:

   ```bash
   python -m ragyourcode.cli describe status
   ```

2. Export a batch — `$ARGUMENTS` units if the user gave a number, else 20.
   Each entry carries the unit's source and a written brief:

   ```bash
   python -m ragyourcode.cli describe export --limit 20 > pending.json
   ```

3. **Read each unit's source and write its description.** Follow the brief:

   - say what the unit is *for* in domain terms — the operation, the failure it
     handles, the thing a person would search by;
   - include the obvious synonyms for each, because those synonyms are the
     entire mechanism;
   - do **not** restate the signature or list parameter names — that text is
     already indexed;
   - do **not** describe behaviour the source does not show; the source is in
     the export so you can check;
   - if a unit is trivial, say so briefly rather than padding it.

   Descriptions are bilingual by default, so a question asked in either
   language reaches the code. `config list` shows `describe.languages`.

4. Store them and apply:

   ```bash
   python -m ragyourcode.cli describe import written.json
   python -m ragyourcode.cli index .
   ```

5. Repeat until `describe status` reports nothing pending. Report progress
   after each round rather than silently looping.

## Two things worth knowing

**Descriptions are committed.** They live in
`rag-your-code.descriptions.json` at the repository root, so one person's pass
benefits everyone who clones. Each is keyed by unit id **and a digest of the
unit's source**: when the code changes the description stops being applied and
the unit returns to the queue, because a description that outlived its code
would be a confident wrong answer.

**They can move into the code.** When nothing is pending, offer:

```bash
python -m ragyourcode.cli describe promote | git apply
```

That emits a diff adding a doc comment in each language's own convention, for
declarations that have none. Review it before applying — the tool never writes
source itself. Text that lives in the code needs no digest, no relocation
lookup and no pruning rule to survive a refactor.
