# Roadmap

What shipped, what was decided against, and what is deliberately not here. The
v0.2.0 audit, the eight phases that closed it, and releases 0.4.0 through 0.7.0
are in [ROADMAP-history.md](ROADMAP-history.md).

## Design principles

1. **One root cause, one change.** Seven symptoms collapse into five edits, not
   seven patches.
2. **Make the error structurally impossible**, do not add a check for it. A line
   number that *is* the loop index cannot drift; no assertion required.
3. **Data over code.** Adding a language is a table row, not a regex edit.
4. **Build the ruler before reshaping the thing measured.** The multi-language
   golden set landed *before* the parser rewrite; the absent ruler landed
   *before* the evidence bars.
5. **The contract does not move.** `CodeUnit`, index schema 2 and the JSON-lines
   protocol are unchanged throughout; every fix sits beneath them, and new
   information arrives in new fields rather than by widening an enumeration.
6. **A dependency is a user's choice, never a default.** Anything needing one
   follows the embedding provider's pattern: an optional extra, selected by a
   setting, absent from `dependencies = []`.

## Open list, closed

Everything the 1.0.0 roadmap listed as still open, and what happened to it.

| item | outcome |
|---|---|
| Qualified names outside Python | **Fixed** in 1.1.0, all 15 languages, from the spans the closer already produced. |
| Descriptions cover 297 of 524 units | **Decided.** Test-function descriptions cost five real answers and six false silences; the table is under 1.0.0 in [ROADMAP-history.md](ROADMAP-history.md). Now 303 of 557. |
| No stemming | **Measured and rejected.** Helps both own-repository rulers, costs the foreign one 3 of 35 hit@3. |
| A test declaration outranks the code it tests | **Misdiagnosed, and corrected.** See below. |
| English questions answered from words used here in another sense | **Fixed** by the concentration bar, 0.53 → 0.93 English silence. One residual, below. |
| Whether the skill fires unprompted in a fresh session | **Still not verifiable from a command.** See below. |
| Vectors are 55% of an index and earn nothing | **Diagnosed** (1.1.0) and **kept**: 65.4%, ±1 question, and the same storage is what makes the optional model work. |
| Tree-sitter parsing | **Decided against as a default**, and the policy for it settled. See non-goals. |
| SQLite / ANN storage layer | Same. |

### The test-ranking item was misdiagnosed

"A test declaration often outranks the code it tests" had been on the list
since 0.6.0. Three measurements retired it:

- Across three rulers, **10 of 175** questions have a test at rank 1 with an
  accepted answer sitting at rank 2–3. That is the real cost, and it is smaller
  than the raw count of tests-at-rank-1 suggested, because sometimes the test
  is a legitimate answer.
- Inspected case by case, **seven of the eight examined** are tests with *no relationship*
  to the code they displaced — `test_readme_badge_match` displacing an i18n
  checker, `test_the_default_provider_opens_no_socket` displacing a path
  guard. So no mechanism keyed on "the code it tests" can address it.
- A callee-before-caller rerank, which is what such a mechanism would look
  like, fires on **zero** questions.
- Lowering the `name` field weight from 8 to 4, and raising its length
  normalisation to b=1.0, changes **nothing at any setting** — because
  `tokenize` keeps an underscored test name as a single token. The name field
  never carried the test's English words.

What is left is generic: test bodies are prose-heavy, and prose-heavy units
win prose queries. That is ranking noise, not the stated defect.

### The residual on the absent ruler

One English question of fifteen, on both repositories: `how is a hostname
resolved when the nameserver times out` finds `hostname`, `resolved` and
`times` genuinely co-occurring in one unrelated declaration. That is a real
vocabulary collision, and no lexical rule separates it from a real answer
without costing more than it saves — three further rules were measured and
each cost more. Chinese sits at 1.000 silence on both repositories.

### The one thing a command cannot check

