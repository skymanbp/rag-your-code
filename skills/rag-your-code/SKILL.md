---
name: rag-your-code
description: Index and search the current codebase with local, explainable RAG records.
---

# RAG Your Code

Use this skill when repository context is broad or a symbol's implementation is difficult to locate.

## Workflow

0. Make sure the package is importable. A plugin install copies this skill but
   not the Python package, so check once per machine and install if the import
   fails. Use `python -m pip` rather than a bare `pip` so the package lands in
   the same interpreter the later commands run under.

   ```bash
   python -c "import ragyourcode" || python -m pip install --user rag-your-code
   ```

1. Build or refresh the index from the repository root:

   ```bash
   python -m ragyourcode.cli index .
   ```

   The report includes `pending_descriptions`. If it is large, step 5 is where
   most of the retrieval quality on this repository is still sitting.

2. Retrieve focused context before making a change:

   ```bash
   python -m ragyourcode.cli search "<concept or behavior>" --json --limit 8
   ```

   Add `--graph --hops 1` when callers, callees, containment, or small imported
   modules are relevant. Prefer one hop; use two only when the first path
   provides concrete edge evidence.

   **Matching is lexical.** The embedder is a feature hash, so a query sharing
   no word with a unit scores zero against it — synonyms do not match. Query in
   the vocabulary the code uses: prefer `retry charge gateway timeout` over
   "重试扣款失败", and try two or three wordings before concluding something is
   absent. A result with an empty `matched_terms` and a near-zero score is the
   no-lexical-overlap fallback, which means nothing actually matched.

3. Read the returned file and line locations directly before editing. Treat
   retrieved snippets as navigation and context, not as permission to change
   unrelated files.

4. For a subprocess integration, start `python -m ragyourcode.cli agent --root .`
   and send one JSON request per line. Supported actions are `search`,
   `research`, `neighbors`, `open`, `describe_pending`, `describe_put`,
   `refresh`, and `stats`. Use `research` only for ambiguous questions; it is
   capped at two observable steps.

5. **Describe what is pending.** Every unit's description is indexed, and by
   default it is generated without a model — the identifier humanised, the
   parameter and callee names listed, the docstring appended. It adds no
   vocabulary the source did not already have, which is why a query for a
   concept nobody wrote down finds nothing. Writing those words is work only
   you can do:

   ```json
   {"action":"describe_pending","limit":20}
   {"action":"describe_put","descriptions":[{"id":"payments.py:4:retry_charge","text":"..."}]}
   ```

   Each batch carries the unit's source and a brief. Follow the brief: write
   what the unit is *for* in domain terms, the failure it handles, and the
   obvious synonyms for each — those synonyms are the entire mechanism. Do not
   restate the signature, and do not describe behaviour the source does not
   show. Stored descriptions apply to the live session immediately; call
   `refresh` when you are done so the published index carries them too.

   Outside the protocol, `describe status`, `describe export` and
   `describe import` do the same round trip.

6. Run `python -m ragyourcode.cli annotate` when a durable, numbered semantic
   inventory is useful. It writes `.rag-your-code/annotations.md` and leaves
   source files untouched.

## Retrieval discipline

Use several narrow queries for ambiguous tasks, inspect the highest-scoring
results, and refresh the index after large edits. Always preserve the returned
path and line range when citing code in a response.

For repositories with many thousands of functions, index with `--compact` and
reuse the default incremental refresh. Use `--full` only after parser or index
schema changes, or suspected cache corruption.

If the repository indexes files it should not — a vendored tree, generated
output — that is configuration, not a reason to filter results by hand:

```bash
python -m ragyourcode.cli config set index.ignore '["vendor", "generated"]'
python -m ragyourcode.cli index .
```

`config list` shows every setting, its effective value, and whether changing it
forces a rebuild.
