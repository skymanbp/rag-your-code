# Testing and evaluation

## End-to-end coverage

`tests/test_e2e_cli.py` runs the real subprocess entry point through `index`,
`search --json`, `annotate`, and `agent`. It also edits a source file and
asserts that the old index reports `stale: true`; stale annotation generation
is rejected with exit code 2. The agent protocol test covers malformed JSON
recovery and a subsequent valid request.

## Full debug coverage

The test suite currently covers:

- Python AST units, nested qualified names, imports, calls, serials, and vectors;
- generic parser declarations across Ruby, Kotlin, Swift, PHP, Go, Rust, Shell,
  C# and JavaScript, including a no-trailing-newline edge case;
- JSON index round trips and vector persistence;
- zero-result limits and agent output contracts;
- schema 1 migration, embedding-version invalidation, global serial stability,
  compact vector sidecars, atomic cleanup, and explicit degraded state;
- conservative call/import/containment graph edges, graph evidence and ARAG
  step/stop contracts;
- malformed/non-object requests, numeric bounds, path traversal and missing
  index errors;
- plugin-facing CLI help and source-preserving annotations;
- a crafted `vector_store.path` in a shipped index failing to delete a source
  file, and orphaned sidecars being reclaimed;
- the agent subprocess answering a UTF-8 CJK query and echoing an
  outside-the-codepage character on a simulated non-UTF-8 console;
- the daemon's failure contract: non-finite numeric fields, an injected
  unanticipated handler exception, the preserved `invalid_request` code, and
  `open` bounded by size as well as by line count;
- retrieval correctness: `limit` filled when a rare term joins common ones,
  every lexically matching unit reachable, an index self-reporting stale after a
  write between parse and publish, and call edges omitted for foreign module
  prefixes while local-module and receiver calls still resolve.

Subprocess tests pin `PYTHONPATH` to `src/` through `cli_env()`, so they
exercise the working tree rather than whatever copy pip has installed.

Run:

```powershell
pytest -q
python -m compileall -q src tests benchmarks
```

`pip check` may report conflicts from unrelated globally installed packages;
this project has no runtime dependencies and its wheel builds with
`python -m pip wheel . --no-deps`.

## Baseline versus hybrid

Run:

```powershell
python -m benchmarks.run_benchmark --output benchmark-result.json
```

The source-controlled [golden set](../benchmarks/golden.json) contains seven
queries, including paraphrases that are deliberately harder than exact symbol
lookups. The benchmark compares lexical-only retrieval to cached lexical plus
vector retrieval and reports precision@3, recall@3, top-1 accuracy, MRR,
mean/P95 query latency, parse/embed latency, and inverted-index build latency.

Golden tests are warranted now. Retrieval ranking is a user-visible contract,
and the paraphrase queries caught a real regression where the first hybrid
scoring rule reduced top-1 accuracy from `1.0` to `0.857`. Making lexical
evidence dominant restored `1.0` without giving up vector tie-breaking. Keep
the set small and reviewable; add repository-specific cases before changing
the embedding provider or ranking weights.

The graph fixture also measures a cross-function workflow. Hybrid retrieval
has related-callee recall@3 of `0.0`; bounded graph expansion recovers the
called function at recall@3 `1.0`, with the `calls` path attached as evidence.