Whether the bundled skill fires on its own in a fresh session. Everything
adjacent is checked — the manifest, the marketplace entry, the install line run
verbatim by CI, the token cost from `claude plugin details` — but the trigger
itself needs an interactive session with a model deciding, which no test in
this repository can stand in for. It is listed here rather than quietly
dropped.

## 1.1.0 — words that are here, but never together

1.0.0 stopped retrieval answering questions whose words are absent. It left six
of fifteen English questions about absent subjects still answered, and blamed
polysemy — words occurring here in another sense. **That diagnosis was wrong.**

Inspected, the surviving failures share one shape: several of the query's rare
words really are in the repository, in *different declarations that have
nothing to do with one another*. Two thirds coverage, and no two of those words
ever appear together. Coverage asks whether each word occurs somewhere; nothing
asked whether they occur in one place.

`search.min_concentration` asks that: what share of a query's distinctive
rarity lands inside a single unit. Rarity-weighted rather than counted, because
a unit holding two ordinary words is not better evidence than one holding the
rare word the question is about.

| gate, varied alone on one corpus | A hit@1/3/MRR | B hit@1/3/MRR | C hit@1/3/MRR | silence own / foreign |
|---|---|---|---|---|
| neither bar | 0.229/0.400/0.300 | 0.314/0.486/0.391 | 0.471/0.686/0.552 | 0.000 / 0.000 |
| coverage 0.40 only | 0.229/0.400/0.300 | 0.314/0.471/0.383 | 0.471/0.671/0.548 | 0.700 / 0.767 |
| concentration 0.28 only | 0.229/0.400/0.300 | 0.314/0.471/0.383 | 0.443/0.614/0.507 | 0.967 / 0.933 |
| **both, shipped** | 0.229/0.400/0.300 | 0.314/0.471/0.383 | 0.443/0.614/0.507 | **0.967 / 0.933** |

On these four rulers concentration subsumes coverage. Both ship anyway: they
answer different questions, they produce different diagnoses, and
`search.min_coverage` is a published setting whose removal would be a breaking
change for no gain.

### What a real model does, measured at last

0.8.0 shipped the endpoint seam and stated plainly that its benefit was
unmeasured, because there was no key here and a number from a stub would be
fiction. A model that runs locally needs no key.

| ruler | signed hash | MiniLM, local |
|---|---|---|
| A foreign, cold (35) | 0.229 / 0.400 / 0.300 | **0.286 / 0.457 / 0.357** |
| B own, cold (70) | 0.314 / 0.471 / 0.383 | **0.329 / 0.486 / 0.400** |
| C own, described (70) | 0.443 / 0.614 / 0.507 | 0.443 / **0.671 / 0.540** |
| D silence, own / foreign | 0.967 / 0.933 | 0.967 / 0.933 |

Better on every positive ruler, refusal unchanged — but only after deleting a
special case 1.0.0 had introduced.

### The exemption that reintroduced the defect

1.0.0 exempted a semantic embedder from the coverage bar, reasoning that a
paraphrase sharing no word with its answer is exactly the case a model exists
for. The reasoning is sound. The conclusion was wrong, and it was reasoned
rather than measured because there was no model here to measure with: exempt
and asked no other question, the model answered **all sixty** unanswerable
questions. The whole defect 1.0.0 existed to fix, restored by the one path that
skipped the fix.

Two vector-space replacements were measured before the exemption was deleted:

- **A similarity floor** is a threshold on a score — the failure this project
  has already had once — and the distributions overlap far too much to place
  one: median nearest-unit cosine 0.469 for answerable questions against 0.418
  for unanswerable.
- **A scale-free standout** — how many standard deviations the nearest unit
  stands above the corpus's own mean for that query — is the right *shape* of
  idea and measured worse, taking ruler B from 0.329 hit@1 to 0.186 in exchange
  for two thirds of the silence.

Applying the existing lexical bars costs ruler A nothing measurable.

### Why the vector earns nothing, diagnosed

Open since 0.6.0, where it was observed and left unexplained. Measured
first-party:

