# RAG Your Code architecture

## Goal

Turn a repository into a searchable semantic layer that a coding agent can use before it edits code. The semantic layer must be inspectable: every result points to a real file and line range, includes source, and explains why the unit was indexed.

## Current end-to-end path

```text
repository
  -> deterministic file walker (ignore generated/dependency trees)
  -> language parser (Python AST; line scanner + rule table for 14 others)
  -> CodeUnit records (stable id, serial, signature, calls, imports, lines)
  -> descriptive sidecar text (RAG[serial] comments)
  -> local deterministic embedding + JSON/float32 persistence
  -> inverted lexical index + hybrid vector retrieval
  -> bounded calls/imports/contains graph expansion (GRAG)
  -> bounded research/open/neighbors/refresh actions (ARAG)
  -> context or JSON-lines response for an agent
```

`CodeUnit` is the contract between all stages. The index never needs to mutate source files; annotations are written to `.rag-your-code/annotations.md` so a user can review, commit, or discard them independently.

## Why the first implementation is local

The feature-hash embedder is deterministic, offline, and dependency-free. That gives a working baseline for private repositories and makes tests reproducible. It is intentionally an adapter boundary: a future provider can implement `embed(text)` and keep the same records, persistence, and retrieval API. For larger repositories, the next storage step is SQLite plus an ANN index (FAISS, Qdrant, or LanceDB).

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

## Retrieval strategy

Results combine lexical overlap (useful for exact symbols and error names) with cosine similarity (useful for concepts such as "retry failed HTTP requests"). The JSON response includes score, matched terms, location, description, and source. Agents should treat retrieval as navigation evidence, then open the cited source before editing.

Two candidate sets, with distinct jobs. Every unit reached by any query term is
scored, so recall is complete. A *selective* subset — the units reached by a term
occurring in under a tenth of the corpus — additionally receives a cosine score,
because a 384-dimension dot product for every unit a stopword-class term touches
is pure cost. Letting the selective set decide who gets scored *at all* was a
defect: units matching more query terms went unranked and `--limit 8` returned a
single result on a 116-unit repository.

Complete recall is not free. Measured at 10,000 units, mean query time went from
1.63 ms to 3.82 ms — the earlier figure was cheap because it scored a subset and
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
Symlinked source files and source files larger than 5 MiB are skipped by
default to prevent repository escape and generated-file memory spikes.
The synthetic benchmark currently covers 10,000 functions and records full vs
incremental build time and readable vs compact index size. Beyond roughly
100k units, JSON loading and no-overlap vector fallback become the next bottlenecks;
the appropriate next storage layer is SQLite metadata plus an ANN vector index,
not a larger JSON file.

## GRAG

The current graph contains only conservative, inspectable relationships:
`calls`, `imports`, and `contains`. A call resolves on an exact match of the
text the parser recorded. Falling back to the last dotted segment is a guess and
is allowed only when the head of the path is attributable to this repository —
`self`/`cls`, or a module some file here defines. Unrestricted, that fallback
gave `os.path.join` a `calls` edge into an unrelated local `join`; foreign
prefixes now resolve to nothing, as this section already promised. `search --graph --hops 1` retrieves normal
semantic seeds and propagates a decayed score to bounded neighbors. Every
expanded result carries the exact graph path as evidence. Unresolved or
ambiguous symbols are omitted or capped rather than guessed.

## ARAG

The JSON-lines agent supports `search`, `research`, `neighbors`, `open`,
`refresh`, and `stats`. `research` is a deterministic two-stage controller:
semantic search, then at most one graph expansion when confidence is low. It
returns each step and a stop reason. `open` rejects paths outside the repository
root, refuses files above the indexer's 5 MiB source cap, and truncates its
reply at 100k characters with `truncated: true` — a line count is not a size,
and a three-line file can hold megabytes on one line. Graph/research hop and
step budgets are capped, and non-finite numeric fields saturate at their bound
rather than raising.

No single request may end a session. The loop reports a malformed field as
`invalid_request` and anything unanticipated as `request_failed` with the
exception type, then serves the next line. Enumerating expected exception types
was the earlier design and the reason `limit: 1e400` terminated the daemon. This is the safe
contract for a future LLM planner; an LLM may propose follow-up queries but
must not bypass these budgets or evidence requirements.

Request and response lines are UTF-8 in both directions regardless of the
console codepage: `main()` pins the process streams rather than inheriting the
OS locale. Without that pin a non-UTF-8 console silently mis-decoded a UTF-8
query into a zero-result, exit-0 answer, and a response holding a character
outside the codepage terminated the subprocess.

One representative synthetic Windows run (500 files, 20 functions/file) took
1.82 s for full parsing/embedding and 0.249 s for a one-file incremental refresh
(7.30x). Compact storage was 35.6% of readable JSON. In an isolated agent
process, 10,000 units loaded in 48.6 ms, built the inverted index in 89.5 ms,
used 57.8 MiB current/64.1 MiB peak RSS, and full-recall hybrid queries averaged
3.82 ms. A full stale stat walk cost 83.7 ms; the one-second monitor cache made
repeated checks effectively free (0.0004 ms). These are directional local measurements,
not universal service-level guarantees; see `large-benchmark-result.json`.

## Evolution plan

1. **Provider adapters:** add optional OpenAI/Ollama/sentence-transformer embeddings selected by configuration, with a local fallback and recorded provider/version in the index.
2. **Richer parsing:** use Tree-sitter for JavaScript/TypeScript/Go/Rust/Java/C++ and capture definitions, references, tests, inheritance, and configuration symbols.
3. **Persistent scale layer:** move metadata/postings to SQLite and vectors to an ANN index once repositories exceed the measured JSON operating envelope.
4. **Richer GraphRAG:** add `implements`, `tests`, `configures`, and git co-change edges with confidence/provenance on every edge.
5. **LLM planner:** optionally formulate bounded follow-up queries while preserving the current tool budgets, privacy policy, and observable stop reasons.
6. **Evaluation:** expand golden queries with multi-hop graph questions and real repository tasks; measure recall@k, citation/edge accuracy, latency, and context budget.

## Safety and privacy

No source leaves the machine in the default mode. Generated artifacts are isolated under `.rag-your-code/` and ignored by Git.

A repository being scanned is untrusted input, and that includes any
`.rag-your-code/index.json` it ships. Nothing read out of an index may name a
filesystem path to act on: the vector sidecars a run supersedes are enumerated
from the naming scheme `write_index` itself uses, never from the index being
replaced. Enumerating also reclaims sidecars orphaned by an earlier run whose
index was unreadable.

External embedding providers, when added, must be opt-in, clearly reported in
the index metadata, and support path/content exclusion rules.
