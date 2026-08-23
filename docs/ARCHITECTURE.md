# RAG Your Code architecture

## Goal

Turn a repository into a searchable semantic layer that a coding agent can use before it edits code. The semantic layer must be inspectable: every result points to a real file and line range, includes source, and explains why the unit was indexed.

## Current end-to-end path

```text
repository
  -> deterministic file walker (ignore generated/dependency trees)
  -> language parser (Python AST, conservative multi-language fallback)
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

## Retrieval strategy

Results combine lexical overlap (useful for exact symbols and error names) with cosine similarity (useful for concepts such as "retry failed HTTP requests"). The JSON response includes score, matched terms, location, description, and source. Agents should treat retrieval as navigation evidence, then open the cited source before editing.

## Large repositories

Index schema 2 stores per-file hashes. Re-indexing reuses parsed units and
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
`calls`, `imports`, and `contains`. `search --graph --hops 1` retrieves normal
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
2.02 s for full parsing/embedding and 0.244 s for a one-file incremental refresh
(8.27x). Compact storage was 35.6% of readable JSON. In an isolated agent
process, 10,000 units loaded in 51.3 ms, built the inverted index in 102.7 ms,
used 70.5 MiB current/76.7 MiB peak RSS, and selective hybrid queries averaged
1.236 ms. A full stale stat walk cost 57.1 ms; the one-second monitor cache made
repeated checks effectively free. These are directional local measurements,
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