- **Not saturation.** Median 56 distinct tokens per unit into 384 buckets;
  13.6% expected occupancy; 0.4% of units exceed the width. Widening to 16,384
  raises fidelity to true token overlap from r=0.40 to r=0.56 and buys no
  ranking at all.
- **Not redundancy.** The hashed cosine correlates only **+0.45** with the
  BM25F score over 26,490 scored candidates, so it does carry variance of its
  own.
- **The variance is the wrong variance.** A signed hash counts every token
  equally, so the part independent of BM25F is exactly the contribution of
  words that are everywhere — precisely what rarity weighting exists to
  discard. Independent noise, not independent signal.
- **And it can only reorder.** Candidates come from the lexical half; six of
  thirty-five foreign questions have an accepted answer sharing no token at all
  with the query.

A vector computed from the same words cannot know anything those words do not
already say. That is the reason eight dependency-free replacement schemes all
failed, and the reason the answer is a model rather than a better hash.

### Also in 1.1.0

Qualified names in all fifteen languages, from the spans the closer already
produced rather than a second brace-depth mechanism that could disagree with
the first. Unit ids deliberately keep the bare name, because re-keying them
would orphan every description ever written against one.

The benchmark stamps the corpus it graded. Two runs of an unchanged `search.py`
returned 0.257 and 0.229 hit@1 on the foreign ruler because that repository had
grown by ninety units between them; both numbers were right, comparing them was
meaningless, and nothing said so.

An imputed rarity that changed shape with corpus size: an absent query word was
charged what a word in zero units would be worth — eighteen times a real term
across nine units, 1.2 times across five hundred. It is charged what the rarest
*present* word is worth instead. Same degeneracy as `COMMON_TERM_FLOOR`,
arrived at from a third direction, caught by the small-index test.

## 1.0.0 — the question a ranking cannot answer

Eight releases measured how well retrieval finds the answer. None of them
could measure what it does when there is no answer, because all three rulers
graded questions that had one. Adding the ruler that could took one run to
settle it: **thirty questions about subjects neither graded repository
implements, and all thirty were answered.** Both languages, both repositories,
scored 0.000 silence.

The evidence was in the reply the whole time. `where are CUDA kernels
dispatched to the device` came back with a test about word counting, matched
on `are`, `the`, `to`, `where`. `准入控制为什么会拒绝没有资源限额的容器组`
came back with the UTF-8 console setup, matched on `拒绝`, `控制`, `没有`.

### It was never a Chinese problem

The session opened by measuring Chinese cold-start at hit@1 0.000 and calling
that the gap. That framing was wrong, and the absent ruler is what showed it:
English fails identically and less visibly. Nothing in the pipeline asked
whether a result was evidence; it only asked which one ranked highest, and a
ranking always has a winner.

### What was measured before choosing

Measured on the four rulers as they ship — 98 answerable questions that are
findable at all, and 60 unanswerable ones, half of each in English:

| rule | real answers kept | unanswerable silenced | English |
|---|---|---|---|
| plain coverage ≥ 0.15 | 98/98 | 16/60 | 0/30 |
| plain coverage ≥ 0.40 | 97/98 | 27/60 | 0/30 |
| **coverage ≥ 0.40 over discriminating words only** | **97/98** | **46/60** | **18/30** |

Two further rules were measured against the draft ruler and rejected there: an
escape hatch admitting any query with one rare matched term recovered no lost
answer and cost a third of the silence, and *requiring* a rare matched term
bought nine English silences for five real answers — the wrong direction.

Plain coverage protects Chinese and does nothing whatever for English, because
`where`/`are`/`to`/`the` are half of that query. Requiring a rare matched term
costs five real answers to suppress nine fake ones — the wrong direction, and
rejected. Dropping corpus-ubiquitous words from *both* sides of the fraction
costs exactly what plain coverage costs and silences twenty more.

### Three defects found while building it

