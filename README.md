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
grep for. **Reading whole files** is thorough and blows the context budget.

Retrieval sits in between and brings a third problem neither has: Grep can say
it found nothing, and **a ranking cannot.** It always produces a least-bad
candidate and returns it with a score and rank that read exactly like an answer,
whether or not the repository holds anything relevant.

## 2 · What it does

| | |
|---|---|
| **Index** | Every function, method and class in 15 languages becomes one `CodeUnit`: id, signature, exact line range, source, calls, imports, description. |
| **Retrieve** | BM25F over five weighted fields, blended with vector similarity. Results carry the terms they matched on. |
| **Refuse** | Two evidence tests decide whether *any* result is an answer; when neither is met, retrieval returns nothing plus a machine-readable diagnosis. |
| **Expand** | Optional bounded walk over `calls` / `imports` / `contains`, each hop carrying its edge path as evidence. |
| **Describe** | Your agent writes the vocabulary the source never contained, stored in a committed sidecar or promoted into the code as a reviewable diff. |
| **Serve** | A CLI, plus a JSON-lines protocol for a long-lived agent subprocess. |

**Scope.** Retrieval over source declarations — not a code-understanding model,
not a generation step, not an IDE index. Questions are answered in vocabulary
somebody wrote down: in the code, its documentation, or an agent's description.

## 3 · What is actually hard here

Three things, and all three are measured rather than argued.

### 3.1 · Ranking cannot say "no answer"

Eight releases measured how well retrieval *finds* the answer. None could see
what it does when there is none, because every question graded had one. A
ruler of its own — thirty questions about subjects no graded repository
implements — settled it in one run: **all thirty answered**, both languages,
every corpus.

| asked of a repository containing no such code | answered with | on the evidence of |
|---|---|---|
| `where are CUDA kernels dispatched to the device` | a test about word counting | `are` `the` `to` `where` |
| `准入钩子为什么会拒绝没有资源限额的工作负载` | the UTF-8 console setup | `拒绝` `没有` `为什么` |
| `how is the OAuth refresh token rotated` | a description-store method | `before` `is` `refresh` `the` |

Not a Chinese problem and not a ranking problem — a **missing question**: nothing
in the pipeline ever asked *is any of this evidence*.

Retrieval now asks two questions that ranking cannot:

**Coverage** — what share of the query's *discriminating* words occur in the
index at all. Words the repository uses everywhere are dropped from both sides
of the fraction, and that is the part that does the work: half of `where are
CUDA kernels dispatched to the device` matches, and it looks like evidence
until you notice which half.

**Concentration** — what share of the query's *rarity* lands inside a single
declaration. Coverage alone asks whether each word occurs somewhere, which a
question about an unimplemented subject can satisfy entirely out of unrelated
units: four of six words in four declarations with nothing to do with the
question or with one another. Rarity-weighted rather than counted, because two
ordinary words are not better evidence than the rare word asked about.

Both are **ratios inside the query**, never thresholds on a score: a score
threshold is tied to whatever scale the ranking produces, and one here silently
stopped existing the moment BM25F changed that scale.

### 3.2 · The vector was carrying nothing, and here is why

The default embedder is a signed feature hash. Ablating it entirely moves the
four positive rulers by **at most two questions, and in both directions**, while
the vectors occupy **72.1%** of the index. Known since 0.6.0 and unexplained.
The explanation, measured here:

- **Not saturation.** Median 56 distinct tokens per unit into 384 buckets, 0.4%
  over the width; widening to 16,384 raises fidelity from r=0.40 to r=0.56 and
  buys no ranking.
- **Not redundancy.** Its cosine correlates only **+0.45** with BM25F over
  26,490 scored candidates, so it does carry variance of its own.
- **The variance is the wrong variance.** A signed hash counts every token
  equally, so the independent part of what it measures is precisely the
  contribution of words that are everywhere — the part rarity weighting exists
  to discard. Independent *noise*, not independent signal.
