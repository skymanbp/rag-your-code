# RAG Your Code architecture

## Goal

Turn a repository into a searchable layer that a coding agent can use before it
edits code. That layer must be inspectable: every result points to a real file
and line range, includes source, and explains why the unit was indexed.

## What this is, precisely

It is the retrieval half of RAG. There is no generation here and no model
anywhere in the process — the agent calling it supplies both.

That framing is load-bearing, because the embedder is a **signed feature hash**
and cosine over it is a normalised measure of *token overlap*, not of meaning:

| pair | cosine |
|---|---|
| `retry failed card charge` vs itself | 1.0000 |
| `sum two numbers` vs `add a pair of integers` | **0.0000** |
| `计算两个数的和` vs `sum two numbers` | **0.0000** |
| `sum two numbers` vs `delete the user database table` | 0.0000 |

A trained embedding model scores row 2 around 0.8. Here the synonym pair and
the unrelated pair are indistinguishable, because no shared token is no shared
token. What makes retrieval work regardless is that identifiers and docstrings
are already natural language: `retry_charge` contains *retry* and *charge*.
What it cannot do is reach a concept nobody wrote down — which is what
agent-authored descriptions exist to fix, and why they are described below as
keyword expansion rather than as semantics.

## Current end-to-end path

```text
rag-your-code.toml  ----------------.
                                     v
repository
  -> deterministic file walker (configured ignores, suffixes, size cap)
  -> language parser (Python AST; line scanner + rule table for 14 others)
  -> CodeUnit records (stable id, serial, signature, calls, imports, lines)
  -> descriptive text: generated, or authored by an agent  <--- descriptions.json
  -> local deterministic embedding + JSON/float32 persistence
  -> inverted lexical index + hybrid vector retrieval
  -> bounded calls/imports/contains graph expansion (GRAG)
  -> bounded research/open/neighbors/describe/refresh actions (ARAG)
  -> context or JSON-lines response for an agent
```

`CodeUnit` is the contract between all stages. The index never mutates source
files; annotations go to `.rag-your-code/annotations.md` so a user can review,
commit, or discard them independently.

Two inputs are **authored** and belong in version control —
`rag-your-code.toml` and `rag-your-code.descriptions.json`, both at the
repository root. Everything under `.rag-your-code/` is generated and
disposable. The split is deliberate: that directory is what a person deletes to
clear the cache, and authored work must survive it.

## Why the embedder is local

It is deterministic, offline and dependency-free. That gives a reproducible
baseline for a private repository and makes tests exact. It is also an adapter
boundary: a provider can implement `embed(text)` and keep the same records,
persistence and retrieval API.

Agent-authored descriptions are deliberately the cheaper answer to the same
problem a provider embedder would solve. They keep `dependencies = []`, keep
source on the machine, need no API key, and produce output a human can read and
correct instead of opaque floats.

## Parsing

Python goes through the standard-library AST. Every other language goes through
three separated layers:

```text
Layer 1  line scanner    one match attempt per line; the line number IS the
                         loop index, so it cannot drift
Layer 2  rule table      per-language declaration patterns, each anchored
                         inside a single line
Layer 3  span closer     brace balance, or Ruby's `end`, or the next declaration
```

The separation is what fixes things, not the individual patterns. One whole-file
regex previously did all three jobs at once and the coupling produced three
defects at once: catastrophic backtracking (a 530-byte `.js` file took 12.6 s,
growing as roughly n^4.3), an `[^;]*` that consumed newlines and swallowed every
declaration up to the last `)` in a file, and a leading `\s*` that began matches
on preceding blank lines so 9 line numbers in 10 were wrong and the signature was
the blank line. A pattern that cannot see a second line cannot consume one, and
the same rewrite closed all three. Measured after: the same 530-byte file parses
in 0.37 ms and a 10 KB one in 1.40 ms, so growth is linear.

