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
occupy **65.3%** of the index. That was known since 0.6.0 and left unexplained.
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
| **A** Flask 3.1.3, no descriptions | what a first-time user gets | 35 | 0.200 | 0.286 | 0.238 |
| **B** this repo, generated descriptions only | a cold index of familiar code | 70 | 0.314 | 0.471 | 0.383 |
| **C** this repo, agent-written descriptions | the warmest case supported | 70 | 0.443 | 0.614 | 0.509 |

The corpora, without which none of the above is reproducible — **A** 1,572
units, `5fd51169eacc`; **B** 584 units, `fb1f841fa43a`; **C** 584 units,
`c9df00350cbd`. Ruler A grades **a copy of Flask 3.1.3 carried in this
repository**, at [`benchmarks/corpus/flask`](benchmarks/corpus/flask), pinned
to commit `22d9247`. Through 1.3.0 it graded a checkout on one machine, and
that cost three things: two questions pointed at a declaration the subject had
renamed, a published score moved 0.257 → 0.229 with no code change because the
subject had grown, and the model comparison below was taken against two
different states of it. All three are now a `git clone` away from being
checked, and CI runs this ruler as an ordinary job.

**Refusal — the fourth ruler, 30 questions with no answer anywhere**

| | this repo | Flask |
|---|---|---|
| correctly met with silence | **0.967** | **0.833** |
| English only | **0.933** | 0.667 |
| Chinese only | **1.000** | **1.000** |
| results resting on no lexical evidence, rulers A–C | **0.000** | **0.000** |

Foreign silence fell from 0.933 to 0.833 when the subject changed, and the
cause is a limit of the design rather than a defect. A word counts as evidence
unless it occurs in more than 5% of units — a stopword list derived from the
corpus, so that it needs no list and works in any language. Here `how`, `when`,
`does` and `are` are everywhere, because 304 units carry written English prose.
Across 1,572 units of mostly short, undocumented methods they occur in 1–5% of
them and start counting as evidence. Five English questions about subjects
Flask does not implement get through on exactly that.

**What each bar costs and buys** — one corpus, gate varied alone:

| gate | A hit@1/3/MRR | B hit@1/3/MRR | C hit@1/3/MRR | silence own / foreign |
|---|---|---|---|---|
| neither (pre-1.0.0) | 0.200/0.286/0.238 | 0.314/0.486/0.391 | 0.486/0.700/0.569 | 0.000 / 0.000 |
| coverage only (1.0.0) | 0.200/0.286/0.238 | 0.314/0.471/0.383 | 0.486/0.686/0.564 | 0.567 / 0.733 |
| concentration only | 0.200/0.286/0.238 | 0.314/0.471/0.383 | 0.443/0.614/0.509 | 0.967 / 0.800 |
| **both (1.1.0)** | **0.200/0.286/0.238** | **0.314/0.471/0.383** | 0.443/0.614/0.509 | **0.967 / 0.833** |

Ruler A is **unmoved by either bar**, and B by concentration. The whole cost is
three questions of seventy at hit@1 on the warmest ruler, and six at hit@3.

Through 1.3.0 this section said concentration subsumes coverage. **On a corpus
this project did not choose, it does not.** Both bars together silence 0.833 of
the foreign absent questions, against 0.800 for concentration alone and 0.733
for coverage alone. One question — and the first time in four releases that
keeping both has been worth a measurable amount rather than worth a different
diagnosis.

Raising the concentration bar buys the remaining silence, and is refused,
because it is bought out of the answers: at 0.50 the foreign absent ruler is
silent on all thirty while ruler A falls to 0.086 hit@1 from 0.200, B to 0.214
from 0.314 and C to 0.329 from 0.443. **0.28 was chosen before this corpus
existed and survived meeting it**, which is the only kind of evidence a default
can have.

**Latency** — warm corpus, 584 units `c9df00350cbd`, five consecutive
invocations of `python -m benchmarks.query_latency --repeats 10` (420 samples
each):

| | | across the five |
|---|---|---|
| query, median | **0.61 ms** | 0.60 – 0.64 |
| query, p95 | 1.09 ms | 1.06 – 1.14 |
| refusing an unanswerable query | **0.017 ms** | 0.015 – 0.019 |
| refusal cheaper than answering by | **~36×** | 33 – 41 |