- **And it can only reorder.** Candidates come from the lexical half, so a
  vector cannot make anything retrievable. Six of thirty-five foreign-ruler
  questions have an accepted answer sharing **no token at all** with the query.

Eight replacement schemes were measured across releases — character n-grams,
random indexing, truncated SVD, posting-list signatures, a rarity-weighted hash,
call-graph diffusion, postings expansion, authored-fields-only. None beat using
no vector: **a vector computed from the same words cannot know anything the
words do not already say.** Making it useful takes a model, which is an
installable option and is measured below.

### 3.3 · Retrieval reaches only what somebody wrote down

`retry_charge` tokenizes to one opaque term, not to *retry* and *charge*.
Splitting identifiers was measured with query and stored vectors rebuilt
together: equal or worse on every ruler, because the pieces are `get`, `find`
and `check`, which rarity weighting discounts.

So the vocabulary ladder is the answer, cheapest rung first:

| source | who wrote it | lives in | survives a refactor | cost |
|---|---|---|---|---|
| identifier, signature, body | author | the code | by construction | free |
| docstring / doc comment, 15 languages | author | the code | by construction | free |
| promoted description | agent | the code | by construction | one review |
| agent description | agent | a sidecar | needs machinery | tokens |

## 4 · How it works

Drawn out, with the refusal path and the surfaces: **[docs/FLOW.md](docs/FLOW.md)**.

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
line number **is** the loop index and cannot drift, and no declaration can
swallow the ones after it. A 530-byte JavaScript file that took 12.6 s to parse
now takes 0.37 ms.

Qualified names come from the spans the closer already produced: nested inside
another's span *is* nested in it. One mechanism, so there is no second one to
disagree with it.

**Ranking.** BM25F with per-field length normalisation, which is the part that
matters: against one length for the whole unit, a body repeating a word forty
times beat the declaration named after it, raw count cancelling length penalty.

| field | weight | why |
|---|---|---|
| `name` | 8 | what the author called the thing |
| `signature` | 4 | what it takes and returns |
| `description` | 3 | what somebody said it does |
| `relations` | 2 | what it calls and imports |
| `body` | 1 | a mention |

**Rarity comes from your corpus, not a stopword list.** `the` and `calls` earn
their low weight the same way a Chinese bigram does — by being everywhere — so
no list is maintained and an unanticipated language works. It is also where the
design degrades: see the refusal table in section 6.

**Safety.** A scanned repository is untrusted input, including any
`.rag-your-code/index.json` it ships, so nothing read out of an index may name
a path to act on: superseded sidecars are enumerated from the writer's own
naming scheme. A crafted index once made `index` delete an in-tree file.

## 5 · Before and after

A question with no lexical shortcut, asked of this repository:

````console
$ rag-your-code search "where does it decide whether to answer at all" --limit 1
[src/ragyourcode/search.py:117:Evidence] score=0.447
The verdict on whether a question reached this index at all, kept separate from
how results rank. ... 中文：判定一个提问究竟有没有够到索引的结论。...
```python
class Evidence:
    """Whether a query reached this index at all, kept apart from ..."""
```
````

There is no string here to grep for: *decide* occurs nowhere in that
declaration and matched nothing. What ranked it first is ordinary words —
*answer*, *whether*, *where* — rare enough in this corpus to tell declarations
apart. What the agent-written description adds is the other language:
「在哪里判定一个提问有没有答案」 returns the same declaration first, at 0.395,
sharing not one character with its source.

Now the case that motivated 1.0.0 — a question with no answer here at all:

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
               "concentration": 0.1691, "min_concentration": 0.28,
               "applied_min_coverage": 0.4, "applied_min_concentration": 0.28,
               "hint": "..."}}