Adding a language is adding rows to the rule table; the scanner does not change.
What counts as a unit is stated once in `tests/fixtures/languages/SPEC.md` -- a
named declaration that owns a body span -- which matches what the Python path
already emits. Layer 3 answers that question too: a declaration reaching `;`
before `{` owns nothing, which is how prototypes, trait and interface method
signatures, Swift protocol requirements and Rust unit structs stay out.

The parser's dispatch table is also the source of truth for which suffixes the
walker accepts. They were separate lists agreeing by coincidence, and a suffix
on only the walker's list produced a file that was read, parsed to nothing, and
reported as a clean index of zero units.

## Configuration

Twelve settings live in one table in `config.py`. The loader, the validator,
the fingerprint, the `config` subcommand and the generated template all read
that table, so a value is named, defaulted, bounded and classified exactly
once. Resolution is CLI flag > `rag-your-code.toml` > built-in default.

There is deliberately no environment-variable layer. An index is an artifact of
a repository, not of a shell, and a setting that changes what gets indexed has
to be visible to everyone who clones it.

An unknown key or an out-of-range value raises rather than being dropped: a
setting silently ignored is indistinguishable, from outside, from one that had
no effect, so the user cannot tell a typo from a misunderstanding.

Four of the twelve — `index.ignore`, `index.suffixes`, `index.max_file_bytes`
and `embedding.dimensions` — decide what an index *contains*. A digest of just
those is written into the index, and a mismatch forces a full rebuild rather
than reuse; reuse is keyed on file content, which cannot notice that the rules
changed. The `embedding.dimensions` case in particular used to fail in silence,
because `search` skips the cosine term when vector widths disagree instead of
raising, so the only symptom was quietly worse ranking. The remaining eight
settings take effect immediately and never invalidate an index.

`tomllib` is standard library from 3.11. Below that, a subset reader in
`config.py` covers what the settings table can express and refuses everything
else with a line number; a differential test checks it against `tomllib` on
every version that ships one. The alternative was a `tomli` runtime dependency,
which would falsify what this project claims about having none.

## Descriptions

Every unit carries a description and that description is part of
`searchable_text`, so its words reach both the inverted index and the vector.
By default it is generated without a model — identifier humanised, parameter
and callee names listed, docstring appended — which introduces no vocabulary
the source did not already contain.

An agent can replace it. `describe_pending` hands out a batch with each unit's
source and a brief; `describe_put` takes descriptions back, validates them, and
applies them to the live units immediately so the same session retrieves on the
new words. The `describe` subcommand offers the same round trip for hosts not
speaking the protocol.

Measured on the fixture repository, one generated sentence replaced by an
agent-written bilingual one:

| query | generated | authored |
|---|---|---|
| `exponential backoff` | no lexical evidence | #1, 1.0172 |
| `double billing safety` | no lexical evidence | #1, 0.3404 |
| `支付网关超时` | no lexical evidence | #1, 0.8632 |

**This is not semantic generalisation.** Matching stays lexical; it moves the
semantic work from query time to index time, and its reach is bounded by how
many ways of saying the thing the agent wrote down. That is what the brief
handed out with each batch asks for, and it is why the default asks for two
languages: the tokenizer emits CJK bigrams, so a Chinese query can only reach a
unit whose indexed text contains Chinese.

Each entry is keyed by unit id **and a digest of the unit's source**. When the
source moves the entry is retained but not applied, the unit returns to the
pending queue, and retrieval falls back to the generated sentence. A
description outliving its code would be a confident wrong answer, which is the
one thing this index exists not to produce. Incremental indexing keeps the cost
proportional: only units in changed files need describing again.

A store change is invisible to a file fingerprint, so the index also records a
digest of the authored text — the same defect class the configuration
fingerprint covers.

## Retrieval strategy

Results combine lexical overlap (exact symbols, error names) with cosine
similarity (ranking among lexical matches). The JSON response includes score,
matched terms, location, description and source. Agents should treat retrieval
as navigation evidence, then open the cited source before editing.

