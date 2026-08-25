# Changelog

Notable changes per release. Dates are the release date; measurements are from
the development machine (Windows 11, CPython 3.13) and are directional.

## 1.2.0 — 2026-08-25

Every release through 1.1.0 improved retrieval and none of them made it
**findable**. The plugin shipped one skill and nothing else, so every path into
it depended on that skill firing on its own — which `docs/ROADMAP.md` itself
lists as the one property no command in this repository can verify. A user who
installed it had no entry point they could discover, and the largest available
lever on retrieval quality, writing descriptions, was step 5 inside a page that
only loads once a model has already decided to search.

352 tests (from 346; **+6 added, 0 removed** by node-id set diff against v1.1.0).

### Added

- **Four commands**, the surface a user can actually find:

  | | |
  |---|---|
  | `/rag-your-code:index` | index, and report which rung this repository is on |
  | `/rag-your-code:search` | ask in plain language; cite `path:line`; act on a refusal correctly |
  | `/rag-your-code:describe` | the description loop, with the brief and the measured reason it matters |
  | `/rag-your-code:status` | stale? coverage? which embedder? what next? |

  Measured with `claude plugin details` on an installed copy: **~249 always-on
  tokens**, up from ~39 — the skill ~30, each command ~50–60 — and 590 to 2,400
  only when one fires. The increase is the honest price of being findable, and
  it is stated rather than buried. An MCP server was rejected for the same job:
  tool schemas are always-on whether or not anyone searches, and the JSON-lines
  `agent` protocol already serves the subprocess case.

- **The command line says when descriptions are the missing piece**, which
  costs nothing at all and reaches a person who knows about neither the skill
  nor the commands. When a search is **refused** and declarations are still
  undescribed, it says how many and names the next step.

  Tied to a refusal rather than to a weak-looking result, deliberately: "the
  results looked poor" would need a threshold on a score — the failure
  `confidence_threshold = 0.8` already demonstrated — while a refusal is a fact
  and is the moment somebody has actually lost something.

  It stays silent on `matched_terms_are_scattered`, because that reason means
  the words are here but never together, which is what a question about a
  subject the repository does not implement looks like; advising more
  descriptions there would be advice that cannot work. It stays silent once
  nothing is undescribed. **The JSON reply gains nothing** — an agent branches
  on `diagnosis` and does not need prose about a field it already has.

### Gates

Both new behaviours were verified **RED against a deliberately broken nudge**
before being trusted green, because a test that only passes on fixed content
cannot tell a working check from a deleted one.

Command files join the documented-surface checks **by discovery rather than by
name**, so a fifth command cannot become the one file nothing checks — which is
exactly how an install line naming a package index this project does not
publish to shipped twice. Every command must carry a loadable `description`,
and every `/rag-your-code:…` a document offers must exist, in both directions.

The protocol-action anti-vacuity guard moved from per-file to per-set: a command
file documents the command line and has no reason to mention the subprocess
protocol, and requiring one from every document would have made that check pass
only by forcing irrelevant JSON into user-facing pages.

## 1.1.0 — 2026-08-25

1.0.0 gave retrieval a way to say it has no answer, and left the open list
saying that six of fifteen English questions about absent subjects still got
answered because their words occur here in another sense. That diagnosis was
wrong. Inspected, the failures were not polysemy: four of one question's six
words occur in this repository, in **four different declarations that have
nothing to do with one another** or with the question. Coverage asks whether
each word occurs somewhere. Nothing asked whether they occur *together*.

346 tests (from 311; **+39 added, 4 removed**, each removal a rename of a test
whose contract changed).

### Added

- **`search.min_concentration`** (default `0.28`) — the share of a query's
  distinctive *rarity* that must occur inside a single declaration.
  Rarity-weighted rather than counted, because a unit holding two ordinary
  words is not better evidence than one holding the rare word the question is
  actually about. Set it to `0` for 1.0.0's behaviour.

  Measured on one corpus with the gate varied alone: the two rulers over
  undescribed code are **identical to three decimal places**, the warm ruler
  costs four questions of seventy, and unanswerable questions go from 0.700 to
  **0.967** silenced on this repository and 0.767 to **0.933** on the foreign
  one. English alone goes 0.53 → **0.93** and 0.53 → **0.87**.

- **A fourth diagnosis, `matched_terms_are_scattered`** — the words are here,
  never together, so the subject is probably not in this repository. Empty
  replies also carry `concentration`, `min_concentration`, and the bars
  *actually applied* after the small-index easing, which are not the settings
  on a repository below `COVERAGE_FULL_STRENGTH` units.

