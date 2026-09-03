# The rulers

Eight scripts. Seven of them measure something the README publishes, and the
rule for all of them is the same: **a score is meaningless without the corpus
it was taken on.** Two runs of an unchanged `search.py` reported 0.257 and
0.229 hit@1 on the foreign ruler, and both were right — that repository had
grown by ninety units in between, and nothing in the output said so. Since
1.4.0 the foreign subjects are [vendored at pinned tags](corpus/), so that
particular drift cannot happen again; the fingerprints stay because the *own*
corpus still moves with every commit.

## Retrieval — the five rulers

```powershell
# C: this repository, agent-written descriptions
python -m benchmarks.repo_queries
# B: this repository, parser-generated sentences only
python -m benchmarks.repo_queries --cold
# D: questions with no answer anywhere, on each of the three corpora
python -m benchmarks.repo_queries --questions benchmarks/absent_queries.json

# A: Flask 3.1.3, Python, carried at a pinned tag in corpus/
python -m ragyourcode.cli index benchmarks/corpus/flask
python -m benchmarks.repo_queries --index benchmarks/corpus/flask --questions benchmarks/cold_queries.json
python -m benchmarks.repo_queries --index benchmarks/corpus/flask --questions benchmarks/absent_queries.json

# E: cobra v1.9.1, Go — the third corpus, and the first that is not Python
python -m ragyourcode.cli index benchmarks/corpus/cobra
python -m benchmarks.repo_queries --index benchmarks/corpus/cobra --questions benchmarks/cobra_queries.json
python -m benchmarks.repo_queries --index benchmarks/corpus/cobra --questions benchmarks/absent_queries.json
```

A, B, C and E grade whether the answer is **found**; D grades whether silence
is **kept**, and is scored on silence rather than hit@k because there is
nothing to hit. D is kept out of the aggregate: averaging a question that
should return something with one that should return nothing produces a number
that improves when either half gets worse.

E exists because four constants were fitted on two corpora that were both
Python and both written or chosen by one author. It is the third, in a language
the parser reaches through the line scanner rather than the AST, and the
defaults survived meeting it: both bars together still give the best silence
there (0.900, against 0.833 for concentration alone and 0.767 for coverage
alone). Forty questions resolves a change of several, not of one — quote it
with that in mind.

Every report prints `corpus  <n> units, fingerprint <hex>`. Quote it with any
figure taken from here. `--min-coverage` and `--min-concentration` vary one
gate at a time, which is how the ablation table in [ROADMAP](../docs/ROADMAP.md)
was produced — `--min-concentration 0` leaves the coverage bar alone in place.

`benchmarks/absent_queries.json` asserts that nothing in any of the three
repositories answers its questions, and `tests/test_absent_queries.py` enforces
that claim against all three indexes. It has fired seven times: twice on the
day the third corpus landed, which uses one guarded word in a completion
example and produces another by lower-casing a mixed-case identifier. Rewrite
the offending name — or, for a vendored corpus, the question. `CONTRIBUTING.md`
keeps the tally and the rules each firing added.

## The head-to-head against a Grep loop

```powershell
python -m benchmarks.grep_baseline
python -m benchmarks.grep_baseline --index benchmarks/corpus/flask --questions benchmarks/cold_queries.json --root benchmarks/corpus/flask
python -m benchmarks.grep_baseline --index benchmarks/corpus/cobra --questions benchmarks/cobra_queries.json --root benchmarks/corpus/cobra
```

Produces all three tables in README section 7. The baseline takes the query's words,
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
were quoted to. Run it on an **idle** machine: the same corpus at the same
commit measures about twice its idle median while a coverage run is in
progress, and nothing in the report can see the difference. Every published
latency figure therefore carries its range and its corpus fingerprint.

The figures the README used to carry came from a script that was never
committed, on a corpus that no longer exists. That is what this file is for.

## When a test takes rank 1

```powershell
python -m benchmarks.displacement
```

Grades all four positive rulers and separates two numbers that are not the
same number: how often a test is the top result, and how often it is the top
result *while an accepted answer sits at rank 2..k*. Only the second is a cost.

The definition of a test file lives in one place, `is_test`, and is
language-aware: `test/` `tests/` `testdata/` directories plus `test_*.py`,
`*_test.py` and `*_test.go`. It has to be. This figure was published for nine
releases with no command behind it, and the last re-derivation counted cobra's
324 test units by file name and then asked "reaches rank 1" of a directory
rule, which in a Go repository matches nothing.

Adding this script moved this repository's own two rulers by three units, which
is the hazard the stamps exist for: two of the five rulers read the live
working tree, so a benchmark that grades its own corpus changes it by landing.

## What the vectors cost

```powershell
python -m benchmarks.vector_share
```

Prints the share of each published index that is vector data, beside the
fingerprint of the corpus it was measured on — this repository and both
vendored corpora in one table.

The unit is bytes of the index as written. The measurement is a difference
rather than a pattern match: the payload is re-serialized with `write_index`'s
own `json.dump(..., ensure_ascii=False, indent=2)`, then again with every
`vector` field dropped, and the first of those is checked against the file on
disk before either is reported — so the table carries the on-disk cost rather
than an approximation of it.

Bytes and characters are different measurements here. This repository's own
index carries about 45,000 bytes of multi-byte UTF-8, which a character count
discards, putting its share about 0.6 points higher; the vendored corpora are
almost pure ASCII and agree to within 0.001 points on either basis, so they
cannot tell the two apart. That is why the basis is stated here rather than
inferred from them. Under `index.compact` the vectors are a float32 side file,
the share compares that file against the pair the index occupies, and the
report names the basis it used.

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

Seven queries over a five-file source-controlled fixture (nine units), comparing lexical
overlap against lexical plus cosine. It is a regression tripwire, not a ruler:
seven queries over nine units cannot distinguish a real improvement from
noise, which is why `repo_queries.py` exists. Keep the expected paths and names
stable, and record the embedding provider with any published result.