**A ratio is degenerate at small N.** `COMMON_TERM = 0.05` marked a word in
one unit of ten as ubiquitous, since 0.1 > 0.05 — so every term in a small
index was "everywhere" and every query refused. 29 tests failed at once and
named it. The same defect as a constant tied to a scale, arrived at from the
other side; `COMMON_TERM_FLOOR` fixes it.

**A default argument is bound at definition.** The first threshold sweep set
`search.DEFAULT_MIN_COVERAGE` on the module between runs and every threshold
scored identically — indistinguishable from a setting that does not matter.
`evaluate()` now passes overrides to `search`, and `--min-coverage` exists for
the same reason `--vector-weight` does. The second confounded measurement in
two releases; CONTRIBUTING carries the rule.

**Writing the documentation made the subjects present.** The absence check
fired on `cuda` and `kernels` the first time it ran, because the source
explains the coverage bar using exactly that example. It also fired on
`webhook` and `hostname`, which this repository has always had and which were
written into the ruler by eye rather than run through the check. Every subject
was re-derived mechanically; the GPU questions were retired.

### What it costs, and what it does not fix

One question of 158. `控制台编码不是 UTF-8 会怎么样` was reaching
`_use_utf8_streams`, and the only words in it this repository contains are
`utf` and `8`, both used everywhere. It was right by coincidence.

An English question whose words occur here in another sense is untouched:
`how is the OAuth refresh token rotated` matches `refresh` because this
project refreshes indexes. Six of fifteen English absent questions survive for
that reason, and no lexical threshold separates them. That is the case a real
embedding model exists for — and for the first time there is an instrument
that would show it.

### Descriptions: written for every unit, kept for 57% of them

The plan was full coverage. All 361 remaining units were described, and the
measurement that followed was decisive enough to undo most of it. On one fixed
corpus, varying nothing but the description store:

| descriptions | n | hit@1 | hit@3 | MRR | silence |
|---|---|---|---|---|---|
| none | 0 | 0.329 | 0.457 | 0.386 | 0.800 |
| src only | 163 | 0.486 | 0.729 | 0.579 | 0.800 |
| src + benchmark tooling | 184 | 0.500 | 0.729 | 0.583 | 0.733 |
| src + parser fixtures | 276 | 0.500 | 0.714 | 0.581 | 0.800 |
| **src + tooling + fixtures** | **297** | **0.500** | **0.729** | **0.583** | 0.733 |
| src + test functions | 411 | 0.414 | 0.729 | 0.552 | 0.633 |
| everything | 524 | 0.414 | 0.714 | 0.545 | 0.600 |

Describing the *test functions* costs five real answers and six false
silences, and lifts test units from 9 of 67 top-1 results to 15. Describing the
*parser fixtures* costs nothing. The line is not tests versus source: it is
what the description says. A fixture description is about grammar — `suspend
function`, `destructor`, `unit struct` — and no question about this project is
asked in those words. A test description restates what the source does, in the
source's own vocabulary, and then competes with it.

A probe of eighteen test descriptions had moved hit@1 by one question in one
direction and hit@3 by two in the other, which is this instrument's noise. The
effect only became visible at scale, which is an argument for finishing a
measurement rather than sampling one.

The 227 test-function descriptions were written and are not shipped. What they
bought is the row that rules them out.

### The edit to the store that did nothing

Removing those 227 changed no score at all, which was the wrong kind of
surprise. Reuse copies a unit out of the previous index carrying the text
applied when that index was written, and the apply step only ever *sets* text:

```python
text = authored.get(unit.id)
if text and unit.description != text:   # a deletion is `None`, so nothing happens
```

Adding a description took effect. Changing one took effect. Deleting one did
nothing, indefinitely — the removed sentence went on being served out of every
reused unit, and the ruler went on reporting the score it produced. It was
found by a number that refused to move, not by a report, and it had been there
since descriptions existed.

The generated sentence a description replaces is a function of the syntax tree,
so only re-parsing recovers it. Re-parsing every file on any description edit
would be free locally and expensive against a provider, where each vector is a
billed round trip — so vectors are carried across by identity on the text they
were computed from, and a unit whose own text did not move costs no request.
The first version of that carry-over compared descriptions instead, which
handed a unit edited from `return 1` to `return 2` its old vector; the existing
incremental test caught it.