- **`embedding.provider = "sentence-transformers"`** — a trained model that
  runs on your machine, the only embedder that is both semantic and offline.
  `pip install "rag-your-code[sentence-transformers]"`. Optional by
  construction: `dependencies = []` still describes a default install, the
  import happens inside the constructor, and a test asserts the default
  provider imports none of it.

  **The first measurement of a real model in this project's history.** 0.8.0
  shipped the endpoint seam and said plainly that its benefit was unmeasured
  because there was no key. With `paraphrase-multilingual-MiniLM-L12-v2`:

  | ruler | signed hash | MiniLM |
  |---|---|---|
  | foreign, cold (35) | 0.229 / 0.400 / 0.300 | **0.286 / 0.457 / 0.357** |
  | own, cold (70) | 0.314 / 0.471 / 0.383 | **0.329 / 0.486 / 0.400** |
  | own, described (70) | 0.443 / 0.614 / 0.507 | 0.443 / **0.671 / 0.540** |
  | silence, own / foreign | 0.967 / 0.933 | 0.967 / 0.933 |

  `计算两个数的和` against `sum two numbers` scores **0.822** where the hash
  scores exactly 0.0000; `刷新索引` against `rebuild the index` **0.684**
  against 0.0000.

- **Qualified names in all fifteen languages.** `CodeUnit.qualified_name` was
  equal to `name` outside Python, so a method could not be told from a free
  function of the same name and `contains` edges had nothing to key on. Derived
  from the spans the closer already produced — a declaration nested inside
  another's span is nested in it, whatever the braces did on the way — so Ruby
  needs no separate treatment and there is no second mechanism to disagree with
  the first. Unit **ids** deliberately keep the bare name: re-keying them would
  orphan every description ever written against one.

- **The benchmark stamps the corpus it graded** — unit count and a fingerprint,
  in the report and in the JSON. Two runs of an unchanged `search.py` against
  the foreign repository returned 0.257 and 0.229 hit@1 because that repository
  had grown by ninety units in between. Both were right; comparing them was
  meaningless, and nothing in the output said so.

- **`--min-concentration`** on `benchmarks/repo_queries.py`, for the same
  reason `--min-coverage` exists: a knob this cannot vary can only be measured
  by editing the source between runs, which moves the corpus and the setting at
  once — and this repository's own source is one of the graded corpora.

### Fixed

- **A semantic embedder is no longer exempt from the evidence bars.** 1.0.0
  exempted one by the argument that a paraphrase sharing no word with its
  answer is exactly what a model is for. The argument is sound, the conclusion
  was wrong, and it was reasoned rather than measured because there was no
  model here to measure with. There is now: exempt and asked no other question,
  a trained model answered **all sixty** questions about subjects neither
  repository implements — the entire defect 1.0.0 existed to fix, back again
  through the one path that skipped the fix.

  Two vector-space replacements were measured and rejected before deleting the
  exemption. A floor on the similarity is a threshold on a score and the
  distributions overlap far too much to place one (median nearest-unit cosine
  0.469 answerable, 0.418 unanswerable). A scale-free version — how many
  standard deviations the nearest unit stands above the corpus's own mean —
  looked more promising and measured worse, taking a cold ruler from 0.329
  hit@1 to 0.186 for two thirds of the silence.

- **An imputed rarity that changed shape with corpus size.** A query word that
  is absent was charged what a word occurring in zero units would be worth,
  which is eighteen times a real term's weight across nine units and 1.2 times
  across five hundred. It is charged what the rarest *present* word is worth
  instead — the same degeneracy `COMMON_TERM_FLOOR` exists to stop, arrived at
  from a third direction, and caught by the small-index test.

### Measured and rejected

- **Stemming.** A light suffix stripper, stems added beside the exact token
  rather than replacing it. It improves both own-repository rulers (0.314 →
  0.343 and 0.443 → 0.529 hit@1) and costs the foreign ruler **3 of 35 hit@3**
  (0.400 → 0.314). The question 0.5.0 left open because an eight-question set
  could not resolve it is now closed, on 135 across four rulers. The first
  attempt also carried a
  doubled-consonant rule that split `classes` into `clas` while `class` kept
  its `s` — the exact opposite of what a stemmer is for.