Two significant figures and a spread, because that is the precision the
measurement has. Across twenty invocations over three releases on the same idle
machine the median has landed anywhere from 0.51 to 1.44 ms and p95 from 0.85
to 7.34 ms — a band wider than any change the code has ever made to this
number. Releases before 1.3.0 published `0.83 ms / p95 1.68 ms` to three
figures from a script that was never committed; both values sit inside that
band, which is the point: they were unfalsifiable rather than wrong.

Refusal is cheap for a structural reason, not a tuned one: an unanswerable
query touches only the posting lists of its own distinctive words, and never
reaches ranking at all.

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

Directional local measurements, not service levels — but every one of them is
now a command rather than a memory, which two of them were not before. Each
prints the corpus fingerprint beside its score; quote both or neither.
[`benchmarks/README.md`](benchmarks/README.md) lists the six scripts and what
each is for, and the corpus one of them grades is now carried here too.

## 7 · `rag-your-code search` vs a Grep loop

The fair baseline is not one `grep`. An agent handed Grep picks the content
words out of the question, runs one search per word, and ranks files by how
many hit. That is what this reproduces — same corpus, same questions, same
ruler, scored at **file** granularity so Grep is not penalised for lacking
declaration spans.

**Which side wins on an undescribed repository depends on the repository.**
Through 1.3.0 this section said flatly that Grep wins there, because the one
undescribed repository ever measured was a hook-heavy tool whose questions were
answerable by matching identifiers. Swapping the subject for a public web
framework reversed it. The honest claim is narrower than either table alone:

| Flask 3.1.3 · 35 questions · 1,572 units `5fd51169eacc` · no descriptions | Grep loop | rag-your-code |
|---|---|---|
| right file first | 22.9% | **37.1%** |
| right file in top 3 | 45.7% | **57.1%** |
| lines it hands back, all questions | 17,641 | — |
| characters returned, all questions | 1,415,656 | **258,236** |
| questions it answers | 30 | 30 |

**Once the vocabulary exists, it is not close.**

| this repository · 70 questions · 584 units `c9df00350cbd` · 304 described | Grep loop | rag-your-code |
|---|---|---|
| right file first | 22.9% | **58.6%** |
| right file in top 3 | 54.3% | **77.1%** |
| lines it hands back, all questions | 11,959 | — |
| characters returned, all questions | 1,135,411 | **615,673** |
| questions it answers | **61** | 60 |

Those two tables are the whole argument of section 3.3, measured against a real
baseline instead of asserted. A cold index retrieves against a sentence the
parser generated from identifiers the author already chose, plus whatever
docstrings the author wrote — so how it fares against Grep is decided by how
much prose the repository already contains. Flask has a written docstring on
most public methods, and the cold index beats Grep there without a single
description being added. On the previous subject, a tool with terse comments
and long identifiers, the same cold index lost to Grep by the same margin.

What does not depend on the subject is what descriptions buy: on this
repository first-place accuracy goes to **more than double** Grep's, and the
payload comes back ranked, spanned, and roughly half the size.

**Both tables come from `python -m benchmarks.grep_baseline`**, which is what
changed in 1.3.0. Until then this section — the strongest claim the project
makes — was published from a script that had never been committed, so nothing
here could be checked and the word "Grep loop" had no precise meaning. The
committed version defines it: take the query's words, drop the ones the corpus
itself shows are everywhere, run one substring search per remaining word over
exactly the files the index was built from, rank each file by how many distinct
words hit it, break ties on path. Reconstructing it reproduced this side's
figures exactly and moved Grep's, which is the expected shape — the ranked arm
was always a call into shipped code, and the baseline never was.

Four qualifications, because the table would otherwise flatter both sides:

- **Scored at file granularity**, which understates this side. A Grep hit is a
  file; a hit here is a declaration with an exact span, a score, and the words
  it matched on. The agent that reads the result opens 40 lines, not a file.