Two candidate sets, with distinct jobs. Every unit reached by any query term is
scored, so recall is complete. A *selective* subset — the units reached by a term
occurring in under a tenth of the corpus — additionally receives a cosine score,
because a 384-dimension dot product for every unit a stopword-class term touches
is pure cost. Letting the selective set decide who gets scored *at all* was a
defect: units matching more query terms went unranked and `--limit 8` returned a
single result on a 116-unit repository.

With no lexical overlap anywhere, scoring falls back to pure cosine so a query
still returns something. On a small corpus that fallback returns units with an
empty `matched_terms` and a near-zero score, which is the honest signal that
nothing actually matched.

Complete recall is not free. Measured at 10,000 units, mean query time went from
1.63 ms to 3.90 ms — the earlier figure was cheap because it scored a subset and
under-filled the result list. Scoring accumulates match counts straight from the
posting lists, materialises only the `limit` results actually returned, and
recovers each one's matched terms by binary search over the sorted postings;
without those three the same recall measured 16.9 ms.

## Large repositories

Index schema 2 stores per-file hashes. One `RepositorySnapshot` is taken per run
and shared by parsing and publication: hashing in a second walk let a save
landing between the two record a file's new hash beside units parsed from its
old content, after which `fingerprint` reported the index fresh and every later
incremental run reused the stale units permanently. Sharing the snapshot also
took a run from four tree walks to one. Re-indexing reuses parsed units and
vectors for unchanged files while preserving repository-global serials. Use
`index --full` to discard that cache. Use `index --compact` to move 384-d
vectors from verbose JSON numbers into a float32 sidecar; the metadata remains
inspectable JSON. Index publication is atomic: content-addressed vector files
are written before an atomic JSON pointer replacement, and stale sidecars are
removed after publication. Embedding provider/version metadata invalidates
incompatible cached vectors automatically.

Search tokenization is cached in an in-memory inverted index for an agent
session. Graph expansion is capped by hop count and per-unit edge budgets.
Symlinked source files and source files above `index.max_file_bytes` (5 MiB by
default) are skipped, to prevent repository escape and generated-file memory
spikes. Beyond roughly 100k units, JSON loading and the no-overlap vector
fallback become the next bottlenecks; the appropriate next storage layer is
SQLite metadata plus an ANN vector index, not a larger JSON file.

## GRAG

The current graph contains only conservative, inspectable relationships:
`calls`, `imports`, and `contains`. A call resolves on an exact match of the
text the parser recorded. Falling back to the last dotted segment is a guess and
is allowed only when the head of the path is attributable to this repository —
`self`/`cls`, or a module some file here defines. Unrestricted, that fallback
gave `os.path.join` a `calls` edge into an unrelated local `join`; foreign
prefixes now resolve to nothing, as this section already promised. `search --graph --hops 1` retrieves normal
seeds and propagates a decayed score to bounded neighbors. Every
expanded result carries the exact graph path as evidence. Unresolved or
ambiguous symbols are omitted or capped rather than guessed.

## ARAG

The JSON-lines agent supports `search`, `research`, `neighbors`, `open`,
`describe_pending`, `describe_put`, `refresh`, and `stats`. `research` is a
deterministic two-stage controller: search, then at most one graph expansion
when confidence is low. It returns each step and a stop reason. `open` rejects
paths outside the repository root, refuses files above `agent.max_open_bytes`,
and truncates its reply at `agent.max_open_chars` with `truncated: true` — a
line count is not a size, and a three-line file can hold megabytes on one line.
Graph/research hop and step budgets are capped, and non-finite numeric fields
saturate at their bound rather than raising.

No single request may end a session. The loop reports a malformed field as
`invalid_request` and anything unanticipated as `request_failed` with the
exception type, then serves the next line. Enumerating expected exception types
was the earlier design and the reason `limit: 1e400` terminated the daemon. This is the safe
contract for a future LLM planner; an LLM may propose follow-up queries but
must not bypass these budgets or evidence requirements.