- **Requiring the query's rarest word to be matched**, retested as a third
  condition on top of concentration rather than as a rule on its own. It halves
  the foreign ruler (0.229 → 0.114 hit@1) to buy the last three silences.

- **Callee-before-caller reranking**, to stop a test outranking the code it
  tests: it fires on **zero** questions across three rulers. And the premise is
  wrong — of eight such cases examined,
  seven are tests with no relationship at all to the code they displaced.

- **Lowering the `name` field weight, and normalising it harder.** No effect at
  any setting, because `tokenize` keeps a fifty-character underscored test name
  as a *single token*. The name field never carried a test's English words; its
  prose docstring does.

- **Removing the stored vectors**, which are **65.3%** of an index and move the
  three positive rulers by ±1 question under the default embedder. Kept,
  because the same storage is what makes the optional model work and the schema
  stays one shape.

### Why the vector earns nothing, finally diagnosed

Left unexplained since 0.6.0. Measured here, first-party:

- **Not saturation.** Median 56 distinct tokens per unit into 384 buckets, 13.6%
  expected occupancy, 0.4% of units wider than the vector. Widening to 16,384
  raises fidelity to true overlap from r=0.40 to r=0.56 and buys no ranking.
- **Not redundancy with BM25F.** Its cosine correlates only **+0.45** with the
  lexical score over 26,490 scored candidates, so it does carry independent
  variance.
- **The variance is the wrong variance.** A signed hash counts every token
  equally, so the part of it independent of BM25F is precisely the contribution
  of words that are everywhere — what rarity weighting exists to discard.
  Independent noise, not independent signal.

A vector computed from the same words cannot know anything the words do not
already say. That is why the answer is a model rather than a better hash, and
why eight dependency-free replacement schemes all failed.

## 1.0.0 — 2026-08-25

Eight releases measured how well retrieval finds an answer. None could measure
what it does when there is no answer, because every ruler graded questions that
had one. The fourth ruler settled it in a single run: **thirty questions about
subjects neither graded repository implements, and all thirty were answered.**

`where are CUDA kernels dispatched to the device` came back with a test about
word counting, on the evidence of `are`, `the`, `to` and `where`.

### Added

- **Retrieval can say it has no answer.** `search` returns nothing when too
  little of a question occurs in the index, rather than the unit that ranked
  least badly. A ranking always has a winner and returns it with a score and a
  rank that read exactly like an answer; asking *is any of this evidence* is a
  separate question, and until now nothing asked it.

- **`search.min_coverage`** (default `0.40`) — the share of a question's
  discriminating words that must occur in the index. Set it to `0` to restore
  the previous behaviour exactly.

  Words the repository uses everywhere are dropped from both sides of that
  fraction, which is the part that does the work: half of `where are CUDA
  kernels dispatched to the device` matches, and it looks like evidence until
  you notice which half. Counting only words that distinguish silenced 18 of 30
  unanswerable English questions that no plain coverage threshold reached at
  all, at identical cost in real answers — 97 of 98 either way.

- **A `diagnosis` field on every empty reply**, in the command line and the
  agent protocol: `no_query_term_in_index`, `only_ubiquitous_terms_matched` or
  `too_little_of_the_query_matched`, each with the matched words and a hint.
  Three ways to fail, recovered by three different moves. `stop_reason` keeps
  its published values — widening an enumeration callers branch on is a
  breaking change wearing the clothes of an improvement.

- **`benchmarks/absent_queries.json`**, the fourth ruler, and
  `--min-coverage` on the benchmark runner. `--index` now accepts a repository
  instead of answering with a `PermissionError` traceback.

### Fixed

- **A description removed from the store went on being served.** Reuse copies a
  unit out of the previous index with the text applied when it was written, and
  the apply step only ever *set* text, so adding took effect, changing took
  effect, and deleting did nothing at all. Found by a number that refused to
  move: removing 227 descriptions changed no score. Recovery re-parses, and
  carries vectors across by identity on the text they were computed from, so a
  provider is not billed for a full re-embedding.

- **The README's settings table had been nine settings behind since 0.8.0**,
  listing twelve of twenty-one and omitting every provider setting that release
  existed to add. Now asserted against `config.py` in both directions.

### Measured

| | before | now |
|---|---|---|
| unanswerable questions met with silence, this repository | 0.000 | **0.733** |
| the same, on the foreign repository | 0.000 | **0.800** |
| results resting on no lexical evidence, all three rulers | 0.029 – 0.129 | **0.000** |
| hit@1 / hit@3 / MRR, foreign repository (35) | 0.257 / 0.400 / 0.314 | **unchanged** |
| hit@1 / hit@3 / MRR, this repository (70) | 0.486 / 0.729 / 0.579 | **0.500 / 0.729 / 0.583** |

