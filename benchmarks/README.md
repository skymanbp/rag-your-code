# The rulers

Six scripts. Five of them measure something the README publishes, and the
rule for all of them is the same: **a score is meaningless without the corpus
it was taken on.** Two runs of an unchanged `search.py` reported 0.257 and
0.229 hit@1 on the foreign ruler, and both were right — that repository had
grown by ninety units in between, and nothing in the output said so. Since
1.4.0 the foreign ruler's subject is [vendored at a pinned tag](corpus/), so
that particular drift cannot happen again; the fingerprints stay because the
*own* corpus still moves with every commit.

## Retrieval — the four rulers

```powershell
# C: this repository, agent-written descriptions
python -m benchmarks.repo_queries
# B: this repository, parser-generated sentences only
python -m benchmarks.repo_queries --cold
# D: questions with no answer anywhere
python -m benchmarks.repo_queries --questions benchmarks/absent_queries.json

# A: a repository nobody here wrote, carried at a pinned tag in corpus/
python -m ragyourcode.cli index benchmarks/corpus/flask
python -m benchmarks.repo_queries --index benchmarks/corpus/flask --questions benchmarks/cold_queries.json
python -m benchmarks.repo_queries --index benchmarks/corpus/flask --questions benchmarks/absent_queries.json
```

A, B and C grade whether the answer is **found**; D grades whether silence is
**kept**, and is scored on silence rather than hit@k because there is nothing
to hit. D is kept out of the aggregate: averaging a question that should return
something with one that should return nothing produces a number that improves
when either half gets worse.

Every report prints `corpus  <n> units, fingerprint <hex>`. Quote it with any
figure taken from here. `--min-coverage` and `--min-concentration` vary one
gate at a time, which is how the ablation table in [ROADMAP](../docs/ROADMAP.md)
was produced — `--min-concentration 0` leaves the coverage bar alone in place.

`benchmarks/absent_queries.json` asserts that nothing in either repository
answers its questions, and `tests/test_absent_queries.py` enforces that claim
against both indexes. It has fired five times: most recently on a docstring
that named the very subject it was explaining, and before that on a helper
named after the statistic it computes. Rewrite the offending name, not the
question. `CONTRIBUTING.md` keeps the tally and the rules each firing added.

## The head-to-head against a Grep loop

```powershell
python -m benchmarks.grep_baseline
python -m benchmarks.grep_baseline --index benchmarks/corpus/flask     --questions benchmarks/cold_queries.json --root benchmarks/corpus/flask
```

Produces both tables in README section 7. The baseline takes the query's words,
drops the ones the corpus itself shows are everywhere, runs one substring
search per remaining word over exactly the files the index was built from, and
ranks each file by how many distinct words hit it, ties broken on path. Both
arms are scored at file granularity and both payloads are counted in
characters, because counting one side in lines and the other in characters
compares nothing.

Determinism is load-bearing: an earlier version iterated a set and let
string-hash randomisation reorder ties, which moved first-place accuracy
between 34.3% and 22.9% on identical inputs.

## Latency

```powershell
python -m benchmarks.query_latency [--samples 420] [--repeats 5]
```

Times one warm `search()` and one query the index refuses, over this
repository's own index. It repeats the whole measurement and prints the
spread, because a single run does not have the precision the earlier figures
were quoted to — four consecutive runs on an idle machine put p95 at 1.01,
1.02, 1.22 and 2.06 ms. Run it on an idle machine; an earlier figure taken
while a model was embedding in another process came out at twice the cost.

The figures the README used to carry came from a script that was never
committed, on a corpus that no longer exists. That is what this file is for.

## Scale, and a cold process

```powershell
python -m benchmarks.large_repo --files 500 --functions 20 --output large-benchmark-result.json
python -m benchmarks.measure_index .rag-your-code/index.json
```

`large_repo` builds a deterministic synthetic repository and reports full and
one-file incremental build time, the speedup between them, and compact float32
index size against readable JSON. `measure_index` loads an existing index in a
fresh process and reports load time, search-index build time and resident
memory — separate because both are startup costs a warm benchmark hides.

## The golden fixture

```powershell
python -m benchmarks.run_benchmark --output benchmark-result.json
```

Seven queries over a five-file source-controlled fixture, comparing lexical
overlap against lexical plus cosine. It is a regression tripwire, not a ruler:
seven queries over nine units cannot distinguish a real improvement from
noise, which is why `repo_queries.py` exists. Keep the expected paths and names
stable, and record the embedding provider with any published result.
