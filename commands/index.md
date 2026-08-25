---
description: Index this repository for local RAG search, then report which rung it is on — descriptions still to write, a promotion to apply, or nothing left.
argument-hint: "[path]   (default: the current repository)"
---

# /rag-your-code:index

Build or refresh the local retrieval index, and say what the repository still
needs before search is actually good.

## What to do

1. Make sure the package is importable. A plugin install copies these commands
   but not the Python package, so check once per machine. Use `python -m pip`
   so it lands in the interpreter the later commands run under.

   ```bash
   python -c "import ragyourcode" || python -m pip install --user rag-your-code
   ```

2. Run bootstrap against `$ARGUMENTS` if the user named a path, otherwise `.`:

   ```bash
   python -m ragyourcode.cli bootstrap .
   ```

   Use `--compact` for a repository with many thousands of declarations. Use
   `--full` only after a parser or schema upgrade, or suspected corruption —
   the default incremental path reuses unchanged files.

3. Report back three things, briefly:

   - how many declarations were indexed, and whether the run was incremental;
   - **the rung bootstrap named**, in plain language;
   - any warnings or files it could not parse.

## Why the rung matters

Indexing is not the same as being searchable. A fresh index retrieves against a
sentence the parser generated from identifiers the author already chose, so it
adds no word the source did not have — a question phrased in domain terms
reaches nothing. Say so explicitly if descriptions are pending, and offer
`/rag-your-code:describe`, because this is where most of the available
retrieval quality still sits and the user has no other way to learn it.

If the repository is indexing files it should not — a vendored tree, generated
output — that is configuration, not something to work around:

```bash
python -m ragyourcode.cli config set index.ignore '["vendor", "generated"]'
```