```

Read `coverage: 0.5` against `concentration: 0.1691`. Half the distinctive
words are here — `job`, `leave`, `print` — and spread thin enough that no
declaration holds a fifth of what was asked, against a bar of 0.28. Before
1.1.0 it came back with a confident-looking result.

Four reasons, because each is recovered by a different move:

| `reason` | what it means | what to do |
|---|---|---|
| `no_query_term_in_index` | no word of the question occurs anywhere | ask in the code's vocabulary |
| `only_ubiquitous_terms_matched` | only words the repository uses throughout | add a distinctive term |
| `too_little_of_the_query_matched` | most of the question is absent | rephrase, or write descriptions |
| `matched_terms_are_scattered` | the words are here, never together | the subject is probably not here |

## 6 · Benchmark dashboard

Five rulers, 175 distinct questions in English and Chinese, graded 305 times —
one of them runs against all three corpora. Four grade whether the answer is
**found**; the fifth grades whether silence is **kept**. Every report carries a
fingerprint of the corpus it graded, because between two runs of an unchanged
`search.py` the foreign ruler moved 0.257 → 0.229 purely because that
repository had grown by ninety units.

**Accuracy — default embedder, zero dependencies**

| ruler | what it represents | n | hit@1 | hit@3 | MRR |
|---|---|---|---|---|---|
| **E** cobra v1.9.1, Go, no descriptions | a foreign repo in a foreign language | 40 | 0.075 | 0.150 | 0.108 |
| **A** Flask 3.1.3, no descriptions | what a first-time Python user gets | 35 | 0.200 | 0.286 | 0.238 |
| **B** this repo, generated descriptions only | a cold index of familiar code | 70 | 0.314 | 0.471 | 0.381 |
| **C** this repo, agent-written descriptions | the warmest case supported | 70 | 0.429 | 0.600 | 0.498 |

The corpora, without which none of the above is reproducible — **E** 602 units,
`3eabaa705477`; **A** 1,572 units, `5fd51169eacc`; **B** 604 units,
`81e47eb0a50c`; **C** 604 units, `f84556ba7881`. Both foreign subjects are
carried in this repository at pinned tags, under
[`benchmarks/corpus/`](benchmarks/corpus/), and CI runs both as ordinary jobs.

**The spread across those four rows is the honest headline.** The same code
scores 0.075 and 0.429 depending on nothing but which repository it is asked
about and whether anyone described it. Ruler E is 1.5.0's third corpus and the
first that is not Python: Go documents *above* the declaration in one terse
sentence beginning with the identifier, which the parser picks up correctly and
which shares almost nothing with the words a user asks in. Prose density, not
language, is what a cold number tracks.

**Refusal — the fifth ruler, 30 questions with no answer anywhere**

| | this repo | Flask | cobra |
|---|---|---|---|
| correctly met with silence | **0.967** | **0.833** | **0.900** |
| English only | **0.933** | 0.667 | 0.800 |
| Chinese only | **1.000** | **1.000** | **1.000** |
| results resting on no lexical evidence | **0.000** | **0.000** | **0.000** |

Silence is lower on both foreign corpora than on this one, and the cause is a
limit of the design rather than a defect. A word counts as evidence unless it
occurs in more than 5% of units — a stopword list derived from the corpus, so
that it needs no list and works in any language. Here `how`, `when`, `does` and
`are` are everywhere, because 317 units carry written English prose. Across a
corpus of short, tersely documented declarations they occur in 1–5% of them and
start counting as evidence: on cobra, three English questions get through on
sets like `[a, is, the, how, after]`.

**What each bar costs and buys** — corpora stamped above, gate varied alone:

| gate | A | B | C | E | silence own / Flask / cobra |
|---|---|---|---|---|---|
| neither (pre-1.0.0) | 0.200/0.286/0.238 | 0.314/0.486/0.388 | 0.486/0.686/0.567 | 0.100/0.200/0.146 | 0.000 / 0.000 / 0.000 |
| coverage only (1.0.0) | 0.200/0.286/0.238 | 0.314/0.471/0.381 | 0.486/0.671/0.559 | 0.075/0.175/0.121 | 0.500 / 0.733 / 0.767 |
| concentration only | 0.200/0.286/0.238 | 0.314/0.471/0.381 | 0.429/0.600/0.498 | 0.075/0.150/0.108 | 0.967 / 0.800 / 0.833 |
| **both (1.1.0)** | **0.200/0.286/0.238** | **0.314/0.471/0.381** | 0.429/0.600/0.498 | 0.075/0.150/0.108 | **0.967 / 0.833 / 0.900** |

Ruler A is **unmoved by either bar**; B loses one hit@3 question to either bar
alone and nothing further when both apply. The rest is four of seventy at hit@1
on the warmest ruler and six at hit@3, plus one and two of forty on the Go one.

**Both bars together give the best silence on all three corpora.** Through
1.3.0 this section said concentration subsumes coverage; on Flask it does not
(0.833 against 0.800), and the third corpus, which arrived long after the
defaults were fixed, says the same (0.900 against 0.833). Four constants fitted
on two repositories, tested on a third in a language nobody here chose, and not
one of them moved.

Raising the bar buys the remaining silence out of the answers, and is refused:
at 0.50 the foreign absent ruler is silent on all thirty while A falls to 0.086
hit@1, B to 0.214 and C to 0.329. **0.28 was chosen before either foreign
corpus existed and survived meeting both**, which is the only kind of evidence
a default can have.

**Latency** — warm corpus, 604 units `f84556ba7881`, one
`python -m benchmarks.query_latency` (5 repeats × 420 samples), idle machine:

| | | across the repeats |
|---|---|---|
| query, median | **0.73 ms** | 0.70 – 0.78 |
| query, p95 | 1.30 ms | 1.17 – 1.39 |
| refusing an unanswerable query | **0.016 ms** | 0.015 – 0.018 |
| refusal cheaper than answering by | **~44×** | 40 – 47 |

*Idle* is load-bearing: the same corpus at the same commit measured 0.99 ms
median while a coverage run was in progress and 0.49 ms once it finished.
This row read 0.49 ms in 1.5.0 at 601 units; a corpus 0.5% larger cannot
explain 40%, and a repeat run here read 0.69 ms — the machine moved, not the code.

Two significant figures and a spread, because that is the precision this has.
Across five releases on the same idle machine the median has landed from 0.49
to 1.44 ms and p95 from 0.85 to 7.34 ms — a band wider than any change the code
has made to it. Releases before 1.3.0 published `0.83 ms / p95 1.68 ms` to
three figures from an uncommitted script; both sit inside that band, which is
the point — unfalsifiable rather than wrong. Refusal is cheap structurally: an
unanswerable query touches only its distinctive words' posting lists, never ranking.

**Scale**, synthetic 10,000-unit repository (500 files), re-measured in 1.5.0
— the previous row of figures was optimistic by more than noise:

| | | previously published |
|---|---|---|
| full build | 3.45 s | 1.84 s |
| incremental rebuild after one file changes | 0.286 s (**12.1×**) | 0.207 s |
| compact storage vs readable JSON | 35.6% | 35.6% |
| index load, fresh process | 79.3 ms | 45.4 ms |
| resident memory | 72.2 MiB | 58.7 MiB |
| mean query, full recall | 15.6 ms | 3.90 ms |

That last row had been carried since before BM25F replaced the scoring it was
taken under. Six releases, a committed script, and nothing that made anyone run
it again.

**Parsing**, against source-controlled fixtures (15 files, 237 negative cases):

| | |
|---|---|
| core declarations found | **91 / 91** |
| with the correct `start_line` | **91 / 91** |
| with a usable signature | **91 / 91** |
| units invented that do not exist | **0** |

Directional local measurements, not service levels — but each is a command
rather than a memory, which two of them were not before. Each
prints the corpus fingerprint beside its score; quote both or neither.
[`benchmarks/README.md`](benchmarks/README.md) lists the seven scripts and what
each is for, and the corpus one of them grades is now carried here too.

## 7 · `rag-your-code search` vs a Grep loop

The fair baseline is not one `grep`. An agent handed Grep picks the content
words out of the question, runs one search per word, and ranks files by how
many hit. That is what this reproduces — same corpus, same questions, same
ruler, scored at **file** granularity so Grep is not penalised for lacking
declaration spans.

**On an undescribed repository, which side wins depends on the repository.**
Three subjects, three answers:

| undescribed · Grep loop → rag-your-code | first | top 3 | answered | characters |
|---|---|---|---|---|
| **Flask** 35 q · 1,572 units `5fd51169eacc` | 22.9% → **37.1%** | 45.7% → **57.1%** | 30 → 30 | 1,415,656 → **258,236** |
| **cobra** 40 q · 602 units `3eabaa705477` | 17.5% → 17.5% | 20.0% → **30.0%** | 22 → 17 | 799,475 → **156,336** |
| a hook-heavy tool, retired in 1.4.0 | 34.3% → 31.4% | — | — | — |

Flask wins for this side, cobra ties on first place, and the retired subject
lost. A cold index retrieves against a generated sentence plus whatever the
author documented, so the outcome is set by how much prose the repository
already carries — Flask documents most public methods in paragraphs, cobra in
one terse line, the retired tool barely at all. What holds on all three is the
payload: this side hands back a fifth to a half of the text, ranked and spanned.

**Once the vocabulary exists, it is not close.**

| this repository · 70 questions · 604 units `f84556ba7881` · 317 described | Grep loop | rag-your-code |
|---|---|---|
| right file first | 22.9% | **58.6%** |
| right file in top 3 | 52.9% | **78.6%** |
| lines it hands back, all questions | 12,540 | — |
| characters returned, all questions | 1,190,816 | **611,859** |
| questions it answers | **61** | 60 |

That is section 3.3's argument measured rather than asserted, and it is the one
thing the subject does not change: first-place accuracy more than doubles
Grep's.

**Every table comes from `python -m benchmarks.grep_baseline`**, new in 1.3.0.
Until then this section — the strongest claim the project makes — came from an
uncommitted script, so nothing here could be checked and "Grep loop" had no
precise meaning. The committed version defines it: take the query's words, drop
the ones the corpus itself shows are everywhere, run one substring search per
remaining word over exactly the files the index was built from, rank each file
by how many distinct words hit it, break ties on path.

Qualifications, because the tables would otherwise flatter both sides:

- **Scored at file granularity**, which understates this side. A Grep hit is a
  file; a hit here is a declaration with an exact span, a score, and the words
  it matched on. The agent that reads the result opens 40 lines, not a file.
- **Dropping the corpus-common words is generous to Grep**, and is what makes
  the baseline fair rather than a straw man: an agent that greps `the` gets
  every file back in no order. It is also why Grep declines nine of the seventy
  questions here — no word was left that this corpus does not use everywhere.
- **Payload is counted in characters on both sides.** Grep hands back roughly
  19,300 characters per question it answers here, unranked and without spans,
  against 10,300 ranked and capped by `search.max_chars` — a factor of 1.9,
  5.5 on Flask and 5.1 on cobra, where a framework repeats its vocabulary
  across files and Grep cannot rank what it finds. 1.4.1 changed what fits in
  that cap: the block had been reprinting the docstring the code below already
  showed, so the same budget now carries **119 declarations instead of 92** on
  Flask.
- **Chinese is the corpus's limit, not the tool's, when a corpus is
  monolingual.** Both sides decline the same five of Flask's 35 — every Chinese
  one. A Chinese word is neither a substring of English source nor a token in
  an index built from it.
- **Grep wins outright when you know the string.** `grep -rn "COMMON_TERM"` is
  exact, instant and complete, and nothing here replaces it.

The two are complementary, and the honest summary is narrow: this earns its
place on questions phrased as questions, over a repository somebody described.

## 8 · Design principles

**Build the ruler before reshaping the thing measured.** Four candidate scoring
changes once landed between five and six correct over an eight-question set —
the instrument's resolution limit, not a ranking. There are 175 questions now
across five rulers, and every claim here is a number from one of them.

**Measure somewhere it can fail.** Every ruler this project had once graded a
repository its own authors wrote; cold against a foreign one the same code
scored 0.086 hit@1 against a self-reported 0.457. Rulers A and E exist so that
cannot be comfortable again — stemming, which helps both own-repo rulers, was
rejected on A, and E publishes a 0.075 this project would rather not print.

**Make the error structurally impossible rather than checking for it.** A line
number that *is* the loop index cannot drift; a description keyed by a digest
of its own code cannot outlive it. **And a ratio inside the query, never a
threshold on a score** — scales move, ratios do not.

**Derive figures from data; a hand-maintained number is a claim nobody checks.**
This README's settings table is asserted against `config.py` in both directions
— it had drifted nine settings behind before that test existed — and the four
diagrams in `docs/FLOW.md` are parsed by a test that refuses a label mermaid
would silently fail to render.

**The contract does not move.** `CodeUnit`, index schema 2 and the JSON-lines
protocol are unchanged across every release: new information arrives in new
fields, never by widening an enumeration callers branch on.

**Publish what was measured and rejected.** Twelve changes were implemented,
measured and dropped, with their numbers, in [docs/ROADMAP.md](docs/ROADMAP.md)
— "we tried that and it cost 3 of 35" beats an unexplored idea.

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

The extra is optional by construction: `dependencies = []` is a default
install, the import happens inside the constructor, and a test asserts the
default provider imports none of it.

**Measured on the four rulers that then existed, both arms against one
corpus.** 1.1.0 published this comparison and read it as a win; its largest
gain was on the foreign ruler, whose two arms turned out to have been taken
against two states of a repository being edited while the script ran. Repeated
against a pinned corpus:

| ruler | corpus | signed hash (default) | MiniLM, local |
|---|---|---|---|
| **A** foreign, cold | 1,572 `5fd51169eacc` | **0.200 / 0.286 / 0.238** | 0.171 / 0.257 / 0.214 |
| **B** own, cold | 581 `8e1e71942c1c` | 0.314 / 0.471 / 0.383 | 0.314 / 0.471 / 0.383 |
| **C** own, described | 581 `978a1d48a82a` | **0.443 / 0.614 / 0.507** | 0.429 / 0.600 / 0.500 |
| **D** silence, own / foreign | as above | 0.967 / 0.833 | 0.967 / 0.833 |

**Worse or identical on every ruler.** The 581-unit stamps are the corpus both
arms shared, kept rather than refreshed — that is what a stamp is for. It ships
anyway for the one thing the hash cannot do and these rulers cannot see: reach
a unit sharing no word with the question. The pairs it scores zero on:

| pair | signed hash | MiniLM |
|---|---|---|
| `retry a failed card charge` vs `resend a payment after a transient error` | 0.298 | **0.583** |
| `retry a failed card charge` vs `delete every row of the user table` | 0.000 | 0.073 |
| `计算两个数的和` vs `sum two numbers` | **0.000** | **0.822** |
| `刷新索引` vs `rebuild the index` | **0.000** | **0.684** |

A semantic embedder is **not** exempt from the evidence bars, correcting
1.0.0. Exempting one was reasoned — a paraphrase sharing no word with its
answer is exactly what a model is for — and wrong: exempt and asked no other
question, the model answered all sixty unanswerable questions. Two vector-space
replacements were then measured and rejected: a similarity floor is a threshold
on a score and the distributions overlap (0.469 vs 0.418 median), and a
scale-free standout metric took ruler B from 0.329 to 0.186 for two thirds of
the silence. Applying the lexical bars costs ruler A nothing.

Install it for the cross-language and paraphrase cases above, not for the hit rates.

**A hosted endpoint** is the third option, and the only one that sends your
source anywhere:

```toml
provider    = "openai-compatible"
endpoint    = "https://api.example.com/v1/embeddings"
model       = "text-embedding-3-small"
dimensions  = 1536
api_key_env = "OPENAI_API_KEY"     # the NAME of the variable, never the key
```

The key is never a setting: `rag-your-code.toml` is meant to be committed so
everyone who clones sees what shaped the index, and a credential is the one
value with the opposite requirement. Sending a key over plain `http://` to
anything but your own machine is refused rather than warned about, and a
failure stops the build rather than falling back — a mixed index is two vector
spaces, and a cosine across them is a meaningless number ranking would act on.

