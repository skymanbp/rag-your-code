# Retrieval benchmark

Run the reproducible comparison with:

```powershell
python -m benchmarks.run_benchmark --output benchmark-result.json
```

The fixture is intentionally small and source-controlled. `golden.json` maps
natural-language tasks to the expected code units. The benchmark compares:

- **lexical baseline**: exact token overlap over indexed text;
- **hybrid optimized**: lexical overlap plus the deterministic embedding cosine score.

It reports index build time, query mean/P95 latency, precision@k, recall@k,
top-1 accuracy, MRR, and deltas. Timing numbers are environment-dependent;
quality metrics should be stable. A future embedding provider must be evaluated
against this same set plus a harder paraphrase set before becoming the default.

For indexing scale, run:

```powershell
python -m benchmarks.large_repo --files 500 --functions 20 --output large-benchmark-result.json
```

It reports full and one-file incremental build time, speedup, and readable JSON
versus compact float32 index size for a deterministic synthetic repository.

The golden set is warranted already: retrieval quality is a user-facing
contract and ranking changes are otherwise easy to regress silently. Keep
expected paths/names stable, add negative or ambiguous queries as the corpus
grows, and record the embedding provider/version with any published result.
