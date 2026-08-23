# Improvement roadmap

Status of record for the hardening pass that follows the v0.2.0 audit. Each
phase is one commit; each phase ends with the full suite green.

## Why this document exists

An adversarial audit of v0.2.0 produced 94 raw findings. Reported one by one
they read as a punch list. Grouped by cause they are **five root causes**, and
the ordering below follows the causes, not the symptoms.

## Root-cause grouping

| Root cause | Symptoms it produces | Phase |
|---|---|---|
| **A.** `FUNCTION_RE` is one whole-file regex doing five jobs at once (locate, name, dispatch by language, delimit scope, imply the line number) | catastrophic backtracking; wrong `start_line`; empty `signature`; cross-line swallowing; TypeScript yielding zero units | P3 |
| **B.** Line model disagrees with the tokenizer: `str.splitlines()` breaks on `\x0b \x0c \x1c-\x1e \x85    `, `ast` counts only `\n \r\n \r` | Python function bodies silently truncated or lost | P3 |
| **C.** `write_index` trusts a path read out of the index file it is replacing | running the documented `index` command deletes an arbitrary in-tree file, exit code 0 | P1 |
| **D.** Process I/O follows the OS locale codepage instead of the protocol's encoding | the long-lived `agent` subprocess dies on non-ASCII output; CJK queries silently mis-decode and return `[]` | P1 |
| **E.** The vector-candidate set replaces the lexical candidate set instead of narrowing what gets a cosine score | `--limit 8` returns 1 result on this repo's own 116 units | P4 |

Measured evidence for each is recorded in the phase sections below.

## Design principles

1. **One root cause, one change.** Seven symptoms above collapse into five
   edits, not seven patches.
2. **Make the error structurally impossible**, do not add a check for it. A
   line number that *is* the loop index cannot drift; no assertion required.
3. **Data over code.** Adding a language becomes a table row, not a regex edit.
4. **Build the ruler before reshaping the thing being measured.** The
   multi-language golden set (P2) lands *before* the parser rewrite (P3).
5. **The contract does not move.** `CodeUnit`, index schema 2, and the
   JSON-lines agent protocol are unchanged throughout; every fix sits beneath
   them.

## Phases

### P0 — Foundation

Version control, ignore rules, removal of stray run artifacts, this document.
Not a polish item: without git, no later phase is revertible or bisectable.

### P1 — Stop the bleeding (root causes C, D)

Two edits, each deleting a wrong assumption rather than adding machinery.

- **C:** the sidecar to delete is derived from this run's own naming scheme, not
  read out of the previous index. Measured before: a repository shipping a
  crafted `.rag-your-code/index.json` whose `vector_store.path` names any file
  under the index directory causes `index` to delete that file and report
  success (`exit code = 0`, `PRECIOUS.py exists = False`).
- **D:** `main()` pins stdin/stdout/stderr to UTF-8. Measured before: on a
  cp936 console (`sys.stdout.encoding == 'gbk'`), one non-representable
  character in a result kills the agent subprocess; a UTF-8 CJK query is
  mis-decoded and returns `results: []` with exit 0.

### P2 — Build the ruler

The golden set currently holds seven queries, all resolving to Python units, so
the parser can regress arbitrarily on the seven other languages README.md names
while the suite stays green. This phase adds per-language fixtures with expected
unit names, line ranges, and signatures — the ground truth P3 is graded against.

Ordering is deliberate: written after P3, these fixtures would encode whatever
the new parser happens to do.

### P3 — Parser: three-layer rewrite (root causes A, B)

Replace the single whole-file regex with three separated layers:

```
Layer 1  line scanner       one match attempt per line; line number is the loop index
Layer 2  language rule table  per-language anchored declaration patterns
Layer 3  span closer        brace balance / `end` keyword / next-declaration fallback
```

Because a pattern now sees exactly one line, the cross-line quantifiers that
caused four of the five symptoms (`[^;]*` consuming newlines, `(?:...|\s)+`
consuming blank lines) cannot exist. The backtracking input size drops from
"file" to "line".

Measured before, on this machine:

| Input | Result |
|---|---|
| `.js`: one function + N whitespace-only lines | n=40 (230 B) 0.256 s · n=60 (330 B) 1.295 s · n=80 (430 B) 4.764 s · n=100 (530 B) **12.630 s** (~n^4.3) |
| idiomatic TypeScript class, 3 methods + constructor | **0 units** |
| `.js`, 4 functions separated by one blank line | 3 of 4 have a wrong `start_line` and an empty `signature` |
| `.py` with `\x0c` inside a string literal | `alpha` source truncated mid-literal; `beta`'s entire body lost |

Layer 3 is conservative by design: brace balancing for `{}` languages, the `end`
keyword for Ruby, and the existing next-declaration fallback where neither
applies. Its limits are documented rather than guessed at.

### P4 — Retrieval correctness (root cause E)

- Candidate set becomes the full lexical set; the selective set decides only
  *which candidates additionally receive a cosine score* — the intent already
  stated in `search.py`'s own comment. Measured before: 116 units, threshold 64,
  `search('sqlite function using json', limit=8)` returns **1** result.
  The latency reason for the current shape is real (a naive full scan measured
  0.49 ms -> 27.53 ms at 10k units), so the fix must keep the selective set for
  vector work while restoring lexical recall.
- Graph edges resolved by bare leaf name currently contradict this module's own
  "omitted rather than guessed" contract; leaf fallback gets constrained.
- `build_units` and `write_index` walk the tree separately, so a write landing
  between them records a fresh hash beside stale units and every later
  incremental run reuses them while reporting `stale: false`. One snapshot,
  shared.

### P5 — Agent protocol robustness

Catch-all around the request loop (a single `1e400` in a request currently kills
the subprocess), a real output bound on `open`, and an ignore list for it.

### P6 — Release bar

`LICENSE` (pyproject declares MIT with no license text in the tree or the built
wheel), `.claude-plugin/marketplace.json`, an install step in `SKILL.md` (which
today tells an agent to run a module that nothing installs), pyproject
classifiers/URLs/dev extra, `py.typed`, `requires-python` corrected to match the
`tomllib` import in the test suite, and CI. CI lands last so it gates the fixed
suite rather than the broken one.

## Non-goals for this pass

Provider-backed embeddings, Tree-sitter, and the SQLite/ANN storage layer stay
on the evolution plan in ARCHITECTURE.md. This pass makes the existing claims
true; it does not add claims.