With a semantic embedder, similarity may also **add** candidates rather than
only reorder them (`search.vector_recall`) — the one thing that can reach a
unit sharing no word with the question. Under the hash it measured worse, so it
stays off there.

## 10 · Install and use

**As a Claude Code plugin** (the primary way):

```
/plugin marketplace add skymanbp/rag-your-code
/plugin install rag-your-code@rag-your-code
/reload-plugins
```

Updating needs the full id and a marketplace refresh first; the bare name is
refused with `Plugin "rag-your-code" not found`, which reads like it is gone:

```bash
claude plugin marketplace update rag-your-code
claude plugin update rag-your-code@rag-your-code   # then restart
```

Four commands and one skill. No hooks, no agents, no MCP server:

| | |
|---|---|
| `/rag-your-code:index` | index, and say which rung this repository is on |
| `/rag-your-code:search` | ask in plain language; cite `path:line` |
| `/rag-your-code:describe` | write the vocabulary the source does not contain |
| `/rag-your-code:status` | stale? coverage? which embedder? what next? |

Measured with `claude plugin details` on an installed copy: **~249 tokens added
to every session** (skill ~30, each command ~50–60), and 590–2,400 only when
one fires. Up from ~39 in 1.1.0, and the increase is the price of being
findable: a skill fires only when a model decides it should, which left the
plugin with no entry point a person could discover.