`stats` distinguishes two questions that are easy to conflate. `stale` says
whether the index still describes the repository; `index_behind` says whether
descriptions stored this session have reached the published index. After a
`describe_put` the live units are current and the file on disk is not, so the
first is correctly `false` while the second is `true`.

Request and response lines are UTF-8 in both directions regardless of the
console codepage: `main()` pins the process streams rather than inheriting the
OS locale. Without that pin a non-UTF-8 console silently mis-decoded a UTF-8
query into a zero-result, exit-0 answer, and a response holding a character
outside the codepage terminated the subprocess.

## Measured envelope

One representative synthetic Windows run (500 files, 20 functions/file, 10,000
units) took **1.84 s** for full parsing and embedding and **0.207 s** for a
one-file incremental refresh (**8.9x**). Compact storage was **35.6%** of
readable JSON (20.8 MB against 58.3 MB). In an isolated agent process, 10,000
units loaded in **45.4 ms**, built a 10,509-term inverted index in **117.7 ms**,
used **58.7 MiB** current and **65.0 MiB** peak RSS, and full-recall hybrid
queries averaged **3.90 ms** (median 3.22 ms over 200 warmed samples). A full
stale stat walk cost **60.4 ms**; the one-second monitor cache made repeated
checks effectively free (0.0004 ms).

Four runs bound the spread: build and walk timings vary by a few percent, and
`compact_write_ms` and `search_index_ms` by considerably more, so treat any
single figure as directional rather than as a service level. The archived run
is the one closest to the four-run centre and is `large-benchmark-result.json`.

The query estimator was itself a defect until 0.4.0: ten cold samples of a
sub-millisecond call once made an unchanged query path look like a real
regression across three runs. It now warms up and takes 200 samples, and
records the median beside the mean so a reader can judge what the number is
worth.

## Evolution plan

1. **Provider adapters:** optional OpenAI/Ollama/sentence-transformer
   embeddings selected by configuration, with a local fallback and recorded
   provider/version. Agent-authored descriptions are the cheaper answer to the
   same problem and land first deliberately; a provider would buy true synonym
   matching at the cost of the no-dependency, no-network, reproducible-index
   properties, and that trade should be made knowingly.
2. **Richer parsing:** Tree-sitter for JavaScript/TypeScript/Go/Rust/Java/C++,
   capturing definitions, references, tests, inheritance and configuration
   symbols. This would also supply `qualified_name` for non-Python languages,
   which the line scanner currently sets equal to `name`.
3. **Persistent scale layer:** SQLite metadata and an ANN vector index once
   repositories exceed the measured JSON envelope.
4. **Richer GraphRAG:** `implements`, `tests`, `configures` and git co-change
   edges, with confidence and provenance on every edge.
5. **LLM planner:** bounded follow-up queries, preserving the current tool
   budgets, privacy policy and observable stop reasons.
6. **Evaluation:** multi-hop graph questions and real repository tasks in the
   golden set; recall@k, citation and edge accuracy, latency, context budget.

## Safety and privacy

No source leaves the machine. There is no network code to disable.

A repository being scanned is untrusted input, and that includes any
`.rag-your-code/index.json` it ships. Nothing read out of an index may name a
filesystem path to act on: the vector sidecars a run supersedes are enumerated
from the naming scheme `write_index` itself uses, never from the index being
replaced. Enumerating also reclaims sidecars orphaned by an earlier run whose
index was unreadable.

`rag-your-code.descriptions.json` is committed and will therefore meet merge
conflicts and hand-editing. A malformed one is treated as empty rather than
fatal: the cost is retrieval quality, which describing again recovers, where
refusing to search until it is repaired would not be recoverable at all.

External embedding providers, when added, must be opt-in, clearly reported in
the index metadata, and support path and content exclusion rules.
