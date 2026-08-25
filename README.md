# RAG Your Code

[![PyPI](https://img.shields.io/badge/PyPI-rag--your--code-blue)](https://pypi.org/project/rag-your-code/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10--3.13-blue)](pyproject.toml)

**A local code-retrieval index for coding agents.** Ask a question in plain
language; get back the declarations that answer it — each with its file, its
exact line range, the words it matched on, and its source.

Zero runtime dependencies. No network calls. No model required. It runs over a
private repository on a machine with the network switched off, and produces an
index a human can read.

It is the **R** in RAG. There is no generation here — your agent is the G.

```bash
pip install rag-your-code
rag-your-code bootstrap .
rag-your-code search "where does it decide whether to answer at all" --json
```

---

## 1 · The problem

An agent looking for something in an unfamiliar codebase has two bad options.

**Grep** is fast and exact, and it only finds the string you already guessed.
Ask "where does it decide whether to answer at all" and there is no string to
grep for. **Reading whole files** is thorough and blows the context budget:
five files of a real repository is tens of thousands of tokens, most of them
irrelevant.

Retrieval sits in between — and brings a third problem that the first two do
not have. Grep can tell you it found nothing. **A ranking cannot.** It always
produces a least-bad candidate and returns it with a score and a rank that read
exactly like an answer, whether or not the repository contains anything
relevant. That is the failure this project spent its last two releases on.

## 2 · What it does

| | |
|---|---|
| **Index** | Every function, method and class in 15 languages becomes one `CodeUnit`: id, signature, exact line range, source, calls, imports, description. |
| **Retrieve** | BM25F over five weighted fields, blended with vector similarity. Results carry the terms they matched on. |
| **Refuse** | Two evidence tests decide whether *any* result is an answer. When neither is met, retrieval returns nothing plus a machine-readable diagnosis. |
| **Expand** | Optional bounded walk over `calls` / `imports` / `contains`, every hop carrying its edge path as evidence. |
| **Describe** | Your agent writes the vocabulary the source never contained, stored in a committed sidecar or promoted into the code as a reviewable diff. |
| **Serve** | A CLI, and a JSON-lines protocol for a long-lived agent subprocess. |

**Scope.** Retrieval over source declarations. Not a code-understanding model,
not a generation step, not an IDE index. Questions are answered in the
vocabulary somebody wrote down — in the code, in its documentation, or in a
description an agent added.

## 3 · What is actually hard here

Three things, and all three are measured rather than argued.

### 3.1 · Ranking cannot say "no answer"

Eight releases measured how well retrieval *finds* the answer. None could
measure what it does when there is no answer, because every question graded had
one. A fourth ruler — thirty questions about subjects neither graded repository
implements — settled it in a single run: **all thirty answered**, in both
languages, on both repositories.

| asked of a repository containing no such code | answered with | on the evidence of |
|---|---|---|
| `where are CUDA kernels dispatched to the device` | a test about word counting | `are` `the` `to` `where` |
| `准入控制为什么会拒绝没有资源限额的容器组` | the UTF-8 console setup | `拒绝` `控制` `没有` |
| `how is the OAuth refresh token rotated` | a description-store method | `before` `is` `refresh` `the` |

Not a Chinese problem and not a ranking problem — a **missing question**.
Nothing in the pipeline ever asked *is any of this evidence*.

Retrieval now asks two questions that ranking cannot:

**Coverage** — what share of the query's *discriminating* words occur in the
index at all. Words the repository uses everywhere are dropped from both sides
of the fraction, and that is the part that does the work: half of `where are
CUDA kernels dispatched to the device` matches, and it looks like evidence
until you notice which half.

**Concentration** — what share of the query's *rarity* lands inside a single
declaration. Coverage alone asks whether each word occurs somewhere, which a
question about a subject nothing here implements can satisfy entirely out of
unrelated units: four of six words found in four different declarations, none
of which has anything to do with the question or with one another. Rarity-
weighted rather than counted, because a unit holding two ordinary words is not
better evidence than one holding the rare word the question is about.

Both are **ratios inside the query**, never thresholds on a score. A score
threshold is tied to whatever scale the ranking currently produces, and this
project has already had one silently stop existing the moment BM25F changed
the scale.

### 3.2 · The vector was carrying nothing, and here is why

The default embedder is a signed feature hash. Ablating it entirely moves the
three positive rulers by **±1 question in either direction** while the vectors
occupy **65.4%** of the index. That was known since 0.6.0 and left unexplained.
The explanation, measured here:

- **Not saturation.** Median 56 distinct tokens per unit into 384 buckets;
  13.6% expected occupancy; 0.4% of units exceed the width. Widening to 16,384
  raises fidelity to true overlap from r=0.40 to r=0.56 and buys no ranking.
- **Not redundancy.** Its cosine correlates only **+0.45** with the BM25F score
  over 26,490 scored candidates, so it does carry variance of its own.
- **The variance is the wrong variance.** A signed hash counts every token
  equally. The independent part of what it measures is therefore precisely the
  contribution of words that are everywhere — the part rarity weighting exists
  to discard. Independent *noise*, not independent signal.
- **And it can only reorder.** Candidates come from the lexical half, so a
  vector cannot make anything retrievable. Six of thirty-five foreign-ruler
  questions have an accepted answer sharing **no token at all** with the query.

Eight replacement schemes were implemented and measured across releases —
character n-grams, random indexing, truncated SVD, posting-list signatures, a
rarity-weighted hash, call-graph diffusion, postings expansion, authored-fields-
only. None beat using no vector. The conclusion is not that the hash needs
tuning; it is that **a vector computed from the same words cannot know anything
the words do not already say.** Making it useful requires a model — which is
now an installable option, and measured below.

### 3.3 · Retrieval reaches only what somebody wrote down

`retry_charge` tokenizes to one opaque term, not to *retry* and *charge*.
Splitting identifiers was implemented and measured with query and stored
vectors rebuilt together: equal or worse on every ruler, because the pieces are
`get`, `find`, `check`, `test`, which rarity weighting immediately discounts.

So the vocabulary ladder is the answer, cheapest rung first:

| source | who wrote it | lives in | survives a refactor | cost |
|---|---|---|---|---|
| identifier, signature, body | author | the code | by construction | free |
| docstring / doc comment, 15 languages | author | the code | by construction | free |
| promoted description | agent | the code | by construction | one review |
| agent description | agent | a sidecar | needs machinery | tokens |

## 4 · How it works

```
your repository
  → walk source files            configurable ignores, suffixes, size cap
  → parse declarations           Python via its own AST; 14 languages via a
                                 3-layer line scanner + per-language rule table
  → one CodeUnit each            id, qualified name, signature, exact span,
                                 source, calls, imports, serial, description
  → embed                        signed hash (default) · local model · endpoint
  → inverted index               BM25F over name/signature/description/
                                 relations/body, IDF derived from your corpus
  → assess                       coverage + concentration → answer, or refuse
  → rank                         lexical + weighted cosine
  → optional graph expansion     calls / imports / contains, evidence per hop
  → results, or JSON-lines to an agent subprocess
```

**Parsing.** Python uses the standard-library syntax tree, so nesting,
qualified names, call lists and spans are exact. Every other language goes
through three separated layers: a scanner reading one line at a time, a rule
table per language, and a span closer following brace depth, Ruby's `end`, or
the next declaration. Because a pattern never sees a second line, a reported
line number **is** the scanner's loop index and cannot drift, and no
declaration can swallow the ones after it. A 441-byte JavaScript file that once
took 12.6 s to parse now takes 0.36 ms.

Qualified names come from the spans the closer already produced — a declaration
nested inside another's span is nested in it, whatever the braces did on the
way. One mechanism, so there is no second one to disagree with the first.

**Ranking.** BM25F with per-field length normalisation. Normalising per field
is the part that matters: measured against one length for the whole unit, a
body repeating a word forty times still beat the declaration actually named
after it, because a long body's advantage in raw count almost exactly cancelled
its penalty for being long.

| field | weight | why |
|---|---|---|
| `name` | 8 | what the author called the thing |
| `signature` | 4 | what it takes and returns |
| `description` | 3 | what somebody said it does |
| `relations` | 2 | what it calls and imports |
| `body` | 1 | a mention |

**Rarity comes from your corpus, not a stopword list.** `the` and `calls` earn
their low weight the same way a Chinese bigram does — by being everywhere — so
it works in a language nobody anticipated and no list has to be maintained.

**Safety.** A repository being scanned is untrusted input, including any
`.rag-your-code/index.json` it ships. Nothing read out of an index may name a
path to act on: superseded vector sidecars are enumerated from the naming
scheme the writer itself uses. A crafted index used to make the documented
`index` command delete an arbitrary in-tree file and report success.

## 5 · Before and after

A question with no lexical shortcut, asked of this repository:

```console
$ rag-your-code search "where does it decide whether to answer at all" --limit 1
[src/ragyourcode/search.py:116:Evidence] score=0.449
This class evidence. and calls dataclass. ... Documented intent: Whether a query
reached this index at all, kept apart from how its results rank. ...
```

The same question through Grep is not askable — there is no string to search
for. The nearest guess, `grep -rn "decide"`, returns matches scattered across
the repository that a reader must then triage by hand.

Now the case that motivated 1.0.0 and 1.1.0 — a question this repository has no
answer to at all:

```console
$ rag-your-code search "why does the print spooler leave a duplex job stuck"
No matching code units.
The words that matched occur in this repository, but never together in one
place, so no single declaration is about what you asked. This is usually a
question about something the repository does not implement, described in words
it happens to use elsewhere.
```

`--json` carries the same answer in a form an agent can branch on:

```json
{"results": [],
 "diagnosis": {"reason": "matched_terms_are_scattered",
               "query_terms": 10,
               "distinctive_terms": ["duplex","job","leave","print","spooler","stuck"],
               "matched_terms": ["job","leave","print"],
               "ubiquitous_terms": ["a","does","the","why"],
               "coverage": 0.5,    "min_coverage": 0.4,
               "concentration": 0.1682, "min_concentration": 0.28,
               "applied_min_coverage": 0.4, "applied_min_concentration": 0.28,
               "hint": "..."}}
```

Read `coverage: 0.5` against `concentration: 0.1682`. Half the distinctive
words are here — `job`, `leave`, `print` — and they are spread thin enough that
no declaration holds a sixth of what was asked. Before 1.1.0 that question came
back with a confident-looking result.

Four reasons, because each is recovered by a different move:

| `reason` | what it means | what to do |
|---|---|---|
| `no_query_term_in_index` | no word of the question occurs anywhere | ask in the code's vocabulary |
| `only_ubiquitous_terms_matched` | only words the repository uses throughout | add a distinctive term |
| `too_little_of_the_query_matched` | most of the question is absent | rephrase, or write descriptions |
| `matched_terms_are_scattered` | the words are here, never together | the subject is probably not in this repository |

## 6 · Benchmark dashboard

Four rulers, 135 distinct questions in English and Chinese, graded 235 times —
two of them run against both repositories. Three grade whether the answer is
**found**; the fourth grades whether silence is **kept**. Every report
carries a fingerprint of the corpus it graded, because between two runs of an
unchanged `search.py` the foreign ruler moved 0.257 → 0.229 purely because that
repository had grown by ninety units.

**Accuracy — default embedder, zero dependencies**

| ruler | what it represents | n | hit@1 | hit@3 | MRR |
|---|---|---|---|---|---|
| **A** foreign repo, no descriptions | what a first-time user gets | 35 | 0.229 | 0.400 | 0.300 |
| **B** this repo, generated descriptions only | a cold index of familiar code | 70 | 0.314 | 0.471 | 0.383 |
| **C** this repo, agent-written descriptions | the warmest case supported | 70 | 0.443 | 0.614 | 0.507 |

**Refusal — the fourth ruler, 30 questions with no answer anywhere**

| | this repo | foreign repo |
|---|---|---|
| correctly met with silence | **0.967** | **0.933** |
| English only | **0.933** | **0.867** |
| Chinese only | **1.000** | **1.000** |
| results resting on no lexical evidence, rulers A–C | **0.000** | **0.000** |

**What each bar costs and buys** — one corpus, gate varied alone:

| gate | A hit@1/3/MRR | B hit@1/3/MRR | C hit@1/3/MRR | silence own / foreign |
|---|---|---|---|---|
| neither (pre-1.0.0) | 0.229/0.400/0.300 | 0.314/0.486/0.391 | 0.471/0.686/0.552 | 0.000 / 0.000 |
| coverage only (1.0.0) | 0.229/0.400/0.300 | 0.314/0.471/0.383 | 0.471/0.671/0.548 | 0.700 / 0.767 |
| **both (1.1.0)** | **0.229/0.400/0.300** | **0.314/0.471/0.383** | 0.443/0.614/0.507 | **0.967 / 0.933** |

Rulers A and B are **identical to three decimals**. The entire cost is four
questions of seventy on the warmest ruler. On these four rulers concentration
subsumes coverage — stated plainly because it is true; coverage is kept because
it answers a different question and names a different diagnosis.

**Latency** — warm corpus, 557 units, 420 samples after warm-up:

| | |
|---|---|
| query, median | **0.41 ms** |
| query, p95 | 0.60 ms |
| refusing an unanswerable query | **0.01 ms** |

Refusal is cheaper than answering by a factor of forty: an unanswerable query
touches only the posting lists of its own distinctive words, never the corpus.

**Scale**, synthetic 10,000-unit repository (500 files):

| | |
|---|---|
| full build | 1.84 s |
| incremental rebuild after one file changes | 0.207 s (**8.9×**) |
| compact storage vs readable JSON | 35.6% |
| index load, fresh process | 45.4 ms |
| resident memory | 58.7 MiB |

**Parsing**, against source-controlled fixtures (15 files, 237 negative cases,
89 constructs the spec deliberately excludes):

| | |
|---|---|
| core declarations found | **91 / 91** |
| with the correct `start_line` | **91 / 91** |
| with a usable signature | **91 / 91** |
| units invented that do not exist | **0** |

Directional local measurements, not service levels. Reproduce with
`python benchmarks/repo_queries.py` and `python benchmarks/large_repo.py`.

## 7 · `rag-your-code search` vs a Grep loop

The fair baseline is not one `grep`. An agent handed Grep picks the content
words out of the question, runs one search per word, and ranks files by how
many hit. That is what this reproduces — same corpus, same questions, same
ruler, scored at **file** granularity so Grep is not penalised for lacking
declaration spans.

**On a repository nobody has described, Grep wins.** That is the measured
result and it is not softened here.

| foreign repository · 35 questions · 1,257 units · no descriptions | Grep loop | rag-your-code |
|---|---|---|
| right file first | **34.3%** | 31.4% |
| right file in top 3 | **60.0%** | 48.6% |
| lines matched across the repo, all questions | 33,115 | — |
| characters returned, all questions | — | **163,521** |
| questions it answers | 35 | 28 |

**Once the vocabulary exists, it is not close.**

| this repository · 70 questions · 557 units · 303 described | Grep loop | rag-your-code |
|---|---|---|
| right file first | 25.7% | **57.1%** |
| right file in top 3 | 64.3% | **75.7%** |
| lines matched across the repo, all questions | 39,550 | — |
| characters returned, all questions | — | **278,929** |
| questions it answers | 70 | 60 |

Those two tables are the whole argument of section 3.3, measured against a real
baseline instead of asserted. A cold index retrieves against a sentence the
parser generated from identifiers the author already chose — so it is competing
with Grep using Grep's own information, and losing, because Grep does not have
to guess which of the matching files is the definition. Descriptions put words
in the index that the source never contained, and first-place accuracy goes
from below Grep's to **more than double** it.

Three qualifications, because the table would otherwise flatter both sides:

- **Scored at file granularity**, which understates this side. A Grep hit is a
  file; a hit here is a declaration with an exact span, a score, and the words
  it matched on. The agent that reads the result opens 40 lines, not a file.
- **Grep answers everything.** It never declines, which is why it hands back
  33,115 matching lines for 35 questions — about 950 lines per question, no
  ranking, no spans, no indication which match is the definition. This returns
  roughly 5,800 characters per question, ranked. Seven of 35 and ten of 70
  questions come back empty here instead, with a reason.
- **Grep wins outright when you know the string.** `grep -rn "COMMON_TERM"` is
  exact, instant and complete, and nothing here replaces it.

The two are complementary, and the honest summary is narrow: this earns its
place on questions phrased as questions, over a repository somebody has taken
the time to describe.

## 8 · Design principles

**Build the ruler before reshaping the thing measured.** Four candidate scoring
changes once landed between five and six correct over an eight-question set —
that is the resolution limit of the instrument, not a ranking of options. There
are 135 now across four rulers, and every claim in this README is a number from
one of them.

**Measure somewhere it can fail.** Every ruler this project had once graded a
repository its own authors wrote. Indexed cold against a foreign repository the
same code scored 0.086 hit@1 against a self-reported 0.457. Ruler A exists so
that can never be comfortable again — and stemming, which helps both own-repo
rulers, was rejected on exactly this evidence: it costs the foreign ruler 3 of
35 hit@3.

**Make the error structurally impossible rather than checking for it.** A line
number that *is* the loop index cannot drift. A description keyed by a digest
of its own code cannot outlive it.

**A ratio inside the query, never a threshold on a score.** Scales move;
ratios do not.

**Derive figures from data; a hand-maintained number is a claim nobody checks.**
The parser fingerprints its own source. The settings table in this README is
asserted against `config.py` in both directions — it had drifted nine settings
behind before that test existed.

**The contract does not move.** `CodeUnit`, index schema 2, and the JSON-lines
protocol are unchanged across every release; new information arrives in new
fields beside the old ones, never by widening an enumeration callers branch on.

**Publish what was measured and rejected.** Twelve changes have been
implemented, measured and dropped. They are recorded in
[docs/ROADMAP.md](docs/ROADMAP.md) with their numbers, because "we tried that
and it cost 3 of 35" is worth more than an unexplored idea.

## 9 · Bringing your own model

Everything above works with no model. Three embedders, and the difference
between them is what the vector is *able* to know.

```toml
# rag-your-code.toml — a model that runs on your machine
[embedding]
provider   = "sentence-transformers"
model      = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
dimensions = 384
```

```bash
pip install "rag-your-code[sentence-transformers]"
```

The extra is optional by construction: `dependencies = []` is what a default
install gets, the import happens inside the constructor, and a test asserts the
default provider imports none of it.

**Measured, on the same four rulers.** This is the first release with a real
model behind these numbers — 0.8.0 shipped the seam and said plainly that its
benefit was unmeasured.

| ruler | signed hash (default) | MiniLM, local |
|---|---|---|
| **A** foreign, cold | 0.229 / 0.400 / 0.300 | **0.286 / 0.457 / 0.357** |
| **B** own, cold | 0.314 / 0.471 / 0.383 | **0.329 / 0.486 / 0.400** |
| **C** own, described | 0.443 / 0.614 / 0.507 | 0.443 / **0.671 / 0.540** |
| **D** silence, own / foreign | 0.967 / 0.933 | 0.967 / 0.933 |

Better on every positive ruler, with refusal unchanged. The pairs the hash
scores exactly zero:

| pair | signed hash | MiniLM |
|---|---|---|
| `retry a failed card charge` vs `resend a payment after a transient error` | 0.298 | **0.583** |
| `retry a failed card charge` vs `delete every row of the user table` | 0.000 | 0.073 |
| `计算两个数的和` vs `sum two numbers` | **0.000** | **0.822** |
| `刷新索引` vs `rebuild the index` | **0.000** | **0.684** |

A semantic embedder is **not** exempt from the evidence bars, and that is a
correction to 1.0.0. Exempting one was reasoned — a paraphrase sharing no word
with its answer is exactly what a model is for — and it was wrong: exempt and
asked no other question, the model answered all sixty unanswerable questions.
Two vector-space replacements were measured and rejected: a similarity floor is
a threshold on a score and the distributions overlap (0.469 vs 0.418 median),
and a scale-free standout metric took ruler B from 0.329 to 0.186 for two
thirds of the silence. Applying the lexical bars costs ruler A nothing.

**A hosted endpoint** is the third option, and the only one that sends your
source anywhere:

```toml
provider    = "openai-compatible"
endpoint    = "https://api.example.com/v1/embeddings"
model       = "text-embedding-3-small"
dimensions  = 1536
api_key_env = "OPENAI_API_KEY"     # the NAME of the variable, never the key
```

The key is never a setting. `rag-your-code.toml` is meant to be committed so
everyone who clones sees what shaped the index; a credential is the one value
with the opposite requirement. Sending a key over plain `http://` to anything
but your own machine is refused rather than warned about. A failure stops the
build rather than falling back, because a mixed index is two vector spaces and
a cosine across them is a meaningless number ranking would act on anyway.

With a semantic embedder, similarity may also **add** candidates rather than
only reorder them (`search.vector_recall`) — the one thing that can reach a
unit sharing no word with the question. Under the hash the same widening
measured worse, so it stays off there.

## 10 · Install and use

**As a Claude Code plugin** (the primary way):

```
/plugin marketplace add skymanbp/rag-your-code
/plugin install rag-your-code@rag-your-code
/reload-plugins
```

One skill, no hooks, no agents, no MCP server: **~39 tokens added to every
session**, ~1.4k only when it fires. The skill installs the package on first
use.

**As a CLI:**

```bash
rag-your-code bootstrap .                       # index, then say what is missing
rag-your-code search "how are stale indexes detected" --json
rag-your-code search "what calls the retry handler" --graph --hops 1
rag-your-code describe status                   # description coverage
rag-your-code describe promote | git apply      # move descriptions into the code
```

`bootstrap` exists because indexing is not the same as being searchable. A
fresh index retrieves against the sentence the parser generated, which adds no
word the source did not have. It reports which rung the repository is on and
hands over that rung's work; run it again after each round.

The index is written under `.rag-your-code/`; **your source files are never
modified**. `describe promote` emits a diff for you to review — the tool never
writes source itself.

### Configuration

22 settings in `rag-your-code.toml`:

| section | settings |
|---|---|
| `[index]` | `ignore`, `suffixes`, `max_file_bytes` |
| `[embedding]` | `dimensions`, `provider`, `endpoint`, `model`, `api_key_env`, `batch`, `timeout`, `retries` |
| `[search]` | `min_coverage`, `min_concentration`, `vector_weight`, `vector_recall`, `limit`, `max_chars` |
| `[agent]` | `max_open_bytes`, `max_open_chars` |
| `[describe]` | `languages`, `batch`, `max_chars` |

This table is asserted against `config.py` in both directions by
`tests/test_metadata.py`. Resolution is CLI flag > file > built-in default;
there is deliberately no environment layer, because an index is an artifact of
a repository rather than of a shell. An unknown key or out-of-range value is an
error, not a shrug.

### Agent protocol

`rag-your-code agent --root PATH` reads one JSON request per line, writes one
reply per line:

```json
{"action":"search","query":"database transaction rollback","limit":5}
{"action":"research","query":"trace payment retry behavior","max_steps":2}
{"action":"neighbors","id":"payments.py:4:retry_charge","hops":1}
{"action":"open","path":"payments.py","start_line":1,"end_line":80}
{"action":"describe_pending","limit":20}
{"action":"describe_put","descriptions":[{"id":"payments.py:4:retry_charge","text":"..."}]}
```

**A result is navigation, not the file.** The code arrives once, in `context`,
trimmed to `max_chars`, with `omitted_for_budget` saying how many results it
did not reach. Carrying source per result is what let one `search --json` reply
reach 65,025 characters against a stated budget of 12,000.

**No single request can end the session.** Numeric fields saturate at their
bounds, `open` is bounded in lines and bytes, and anything unanticipated is
reported in-band with its exception type. Streams are pinned to UTF-8 rather
than following the console codepage.

### What lives where

| path | authored or generated | commit it? |
|---|---|---|
| `rag-your-code.toml` | authored | yes |
| `rag-your-code.descriptions.json` | authored by your agent | yes |
| `.rag-your-code/` | generated | no |

## 11 · Known limits

Named because they are measured, not because they are excuses.

**One English question in fifteen still gets answered when it should not.**
`how is a hostname resolved when the nameserver times out` finds `hostname`,
`resolved` and `times` genuinely co-occurring in one unrelated declaration, on
both repositories. No lexical rule separates a real vocabulary collision from a
real answer. Chinese sits at 1.000 silence on both.

**Chinese cold-start hit@1 is 0.000** on rulers A and B. Chinese reaches a
repository through descriptions or not at all: the code contains no Chinese, so
a cold index has no Chinese vocabulary to match. `describe` is the fix and it
works — ruler C is 0.333 — but there is no free rung of the ladder for it.

**There is no stemming.** `catastrophic backtracking` does not reach
`backtracks catastrophically`. A light suffix stripper was implemented and
measured on all four rulers: it improves both own-repository rulers and costs
the foreign one 3 of 35 hit@3, so it was rejected.

**A test declaration sometimes outranks real code** — 10 of 175 questions across
three rulers, where a test at rank 1 displaced an accepted answer at rank 2–3.
The long-standing explanation, that a test outranks the code it *tests*, is
wrong: of the eight inspected, seven are unrelated tests winning on
prose. A callee-before-caller rerank fires on zero questions and the `name`
field weight moves nothing, because an underscored test name is a single token.

**The vectors are 65.4% of the index and earn ±1 question** under the default
embedder. Not removed: the same storage is what makes an optional model work,
and the schema stays one shape.

**`search.vector_recall` scans every vector per query.** Affordable at the
measured envelope, and exactly the work an ANN index would replace.

**Tree-sitter parsing and a SQLite/ANN storage layer are not here.** Both would
need a dependency, and the policy for those is settled: they follow the
embedding provider's pattern — optional, user-selected, never in the default
install. Full reasoning in [docs/ROADMAP.md](docs/ROADMAP.md).

## 12 · Development

```bash
python -m pip install -e ".[dev]"
pytest -q
```

Per-release test counts are in [CHANGELOG.md](CHANGELOG.md); a bare figure in a
living document is a claim that rots. CI runs Python 3.10–3.13 on Linux and
Windows, plus a job that installs the built wheel into a clean environment and
runs every documented command, and another that runs the skill's own install
line verbatim.

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — how each stage works and why
- [docs/TESTING.md](docs/TESTING.md) — what the suites protect
- [docs/ROADMAP.md](docs/ROADMAP.md) — what shipped, what was rejected and why
- [CONTRIBUTING.md](CONTRIBUTING.md) — ground rules, and how to add a language
- [CHANGELOG.md](CHANGELOG.md) — every release with its measurements

MIT licensed.
