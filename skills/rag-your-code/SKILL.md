---
name: rag-your-code
description: Index and search the current codebase with local, explainable RAG records.
---

# RAG Your Code

Use this skill when repository context is broad or a symbol's implementation is difficult to locate.

## Workflow

0. Make sure the package is importable. A plugin install copies this skill
   but not the Python package, so check once per machine and install if the
   import fails. Use `python -m pip` rather than a bare `pip` so the package
   lands in the same interpreter the later commands run under.

   ```bash
   python -c "import ragyourcode" || python -m pip install --user rag-your-code
   ```

1. Build or refresh the index from the repository root:

   ```bash
   python -m ragyourcode.cli index .
   ```

2. Retrieve focused context before making a change:

   ```bash
   python -m ragyourcode.cli search "<concept or behavior>" --json --limit 8
   ```

   Add `--graph --hops 1` when callers, callees, containment, or small imported
   modules are relevant. Prefer one hop; use two only when the first path
   provides concrete edge evidence.

3. Read the returned file and line locations directly before editing. Treat retrieved snippets as navigation/context, not as permission to change unrelated files.

4. For a subprocess integration, start `python -m ragyourcode.cli agent --root .`
   and send one JSON request per line. Supported actions are `search`,
   `research`, `neighbors`, `open`, `refresh`, and `stats`. Use `research` only
   for ambiguous questions; it is capped at two observable steps.

5. Run `python -m ragyourcode.cli annotate` when a durable, numbered semantic inventory is useful. It writes `.rag-your-code/annotations.md` and leaves source files untouched.

## Retrieval discipline

Use several narrow queries for ambiguous tasks, inspect the highest-scoring results, and refresh the index after large edits. Always preserve the returned path and line range when citing code in a response.

For repositories with many thousands of functions, index with `--compact` and
reuse the default incremental refresh. Use `--full` only after parser/index
schema changes or suspected cache corruption.