**As a CLI:**

```bash
rag-your-code bootstrap .                       # index, then say what is missing
rag-your-code search "how are stale indexes detected" --json
rag-your-code search "what calls the retry handler" --graph --hops 1
rag-your-code describe status                   # description coverage
rag-your-code describe promote | git apply      # move descriptions into the code
```

`bootstrap` exists because indexing is not the same as being searchable: a
fresh index retrieves against a generated sentence that adds no word the source
did not have. It reports which rung the repository is on and hands over that
rung's work; run it again after each round. The index is written under
`.rag-your-code/` and **your source files are never modified** — `describe
promote` emits a diff to review rather than writing source.

### Configuration

23 settings in `rag-your-code.toml`:

| section | settings |
|---|---|
| `[index]` | `ignore`, `suffixes`, `max_file_bytes` |
| `[embedding]` | `dimensions`, `provider`, `endpoint`, `model`, `api_key_env`, `batch`, `timeout`, `retries` |
| `[search]` | `min_coverage`, `min_concentration`, `vector_weight`, `vector_recall`, `limit`, `max_chars` |
| `[agent]` | `max_open_bytes`, `max_open_chars` |
| `[describe]` | `languages`, `batch`, `max_chars`, `skip` |

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

**One English question in fifteen is answered when it should not be** on this
repository, and five in fifteen on Flask. `how is a hostname resolved when the
nameserver times out` finds `hostname`, `resolved` and `times` genuinely
co-occurring in one unrelated declaration. No lexical rule separates a real
vocabulary collision from a real answer. Chinese sits at 1.000 silence on both.

