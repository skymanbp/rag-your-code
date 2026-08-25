# RAG Your Code

**A local code-retrieval index for coding agents.** Ask a question in plain
language, get back the functions that answer it — each with its file, its exact
line range, the words that matched, and its source.

[![PyPI](https://img.shields.io/badge/PyPI-rag--your--code-blue)](https://pypi.org/project/rag-your-code/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10--3.13-blue)](pyproject.toml)

No network calls. No runtime dependencies. No model. It is built to run over a
private repository on a machine with the network switched off, and to produce
an index a human can read.

---

## The problem it solves

An agent that needs to find something in an unfamiliar codebase has two bad
options. It can grep — fast, but it only finds the string you already guessed.
Or it can read whole files into context — thorough, but a handful of them
exhausts the budget and most of what it read was irrelevant.

This sits in between. It indexes every function, method and class once, then
answers a question with the eight units most likely to be relevant, at roughly
a hundred lines instead of ten thousand. Every result carries its provenance,
so the agent can open the real code before it edits anything, and you can see
why each one came back.

It is the **R** in RAG. There is no generation here — your agent is the G.

## Install

**As a Claude Code plugin** (this is the primary way to use it):

```
/plugin marketplace add skymanbp/rag-your-code
/plugin install rag-your-code@rag-your-code
/reload-plugins
```

The plugin is one skill and nothing else — no hooks, no agents, no MCP server.
Measured with `claude plugin details`: **~39 tokens added to every session**,
and ~1.4k only when the skill actually fires. The skill installs the Python
package itself on first use.

**Or as a plain CLI:**

```bash
pip install rag-your-code

rag-your-code bootstrap .                  # index, and say what is still missing
rag-your-code search "where are HTTP retries handled" --json
rag-your-code search "what calls the retry handler" --graph --hops 1 --json
```

`bootstrap` exists because indexing a repository is not the same as making it
searchable, and nothing used to say so. A fresh index retrieves against the
sentence the parser generated, which adds no word the source did not already
have. It reports which rung this repository is on — descriptions still to
write, a promotion to apply, or nothing left — and hands over that rung's
work. It reads the state rather than remembering a position, so running it
again after each round is how you make progress. `index` still exists and does
only the indexing.

The index is written under `.rag-your-code/`; your source files are never
modified. Later runs reuse unchanged files. For a large repository, prefer
`--compact`.

## How it works

```
your repository
  → walk source files (configurable ignores, suffixes, size cap)
  → parse declarations   Python via its own AST; 14 other languages via a
                         line scanner + per-language rule table
  → one CodeUnit each    id, signature, exact line range, source, calls,
                         imports, a stable serial number, a description
  → embed description + source into a deterministic local vector
  → inverted word index + hybrid ranking
  → optional graph expansion over calls / imports / contains
  → results, or a JSON-lines protocol for an agent subprocess
```

**Parsing.** Python goes through the standard-library syntax tree, so nesting,
qualified names, call lists and line ranges are exact. Every other language
goes through three separated layers: a scanner that reads one line at a time,
a rule table per language, and a span closer that follows brace depth, Ruby's
`end`, or the next declaration. Because a pattern never sees a second line, a
reported line number *is* the scanner's loop index and cannot drift, and a
declaration cannot swallow the ones after it.

Fifteen languages: Python, JavaScript, TypeScript, Go, Rust, Java, Kotlin,
Scala, C#, C, C++, Ruby, PHP, Swift, shell.

**Graph.** `calls`, `imports` and `contains` edges, each conservative: an
unresolved or ambiguous reference produces no edge rather than a guessed one,
and every expanded result carries the exact edge path as evidence.

## What the embedding does — and what it does not

This matters more than any feature list, so it is here rather than in a
footnote.

The embedder is a **signed feature hash**: it hashes words into 384 buckets.
Cosine similarity over those vectors is therefore a normalised measure of
*shared words*, and it carries no semantics whatsoever:

| pair | cosine |
|---|---|
| `retry failed card charge` vs itself | 1.0000 |
| `sum two numbers` vs `add a pair of integers` | **0.0000** |
| `计算两个数的和` vs `sum two numbers` | **0.0000** |
| `sum two numbers` vs `delete the user database table` | 0.0000 |

A trained embedding model scores row 2 at around 0.8. Here a synonym pair and
an unrelated pair are indistinguishable, because no shared word is no shared
word either way.

Retrieval works regardless, because **the prose people write about code is
already natural language** — docstrings, comments, descriptions. Identifiers
are not part of that, and it is worth being exact: `retry_charge` tokenizes to
one opaque term, not to *retry* and *charge*. Splitting identifiers was
implemented and measured against all three rulers, with query and stored
vectors rebuilt together, and it was equal or worse on every one; the pieces it
makes are `get`, `find`, `check`, `test`, which rarity weighting immediately
discounts to nothing.

So retrieval reaches only concepts somebody wrote down. Two things close the
rest of the gap, and neither is a model:

- **Your agent rewrites the query.** It has the conversation; turning
  "重试扣款" into `retry charge payment gateway` costs it nothing.
- **Your agent writes the descriptions**, which puts the missing vocabulary
  into the index once instead of into every query.

### Seven attempts to make the vector half earn its place

Because "just use a better embedding" is the obvious next thought, it was
measured rather than argued about. Six schemes were implemented — character
n-grams, corpus co-occurrence via random indexing, truncated SVD, posting-list
signatures, a rarity- and field-weighted hash, and call-graph diffusion — plus
lexical postings expansion and embedding only the authored text. **On the
foreign-repository ruler, not one of them beat using no vector at all.**

The reason is architectural, not representational. Retrieval scores only the
units the lexical half already matched, so a vector can reorder an answer but
can never make one *retrievable*; pure cosine fires only when nothing matched
at all, on 1 question of 35. Every scheme was competing for the same one- or
two-question reshuffle inside a list that had already been chosen.

Two things follow, and both are stated here rather than buried. Corpus-learned
semantics need orders of magnitude more text than a repository has: 65% of the
foreign corpus's terms appear in four or fewer units, so their co-occurrence
row is a handful of sightings rather than a distribution. And on a *described*
repository the shipped hash is useful precisely because it is blunt — every
scheme that sharpened it lost ground there.

## Agent-authored descriptions

Every unit carries a description, and that description is indexed. By default
it is generated without a model: the identifier humanised, the parameters and
callees listed, the docstring appended. It introduces no vocabulary the source
did not already have — which is exactly why retrieval cannot reach a concept
nobody wrote down.

**First, the documentation you already wrote is indexed.** Fourteen of the
fifteen supported languages put documentation immediately above a declaration
— JSDoc, Javadoc, KDoc, rustdoc, Go doc comments, XML doc comments, PHPDoc —
and a unit's span begins at the declaration, so all of it used to sit outside
the index. The same sentence reached thirteen searchable words as a Python
docstring and two as a JavaScript comment. Now both reach thirteen. Commented-
out code, separator rules and licence headers are deliberately left out.

**Where there is none, the agent can write it:**

```bash
rag-your-code describe status              # coverage, and what is pending
rag-your-code describe export --limit 20   # a batch, with source and a brief
rag-your-code describe import written.json # store what the agent wrote
rag-your-code index .                      # apply it
```

or, in the protocol, `describe_pending` and `describe_put` — which take effect
in the same session, with no refresh.

**And you can move it into the code**, where it needs no bookkeeping at all:

```bash
rag-your-code describe promote | git apply    # review it first
```

That emits a unified diff adding a doc comment in each language's own
convention, for declarations that have none. The tool still never writes your
source. Only the half meant for a reader is promoted, so a bilingual
description leaves its second language in the store where retrieval still uses
it — measured, promoting all 68 on this repository discarded no description
and left Chinese retrieval unchanged.

### Measured on this repository

This project describes its own implementation: all 163 units under `src/` carry
an agent-written bilingual description, committed to the repo, and 155 of those
163 declarations also carry the author's own documentation in the source.

Seventy natural-language questions about this codebase, in English and
Chinese, each listing every unit that genuinely answers it
([`benchmarks/repo_queries.json`](benchmarks/repo_queries.json)):

| | generated descriptions | agent-written |
|---|---|---|
| hit@1 | 0.314 | **0.500** |
| hit@3 | 0.457 | **0.729** |
| MRR | 0.379 | **0.583** |
| questions declined for want of evidence | 13.0% | **4.3%** |

Half again the first-place accuracy. Nineteen questions still fail, which is
what makes the set usable for measuring the next change;
`tests/test_repo_queries.py` asserts that some question always does, and that
the written column beats the generated one.

One failure is worth naming: a query saying `catastrophic backtracking` does
not reach a description saying `backtracks catastrophically`. There is no
stemming — exactly the limit documented above.

### Measured on a repository nobody here wrote

The table above is the warmest case this project supports: its own code, its
own descriptions, and questions written by the same party. It cannot say what
a first-time user gets. So there is a second ruler — thirty-five questions
about [cc-enforcer](https://github.com/skymanbp/cc-enforcer), 1153 units, no
descriptions at all, each question phrased in a user's words rather than in
the words of the docstring that answers it
([`benchmarks/cold_queries.json`](benchmarks/cold_queries.json)):

| | before 0.6.0 | now |
|---|---|---|
| hit@1 | 0.086 | **0.257** |
| hit@3 | 0.229 | **0.400** |
| MRR | 0.157 | **0.314** |

Three times the first-place accuracy, and the same change moved both other
rulers in the same direction. What it fixed was ranking: scoring used to be
the fraction of query words a unit contained, so `the` counted for as much as
`daemon`, and nothing corrected for size — the single largest declaration in
that repository came back in the top three for four questions out of six. It
is now BM25 over weighted fields, where a word's worth comes from how rare it
is in *your* corpus and a word in a declaration's name outweighs the same word
buried in a body.

Twenty-one of the thirty-five still fail, and the largest remaining cause is
named in [docs/TESTING.md](docs/TESTING.md): a test declaration often outranks
the code it tests, because it repeats that code's vocabulary and adds its own.

**What this is:** it moves the semantic work from query time to index time.
Matching stays lexical. It is LLM-authored keyword expansion, and its reach is
bounded by how many ways of saying the thing the agent thought to write down.

### The question a ranking cannot answer

Both rulers above ask questions that *have* an answer, so both can only score
whether it was found. Neither can see the opposite failure. A ranking always
produces a least-bad unit and hands it back with a score and a rank that read
exactly like an answer — and it does that whether or not the repository
contains anything relevant at all.

So there is a third ruler: thirty questions about subjects neither repository
implements, where the only correct reply is nothing
([`benchmarks/absent_queries.json`](benchmarks/absent_queries.json)). Before
1.0.0 it scored **zero**. All thirty answered, on both repositories, in both
languages:

| asked of a repository with no such code | answered with | on the evidence of |
|---|---|---|
| `where are CUDA kernels dispatched to the device` | a test about word counting | `are` `the` `to` `where` |
| `准入控制为什么会拒绝没有资源限额的容器组` | the UTF-8 console setup | `拒绝` `控制` `没有` |
| `how is the OAuth refresh token rotated` | a description-store method | `before` `is` `refresh` `the` |

Not a Chinese problem and not a ranking problem — a missing question. Nothing
in the pipeline asked *is any of this evidence*; it only asked which ranks
highest. Retrieval now asks both, and returns nothing when the answer to the
first is no:

| | before | now |
|---|---|---|
| unanswerable questions correctly met with silence, this repository | 0.000 | **0.733** |
| the same, on the foreign repository | 0.000 | **0.800** |
| results resting on no lexical evidence at all, all three rulers | 0.029 – 0.129 | **0.000** |
| hit@1 / hit@3 / MRR on the foreign ruler | 0.257 / 0.400 / 0.314 | **unchanged** |
| hit@1 / hit@3 / MRR on this repository | 0.471 / 0.686 / 0.557 | **unchanged** |

The bar is the share of a question's **discriminating** words that occur in
the index — words the repository uses everywhere are dropped from both sides
of that fraction, which is the part that does the work. Half of `where are
CUDA kernels dispatched to the device` matches, and it looks like evidence
until you notice which half. Counting only words that distinguish silenced 18
of 30 unanswerable English questions that no plain coverage threshold reached
at all, at identical cost in real answers — 97 of 98 either way.

It is a ratio inside the query rather than a threshold on a score, because a
score threshold is tied to whatever scale the ranking currently produces —
this project has already had one of those stop meaning anything the moment
BM25F changed the scale. `search.min_coverage` sets it; `0` restores the old
behaviour exactly.

**What it costs:** one question of the 158 measured. `控制台编码不是 UTF-8
会怎么样` was reaching `_use_utf8_streams`, and the only words in it this
repository contains are `utf` and `8`, both of which it uses everywhere. The
gate says too little of that question is distinctive, which is defensible, and
it was getting the right answer on a coincidence.

**What it does not fix:** an English question whose words genuinely occur here
in another sense. `how is the OAuth refresh token rotated` matches `refresh`
because this repository refreshes *indexes*, and no threshold separates those.
Six of fifteen English absent questions still get answered for that reason.
That is the case a real embedding model exists for, and it is measurable now
that the ruler exists.

An empty answer says which kind of empty it is, because each is recovered by a
different move:

```json
{"results": [],
 "diagnosis": {"reason": "only_ubiquitous_terms_matched",
               "matched_terms": [], "ubiquitous_terms": ["the", "to"],
               "coverage": 0.0, "min_coverage": 0.4,
               "hint": "The only words that matched are ones this repository uses throughout ..."}}
```

Descriptions live in `rag-your-code.descriptions.json` at the repository root
and are meant to be committed, so one person's pass benefits everyone who
clones. Each is keyed by unit id **and a digest of the unit's source**: when
the code changes, the description is not applied, the unit returns to the
pending queue, and retrieval falls back to the generated sentence. A
description that outlived its code would be a confident wrong answer, which is
the one thing this index is built not to give. When code merely *moves* — an
import added above it — the description follows it by digest.

## Measured

**Parsing**, against source-controlled fixtures in `tests/fixtures/languages/`
(15 fixture files, 96 expected units, 237 negative cases, 89 constructs the
spec deliberately excludes):

| | |
|---|---|
| core declarations found | **91 / 91** |
| with the correct `start_line` | **91 / 91** |
| with a usable signature | **91 / 91** |
| units that do not exist | **0** |

A 441-byte JavaScript file that once took **12.6 s** to parse now takes
**0.36 ms**, and 10 KB takes 2.1 ms — growth is linear again.

**Scale**, on a synthetic 10,000-unit repository (500 files):

| | |
|---|---|
| full build | 1.84 s |
| incremental rebuild after one file changes | 0.207 s (**8.9x**) |
| compact storage vs readable JSON | 35.6% |
| index load, in a fresh process | 45.4 ms |
| inverted index build | 117.7 ms |
| resident memory | 58.7 MiB |
| query, mean of 200 warmed samples | 3.90 ms |

Directional local measurements, not service levels; the archived run is
[`large-benchmark-result.json`](large-benchmark-result.json).

**Suite:** Python 3.10 – 3.13 on Linux and Windows, plus a job that installs
the built wheel into a clean environment and runs every command the
documentation prescribes, and another that runs the skill's own install line
verbatim. 248 tests as of 0.5.0 — the count is version-stamped rather than
maintained, because a bare figure in a living document is a claim that rots;
per-release counts are in [CHANGELOG.md](CHANGELOG.md).

## Configuration

21 settings in `rag-your-code.toml` at the repository root:

```bash
rag-your-code config init                     # a commented file, all defaults
rag-your-code config list                     # effective values and their source
rag-your-code config set index.ignore '["vendor", "generated"]'
rag-your-code config set search.min_coverage 0.25
```

| section | settings |
|---|---|
| `[index]` | `ignore`, `suffixes`, `max_file_bytes` |
| `[embedding]` | `dimensions`, `provider`, `endpoint`, `model`, `api_key_env`, `batch`, `timeout`, `retries` |
| `[search]` | `min_coverage`, `vector_weight`, `vector_recall`, `limit`, `max_chars` |
| `[agent]` | `max_open_bytes`, `max_open_chars` |
| `[describe]` | `languages`, `batch`, `max_chars` |

This table is asserted against the settings table in `config.py`, in both
directions, by `tests/test_metadata.py` — it had already fallen nine settings
behind by 1.0.0, and a section listing three quarters of what exists is worse
than none, because it reads as complete.

Resolution is CLI flag > file > built-in default. There is no environment
layer: an index is an artifact of a repository, not of a shell.

An unknown key or an out-of-range value is an error, not a shrug — a setting
silently dropped is indistinguishable from one that had no effect.
`index.suffixes` may only name suffixes the parser has rules for, because a
suffix it cannot read is walked, parsed to nothing, and reported as a clean
index of zero units.

The settings under `[index]` and `[embedding]` that decide what an index
*contains* — including which provider and model computed its vectors — have a
digest stored in the index, and changing one forces a full rebuild. The rest
take effect immediately and invalidate nothing.

## Agent protocol

`rag-your-code agent --root PATH` reads one JSON request per line and writes
one reply per line:

```json
{"action":"bootstrap"}
{"action":"search","query":"database transaction rollback","limit":5}
{"action":"research","query":"trace payment retry behavior","max_steps":2}
{"action":"neighbors","id":"payments.py:4:retry_charge","hops":1}
{"action":"open","path":"payments.py","start_line":1,"end_line":80}
{"action":"describe_pending","limit":20}
{"action":"describe_put","descriptions":[{"id":"payments.py:4:retry_charge","text":"..."}]}
{"action":"refresh"}
{"action":"stats"}
```

**A result is navigation, not the file.** `results` carries the identifier,
path, line range, signature, description, score and matched terms. The code
arrives once, in the reply's `context`, trimmed to `max_chars`, and
`omitted_for_budget` says how many results it did not reach. Carrying the
source per result as well is what let one `search --json` reply reach 65,025
characters against a stated budget of 12,000, and one `research` reply reach
111,843 by serialising the same eight units three times over.

**No single request can end the session.** Numeric fields saturate at their
bounds, `open` is bounded in both lines and bytes, and anything unanticipated
is reported in-band with its exception type. Streams are pinned to UTF-8
rather than following the console codepage.

`research` is a deliberately bounded two-step controller: retrieve, then at
most one graph expansion when confidence is low, reporting each step and why
it stopped.

## What lives where

| path | authored or generated | commit it? |
|---|---|---|
| `rag-your-code.toml` | authored | yes |
| `rag-your-code.descriptions.json` | authored by your agent | yes |
| `.rag-your-code/` (index, vectors, annotations) | generated | no |

Nothing authored lives under `.rag-your-code/` — that directory is what people
delete to clear the cache.

## Bringing your own model

Everything above works with no model at all. If you would rather have real
semantics, point the index at any OpenAI-compatible embeddings endpoint —
which includes a model server on your own machine:

```toml
# rag-your-code.toml
[embedding]
provider   = "openai-compatible"
endpoint   = "http://localhost:11434/v1/embeddings"   # ollama, LM Studio, vLLM…
model      = "nomic-embed-text"
dimensions = 768                                      # must match the model
```

A hosted service is the same three lines with an `https://` endpoint, plus the
name of the environment variable holding your key:

```toml
api_key_env = "OPENAI_API_KEY"    # the NAME of the variable, never the key
```

**The key is never a setting.** `rag-your-code.toml` is meant to be committed
so everyone who clones can see what shaped the index; a credential is the one
value with the opposite requirement, so the file only ever names the variable
it lives in. Sending a key over plain `http://` to anything but your own
machine is refused rather than warned about.

Three things follow from turning this on, and it is worth knowing all three
before you do:

- **Your source leaves the machine**, unless the endpoint is local. That is
  the whole reason the local case is written first here.
- **Similarity may now find things, not just order them.** With the local
  hash a cosine shortlist is measurably noise, so it is confined to
  re-ranking. A real model earns the right to add candidates the words never
  reached, which is the one gap no amount of ranking closes:
  `search.vector_recall` sets how many. Lexical evidence still dominates — a
  unit found by similarity alone scores at most `search.vector_weight`.
- **A failure stops the build.** Falling back to the local hash would leave an
  index whose vectors come from two incompatible spaces, and ranking would act
  on the meaningless cosine between them with full confidence.

Switching provider, model or width discards the old vectors and rebuilds, so
an index can never be a mixture. An incremental run over unchanged files makes
no request at all.

**What is not measured:** whether this helps *your* repository, and by how
much. No number here is from a real model — this project has no key, and a
figure produced by a stub would be fiction. The instrument ships instead:
point `benchmarks/repo_queries.py --index` at your own index and grade it. You
will probably also want a higher `search.vector_weight` than the 0.15 tuned
for a hash that carries no meaning.

## Still not here

Tree-sitter parsing, and a SQLite/ANN storage layer for repositories past the
measured JSON envelope. Note also that `search.vector_recall` scans every
unit's vector on every query, which is fine at the measured envelope and is
the thing an ANN index would replace. See [docs/ROADMAP.md](docs/ROADMAP.md).

## Development

```bash
python -m pip install -e ".[dev]"
pytest -q
```

No runtime dependencies; `pytest` and, below Python 3.11, `tomli` come from the
`dev` extra.

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — how each stage works and why
- [docs/TESTING.md](docs/TESTING.md) — what the suites are protecting
- [docs/ROADMAP.md](docs/ROADMAP.md) — what shipped, what is still open
- [CONTRIBUTING.md](CONTRIBUTING.md) — ground rules, and how to add a language
- [CHANGELOG.md](CHANGELOG.md) — every release, with its measurements

MIT licensed.
