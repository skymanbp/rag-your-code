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

1. Build the index and find out what this repository still needs:

   ```bash
   python -m ragyourcode.cli bootstrap .
   ```

   Indexing a repository is not the same as making it searchable. A fresh
   index retrieves against the sentence the parser generated, which adds no
   word the source did not already have, so a question phrased in domain terms
   reaches nothing. `bootstrap` indexes, says which rung this repository is on
   — descriptions to write, a promotion to apply, or nothing left — and hands
   over that rung's work. It reads the state rather than remembering a
   position, so running it again after each round is how you make progress.

   `index` still exists and does only the indexing.

2. Retrieve focused context before making a change:

   ```bash
   python -m ragyourcode.cli search "<concept or behavior>" --json --limit 8
   ```

   Add `--graph --hops 1` when callers, callees, containment, or small imported
   modules are relevant. Prefer one hop; use two only when the first path
   provides concrete edge evidence.

   **Matching is lexical by default.** The embedder is a feature hash, so a
   query sharing no word with a unit scores zero against it — synonyms do not
   match. So query in the vocabulary the code uses: prefer `retry charge
   gateway timeout` over "重试扣款失败", and try two or three wordings before
   concluding something is absent. A result with an empty `matched_terms` and
   a near-zero score is the no-lexical-overlap fallback, which means nothing
   actually matched.

   A repository's owner may have set `embedding.provider` to
   `openai-compatible`, in which case similarity carries real meaning and can
   reach units the words miss. `config list` says which is in force. Do not
   turn it on for them: it can send their source to a third party, and that is
   theirs to decide.

3. Read the returned file and line locations directly before editing. Treat
   retrieved snippets as navigation and context, not as permission to change
   unrelated files.

4. For a subprocess integration, start `python -m ragyourcode.cli agent --root .`
   and send one JSON request per line. Supported actions are `bootstrap`,
   `search`, `research`, `neighbors`, `open`, `describe_pending`,
   `describe_put`, `refresh`, and `stats`. Send `bootstrap` first on an
   unfamiliar repository: it answers what step 1 answers, in one request. Use
   `research` only for ambiguous questions; it is capped at two observable
   steps.

   **A result is navigation, not the file.** `results` carries the identifier,
   path, line range, signature, description, score and matched terms; the code
   arrives once, in the reply's `context`, trimmed to `max_chars`. Use `open`
   for anything the context left out — `omitted_for_budget` says how many
   results that was.

5. **Describe what is pending** — this is the rung `bootstrap` names first,
   and on an undescribed repository it is where most of the available
   retrieval quality still sits. Every unit's description is indexed, and by
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
   `describe import` do the same round trip, and `bootstrap` reports how many
   rounds are left.

   When nothing is pending, `bootstrap` moves on to `describe promote`, which
   emits a patch that writes each description into the source as a doc
   comment. Text that lives in the code needs no digest, no relocation lookup
   and no pruning rule to survive an edit.

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
