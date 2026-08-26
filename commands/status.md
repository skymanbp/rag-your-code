---
description: Check the health of this repository's RAG index — whether it is stale, how much of it carries written descriptions, and which settings are in force.
---

# /rag-your-code:status

Report whether search here can be trusted right now, and what would improve it.

## What to do

```bash
python -m ragyourcode.cli describe status
python -m ragyourcode.cli config list
```

Then a live query, to prove retrieval actually answers rather than only that
the files exist:

```bash
python -m ragyourcode.cli search "<something this repository certainly does>" --json --limit 3
```

## What to report

Four things, in this order, and briefly:

1. **Is the index current?** Read it from a field rather than from a warning:
   `stale_index` in `describe status`, `stale` in `search --json`. `config
   list` never opens the index and reports nothing about it. Three different
   things make it stale and only one is a file edit: the repository content
   moved, the rules that decide what a unit is changed, or the written
   descriptions changed. Any of them means `/rag-your-code:index`.

2. **Description coverage** — described, superseded and missing.
   *Superseded* is the interesting one: something was written about that
   declaration and the code has since changed, so it is deliberately not
   applied. Those are re-describe work, not lost work.

3. **Which embedder is in force.** `embedding.provider` is one of
   `signed-feature-hash` (the default — offline, no dependency, matching is
   lexical), `sentence-transformers` (a model on this machine) or
   `openai-compatible` (a service). Say which, because it changes what
   retrieval can reach. **Do not switch it for the user:** one adds a
   dependency and downloads weights, the other can send their source to a third
   party, and both are theirs to decide.

4. **The next useful move.** Usually one of: refresh the index, run
   `/rag-your-code:describe`, or narrow `index.ignore` if a vendored or
   generated tree is being indexed.

## Do not tune the evidence bars

If searches come back empty, that is `search.min_coverage` and
`search.min_concentration` doing their job — refusing to hand back a plausible
wrong declaration. Lowering them restores guessing. Report low description
coverage instead; that is the real cause and the real fix.