**Chinese cold-start hit@1 is 0.000** on rulers A and B. Chinese reaches a
repository through descriptions or not at all: the code contains no Chinese, so
a cold index has no Chinese vocabulary to match. `describe` is the fix and it
works — ruler C is 0.250 on its twelve Chinese questions — but there is no free
rung of the ladder for it. A Grep loop scores 0.000 there too, on the same
questions: it is the corpus's limit, not this tool's.

**There is no stemming.** `catastrophic backtracking` does not reach
`backtracks catastrophically`. A light suffix stripper was implemented and
measured on every ruler that then existed: it improves both own-repository
rulers and costs the foreign one 3 of 35 hit@3, so it was rejected.

**A test declaration sometimes outranks real code** — 9 of 215 questions across
all four positive rulers (`benchmarks/displacement.py`), a test at rank 1
displacing an accepted answer at rank 2–3, **none of them foreign**. The long-standing
explanation, that a test outranks the code it *tests*, is wrong: five of the
nine are unrelated tests winning on prose. A callee-before-caller rerank fires
on zero questions, and the `name` field weight moves nothing because an
underscored test name is one token.

**Describing a declaration that already has a good docstring loses ground.** An
authored description *replaces* the generated sentence, which is the only route
by which the author's docstring reaches the weight-3 description field — so
writing one demotes it to the weight-1 body. On `parser.py::_generic_units` a
long description cost one graded question and a short one cost three;
appending the docstring to every description instead cost the 1.5.0 corpus
0.443 → 0.414 hit@1. `describe.skip` records the decision.