- **Dropping the corpus-common words is generous to Grep**, and it is what
  makes the baseline a fair one rather than a straw man: an agent that greps
  `the` gets every file back in no order. It is also why Grep declines nine of
  the seventy questions here — those had no word left that this corpus does not
  use everywhere.
- **Payload is counted in characters on both sides.** Grep hands back 18,600
  characters per question it answers here, unranked and without spans, against
  10,300 ranked and capped by `search.max_chars` — a factor of 1.8, and 5.5 on
  Flask, where a framework repeats its vocabulary across many files and Grep
  cannot rank what it finds. 1.4.1 changed what fits in that cap: the block had
  been reprinting the docstring the code below already showed, 2,381 of 3,382
  characters of prose header on Flask, so the same budget now carries **119
  declarations instead of 92** there and 323 instead of 305 here. Both sides
  decline the same five of those 35 — the five Chinese ones, all of them. A Chinese word is
  not a substring of English source and it is not a token in an index built
  from English source, so on a repository written in one language the cold
  cross-language case is not this tool's failure but the corpus's.
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

**Measured on the same four rulers, both arms against one corpus.** 1.1.0
published this comparison and read it as a win. Its largest gain was on the
foreign ruler, whose two arms turned out to have been taken against two
different states of a repository being edited while the script ran. Repeated
against a pinned corpus:

| ruler | corpus | signed hash (default) | MiniLM, local |
|---|---|---|---|
| **A** foreign, cold | 1,572 `5fd51169eacc` | **0.200 / 0.286 / 0.238** | 0.171 / 0.257 / 0.214 |
| **B** own, cold | 581 `8e1e71942c1c` | 0.314 / 0.471 / 0.383 | 0.314 / 0.471 / 0.383 |
| **C** own, described | 581 `978a1d48a82a` | **0.443 / 0.614 / 0.507** | 0.429 / 0.600 / 0.500 |
| **D** silence, own / foreign | as above | 0.967 / 0.833 | 0.967 / 0.833 |

**Worse or identical on every ruler.** The 581-unit stamps are the corpus both
arms shared, kept rather than refreshed — that is what a stamp is for. It ships
anyway because it does one thing the hash cannot and these rulers cannot see:
reach a unit sharing no word with the question. The pairs it scores zero on:

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

If you install it expecting the hit rates above to move, they will not. Install
it for the cross-language and paraphrase cases in the table above, which is
where the difference between the two columns actually lives.

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
one of them fires. That is up from ~39 in 1.1.0, and the increase is the price
of being findable — a skill fires only when a model decides it should, which
left the whole plugin with no entry point a person could discover. The commands
install the Python package on first use.

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

**The vectors are 65.3% of the index and earn ±1 question** under the default
embedder. Not removed: the same storage is what makes an optional model work,
and the schema stays one shape.

**`search.vector_recall` scans every vector per query.** Affordable at the
measured envelope, and exactly the work an ANN index would replace.

**Tree-sitter parsing and a SQLite/ANN storage layer are not here.** Both would
need a dependency, and the policy for those is settled: they follow the
embedding provider's pattern — optional, user-selected, never in the default
install. Full reasoning in [docs/ROADMAP.md](docs/ROADMAP.md).

**Whether the skill fires unprompted is not measured**, and until 1.2.1 this
project claimed no command could measure it. That was wrong: `claude plugin
eval` grades exactly this, with `tool_used: Skill` as a plugin-fired indicator
and a no-plugin baseline arm. It is unmeasured because the command is in early
access on the account here and its case schema is undocumented, so a suite
written from `--help` fragments could not be run even once to see whether it
loads — and a suite that silently fails to load reads as a gate while checking
nothing. Since 1.2.0 the four commands give an entry path that does not depend
on it.

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

- [docs/FLOW.md](docs/FLOW.md) — the whole thing in four diagrams
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — how each stage works and why
- [docs/TESTING.md](docs/TESTING.md) — what the suites protect
- [docs/ROADMAP.md](docs/ROADMAP.md) — what shipped, what was rejected and why
- [CONTRIBUTING.md](CONTRIBUTING.md) — ground rules, and how to add a language
- [CHANGELOG.md](CHANGELOG.md) — every release with its measurements

MIT licensed.