Cost: one question of the 158 measured. `控制台编码不是 UTF-8 会怎么样` was
reaching `_use_utf8_streams`, and the only words in it this repository contains
are `utf` and `8`, both used everywhere. It was right by coincidence.

Not fixed: an English question whose words occur here in another sense. `how is
the OAuth refresh token rotated` matches `refresh` because this project
refreshes indexes. Six of fifteen English absent questions survive for that
reason, and no lexical threshold separates them.

### Descriptions

Coverage is 297 of 524 units — `src/`, the benchmark tooling and the parser
fixtures. All 227 test-function descriptions were written and are not shipped:
measured on a fixed corpus they cost hit@1 0.500 → 0.414 and silence 0.800 →
0.600, because a test description restates what the source does in the source's
own vocabulary and then competes with it. Fixture descriptions cost nothing,
because they are about grammar and no question here is asked in those words.

311 tests.

## 0.8.0 — 2026-08-25

0.7.0 measured eight ways to give the vector half real semantics without a
model and adopted none of them, then named what was left: a real model as
something a user opts into, or accepting that retrieval reaches only what
somebody wrote down. This is the first, and it is off unless you turn it on.

### Added

- **`embedding.provider`.** Set it to `openai-compatible` and vectors come
  from any endpoint speaking that shape — a hosted service, or `ollama`,
  LM Studio, vLLM or llama.cpp on your own machine. One request shape covers
  both, and the local one keeps the property this project was built on: the
  source never leaves the machine.

  ```toml
  [embedding]
  provider   = "openai-compatible"
  endpoint   = "http://localhost:11434/v1/embeddings"
  model      = "nomic-embed-text"
  dimensions = 768
  api_key_env = "OPENAI_API_KEY"   # the NAME of the variable, never the key
  ```

- **`search.vector_recall`.** Similarity may now *add* candidates rather than
  only reorder them — the architectural constraint 0.7.0 identified as the
  reason no embedding change could help. It is gated on the embedder rather
  than on a preference: under the feature hash the same widening measured
  worse, while six of thirty-five foreign-ruler questions have no acceptable
  answer sharing a single token with the query. Lexical evidence still
  dominates; a unit found by similarity alone scores at most
  `search.vector_weight`.
- **`embedding.batch`, `timeout`, `retries`**, and a `str` kind in the
  settings table.

### Changed

- Embedding is one batched pass over the units that need vectors, not a call
  inside the parse loop. Eleven hundred units one round trip at a time is not
  a slower version of the same thing. An incremental run over unchanged files
  makes no request at all.
- `SearchIndex` carries the embedder. A query vector and a unit vector have to
  come from the same scheme to be comparable, and this project already
  produced one wrong conclusion from exactly that mismatch.
- An index records the provider and the model as well as the width, so
  switching any of them discards the stored vectors instead of mixing two
  spaces.

### Safety properties, each asserted

- **The default opens no socket.** The test makes the transport raise, then
  runs a full index and search. Everything else here is only worth having
  while that passes.
- **The credential is never a setting.** `rag-your-code.toml` is meant to be
  committed; the file names an environment variable and the variable holds the
  key. That is not the environment layer `config.py` deliberately does not
  have — it is one secret kept out of a shared file.
- **A key is never sent in cleartext to anything but loopback**, and never
  appears in an error message.
- **A rejected key or unknown model is not retried**; a rate limit or a
  transport failure is, with growing backoff, and then the build stops rather
  than falling back to the hash. A mixed index would rank confidently on a
  cosine that means nothing.
- **Rows are ordered by the index they report**, because the response schema
  promises an index and not a sequence.

### Not measured

Whether this helps a real repository, and by how much. There is no key here,
and a number produced by a stub would be fiction. The instrument ships
instead: `benchmarks/repo_queries.py --index` grades any index. The 0.15
default for `search.vector_weight` was tuned against a hash that carries no
meaning and is very likely wrong for a model.

## Earlier releases

0.7.0 and everything before it are in
[docs/CHANGELOG-0.x.md](docs/CHANGELOG-0.x.md), moved there unedited when this
file reached its size budget. They are worth reading for the four rulers'
origins and for the twelve changes measured and rejected along the way.