**The vectors are 72.1% of the index and earn at most two questions** under the
default embedder — 74.8% Flask, 79.7% cobra. Ablating costs A one, gains B one
and C two at hit@3, moves E none; that storage is what an optional model needs.

**`search.vector_recall` scans every vector per query** — under a semantic
embedder. The default hash never widens at all. Affordable at the measured
envelope, and exactly the work an ANN index would replace.

**Tree-sitter parsing and a SQLite/ANN storage layer are not here.** Both need
a dependency, and the policy is settled: they follow the embedding provider's
pattern — optional, user-selected, never in a default install. Full reasoning
in [docs/ROADMAP.md](docs/ROADMAP.md).

**Whether the skill fires unprompted is not measured**, and it is the only
claim here with no command behind it. `claude plugin eval` grades exactly this
— `tool_used: Skill` as the indicator, against a no-plugin baseline arm — but
it is gated behind an account-level early access this project does not have,
and a suite written from `--help` fragments could not be run once to see
whether it loads. Since 1.2.0 the four commands give an entry path that does
not depend on it.

## 12 · Development

```bash
python -m pip install -e ".[dev]"
pytest -q
```

Per-release test counts and line coverage are in
[CHANGELOG.md](CHANGELOG.md); a bare figure in a living document is a claim
that rots. `pytest --cov=ragyourcode` is the command behind the coverage one.
CI runs Python 3.10–3.13 on Linux and Windows, installs the built wheel into a
clean environment and runs the documented CLI end to end — `bootstrap` through
`describe promote` — plus the skill's own install line verbatim, and grades
every ruler including both vendored corpora.

- [docs/FLOW.md](docs/FLOW.md) — the whole thing in four diagrams
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — how each stage works and why
- [docs/TESTING.md](docs/TESTING.md) — what the suites protect, and how covered
- [docs/ROADMAP.md](docs/ROADMAP.md) — what shipped, what was rejected and why
- [CONTRIBUTING.md](CONTRIBUTING.md) — ground rules, and how to add a language
- [CHANGELOG.md](CHANGELOG.md) — every release with its measurements
- [benchmarks/corpus/](benchmarks/corpus/) — the two vendored repositories

MIT licensed.
