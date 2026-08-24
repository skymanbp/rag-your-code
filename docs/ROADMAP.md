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

### P0 — Foundation *(landed)*

Version control, ignore rules, removal of stray run artifacts, this document.
Not a polish item: without git, no later phase is revertible or bisectable.

### P1 — Stop the bleeding (root causes C, D) *(landed)*

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

### P2 — Build the ruler *(landed)*

The golden set currently holds seven queries, all resolving to Python units, so
the parser can regress arbitrarily on the seven other languages README.md names
while the suite stays green. This phase adds per-language fixtures with expected
unit names, line ranges, and signatures — the ground truth P3 is graded against.

Ordering is deliberate: written after P3, these fixtures would encode whatever
the new parser happens to do.

### P3 — Parser: three-layer rewrite (root causes A, B) *(landed)*

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

### P4 — Retrieval correctness (root cause E) *(landed)*

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

### P5 — Agent protocol robustness *(landed)*

Catch-all around the request loop (a single `1e400` in a request currently kills
the subprocess), a real output bound on `open`, and an ignore list for it.

### P6 — Release bar *(landed)*

`LICENSE` (pyproject declares MIT with no license text in the tree or the built
wheel), `.claude-plugin/marketplace.json`, an install step in `SKILL.md` (which
today tells an agent to run a module that nothing installs), pyproject
classifiers/URLs/dev extra, `py.typed`, `requires-python` corrected to match the
`tomllib` import in the test suite, and CI. CI lands last so it gates the fixed
suite rather than the broken one.

## Decided since

The plugin manifest and marketplace entry now carry `homepage` and `repository`
pointing at `https://github.com/skymanbp/rag-your-code`. They were left empty
through P6 because the repository had no remote and a URL that resolves to
nothing is worse than an absent field; the remote now exists.

## Still open

Qualified names for non-Python languages. `CodeUnit` carries `qualified_name`,
and the Python path fills it (`Svc.helper`), but the line scanner sets it equal
to `name`. A scope stack keyed on brace depth would supply it and would improve
`contains` edges; it was outside P3's scope, which was root causes A and B.

## Next: 0.4.0

0.3.0 closed the gap between what the code claimed and what it did. 0.4.0 is
the first pass that adds a claim, and it rests on one measured fact.

### The measurement that motivates it

The embedder is a signed feature hash (`embeddings.py`), so `cosine` is a
normalised measure of *token overlap*. It carries no semantics whatever:

| pair | cosine |
|---|---|
| `retry failed card charge` vs itself | 1.0000 |
| `sum two numbers` vs `add a pair of integers` | **0.0000** |
| `计算两个数的和` vs `sum two numbers` | **0.0000** |
| `sum two numbers` vs `delete the user database table` | 0.0000 |

A real embedding model scores row 2 around 0.8. Row 4 is the control: a synonym
pair and an unrelated pair are indistinguishable, because zero shared tokens is
zero either way.

The golden set's paraphrase queries still reach top-1, but on a thin margin
supplied by the developer's own docstring: `check whether a credential is valid
and has not expired` matches `verify_session_token` on the single content word
`expired` (0.3293) ahead of `retry_charge` (0.2401) — whose only matched terms
are the stopwords `a` and `and`.

### P7 — Configuration layer

Seven classes of tunable are module constants today and can only be changed by
editing installed source: ignore list and source suffixes and size cap
(`indexer.py`), embedding dimensions (`embeddings.py`), the 0.15 hybrid weight
(`search.py`), the `limit`/`max_chars` defaults and the agent `open` bounds
(`cli.py`).

Resolution order is CLI flag > `.rag-your-code/config.toml` > built-in default.
No environment variables and no new dependencies: `tomllib` is standard library
from 3.11, and the 3.10 leg reads the same file with a minimal parser rather
than adding `tomli` to the runtime.

One trap this phase must handle rather than discover later: changing
`dimensions` or `suffixes` invalidates an existing index, and a dimension
mismatch is currently *silent* — `search.py`'s guard drops the vector score to
zero rather than raising. The index must record a fingerprint of the
configuration that produced it and force a full rebuild when it differs.

### P8 — Agent-authored descriptions

`annotate.py` says it in its own first line: descriptions are generated
*without an LLM*. `describe_python` humanises the identifier, lists parameter
and callee names, and appends the docstring verbatim. It introduces no
vocabulary that was not already in the source, which is exactly why retrieval
cannot reach a concept the author never wrote down.

The architecture already has the seam. `description` is part of
`searchable_text` (`models.py`), the vector is computed from the description
plus that text (`indexer.py`), and incremental reuse copies whole `CodeUnit`s
for unchanged files, so a better description survives re-indexing untouched.

So the agent already consuming this index writes the descriptions, at index
time, through two new protocol actions (`describe_pending` / `describe_put`)
and a `describe` subcommand for the non-protocol case. They are stored in
`.rag-your-code/descriptions.json`, keyed by unit id **and source hash** so a
description can never outlive the code it describes, and committed to Git so
one person's pass benefits the team and CI.

Measured on `benchmarks/fixture`, replacing one template description with an
agent-written bilingual one:

| query | template description | agent description |
|---|---|---|
| `exponential backoff` | not in top 3 | **#1**, 1.0175 |
| `double billing safety` | not in top 3 | **#1**, 0.3369 |
| `支付网关超时` | not in top 3 | **#1**, 0.8636 |
| `resend a payment after a transient upstream error` | #1, 0.3211 | #1, **0.9178** |

Three queries move from missing entirely to first. The fourth already matched;
its margin stops depending on a stopword.

**What this is, stated plainly:** it moves the semantic work from query time to
index time. It is not semantic generalisation — matching stays lexical, so a
description saying `retry` still cannot answer a query saying `resend` unless
the description also says so. It is LLM-authored keyword expansion, and its
quality is bounded by how many ways of saying the thing the agent thought to
write down. Descriptions are bilingual by default (configurable), because the
row above shows a Chinese query going from unreachable to first.

## Non-goals

Provider-backed embeddings, Tree-sitter, and the SQLite/ANN storage layer stay
on the evolution plan in ARCHITECTURE.md. P8 is deliberately the cheaper answer
to the same problem provider embeddings solve: it keeps `dependencies = []`, it
keeps source on the machine, it needs no API key, and its output is text a human
can read and correct rather than opaque floats.