### Also in 1.0.0

Descriptions cover every unit rather than `src/` alone. The README's settings
table had been nine settings behind since 0.8.0 and is now asserted against
`config.py` in both directions. `--index` on the benchmark accepts a
repository instead of answering with a `PermissionError` traceback, which
mattered because that is the one command the docs hand to a stranger.

## 0.8.0 — the trade, made the only way it could be

0.7.0 closed the question of whether a dependency-free scheme could give the
vector half real semantics: eight approaches, none adopted, and the reason was
architectural rather than representational. What remained was named there as
two options — a real model as an optional dependency, or accepting that
retrieval reaches only what somebody wrote down.

This is the first, built as something a user turns on. `embedding.provider`
switches between the local hash and any OpenAI-compatible embeddings endpoint,
which covers hosted services and a model server on localhost with one request
shape. The local case is documented first because it is the one that keeps the
original promise: the source never leaves the machine.

The default is unchanged and stays unchanged by construction. It adds no
dependency, opens no socket, and a test asserts the second of those by making
the transport raise before running a full index and search. Everything else in
`tests/test_providers.py` is only worth having while that one passes.

### What the settings had to get right

| decision | why it went this way |
|---|---|
| the key is an environment variable, the file names it | every other setting is meant to be committed so everyone who clones sees what shaped the index; a credential is the one value with the opposite requirement |
| cleartext HTTP to a non-loopback host with a key is refused | a warning about a leak that has already happened is not a safeguard |
| provider, model and width are recorded in the index | two models behind one endpoint are two vector spaces; a cosine across them is meaningless and ranking would act on it anyway |
| a failure ends the build | falling back would leave a mixed index, and the confident wrong answer is the one thing this index is built not to give |
| embedding is one batched pass | eleven hundred units one round trip at a time is not a slower version of the same thing |

### The candidate set opens, but only for real semantics

`search.vector_recall` lets similarity *add* candidates rather than only
reorder them — the constraint 0.7.0 identified as the reason no embedding
change could help. It is gated on the embedder, not on a preference: under the
feature hash the same widening measured worse, and six of thirty-five foreign
ruler questions have no acceptable answer sharing a single token with the
query, which is exactly what only a real model can reach.

Verified against a stub whose vectors carry meaning by hand: with recall off
the semantically-near unit is not a candidate at all; with it on the unit
appears, found by similarity alone, ranked below the lexical hit.

### What is not measured

Whether any of this helps a real repository, and by how much. There is no key
here, and a number produced by a stub would be fiction. The instrument ships
instead: `benchmarks/repo_queries.py --index` grades any index, so the
question is answerable by whoever has the key. The 0.15 default for
`search.vector_weight` was tuned against a hash carrying no meaning and is
very likely wrong for a model.

## Non-goals

**Tree-sitter parsing** and a **SQLite/ANN storage layer** are not here, and
the policy that governs them is now settled rather than pending: anything
requiring a dependency follows `embedding.provider` — an optional extra,
selected by a setting, never in a default install.

Neither has been built, and the reasons are specific rather than general.

- Tree-sitter's headline benefit for this project was qualified names outside
  Python, and 1.1.0 supplies those from spans the parser already computes. What
  would remain is better recall on constructs the rule table misses, and the
  language fixtures currently report 91/91 on found declarations, line numbers
  and signatures — so the measured headroom is zero and there would be no way
  to tell an improvement from a regression.
- An ANN index replaces the full vector scan in `search.vector_recall`, which
  runs only under a semantic embedder. That path is affordable at the measured
  envelope (10,000 units, 3.90 ms mean query), so the work would be justified
  by a repository size nobody has brought yet.

The default stays what it is: `dependencies = []`, no socket, no key, and
output a human can read and correct rather than opaque floats.
