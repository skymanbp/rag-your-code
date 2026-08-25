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

rag-your-code index .
rag-your-code search "where are HTTP retries handled" --json
rag-your-code search "what calls the retry handler" --graph --hops 1 --json
```

The index is written under `.rag-your-code/`; your source files are never
modified. Later `index` runs reuse unchanged files. For a large repository,
prefer `rag-your-code index . --compact`.

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

Retrieval works regardless, because **identifiers and docstrings are already
natural language** — `retry_charge` contains *retry* and *charge*. But it
reaches only concepts somebody wrote down. Two things close the rest of the
gap, and neither is a model:

- **Your agent rewrites the query.** It has the conversation; turning
  "重试扣款" into `retry charge payment gateway` costs it nothing.
- **Your agent writes the descriptions**, which puts the missing vocabulary
  into the index once instead of into every query.

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

This project describes its own implementation: every unit under `src/` carries
an agent-written bilingual description, committed to the repo, and 68 of them
have been promoted into the source as doc comments.

Seventy natural-language questions about this codebase, in English and
Chinese, each listing every unit that genuinely answers it
([`benchmarks/repo_queries.json`](benchmarks/repo_queries.json)):

| | generated descriptions | agent-written |
|---|---|---|
| hit@1 | 0.271 | **0.500** |
| hit@3 | 0.486 | **0.800** |
| MRR | 0.367 | **0.631** |
| answered with no shared word at all | 12.9% | **0%** |

Roughly double the first-place accuracy. Fourteen questions still fail, which
is what makes the set usable for measuring the next change;
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

Twelve settings in `rag-your-code.toml` at the repository root:

```bash
rag-your-code config init                     # a commented file, all defaults
rag-your-code config list                     # effective values and their source
rag-your-code config set index.ignore '["vendor", "generated"]'
rag-your-code config set search.vector_weight 0.25
```

| section | settings |
|---|---|
| `[index]` | `ignore`, `suffixes`, `max_file_bytes` |
| `[embedding]` | `dimensions` |
| `[search]` | `vector_weight`, `limit`, `max_chars` |
| `[agent]` | `max_open_bytes`, `max_open_chars` |
| `[describe]` | `languages`, `batch`, `max_chars` |

Resolution is CLI flag > file > built-in default. There is no environment
layer: an index is an artifact of a repository, not of a shell.

An unknown key or an out-of-range value is an error, not a shrug — a setting
silently dropped is indistinguishable from one that had no effect.
`index.suffixes` may only name suffixes the parser has rules for, because a
suffix it cannot read is walked, parsed to nothing, and reported as a clean
index of zero units.

The four settings under `[index]` and `[embedding]` decide what an index
*contains*, so a digest of them is stored in the index and a change forces a
full rebuild. The rest take effect immediately and invalidate nothing.

## Agent protocol

`rag-your-code agent --root PATH` reads one JSON request per line and writes
one reply per line:

```json
{"action":"search","query":"database transaction rollback","limit":5}
{"action":"research","query":"trace payment retry behavior","max_steps":2}
{"action":"neighbors","id":"payments.py:4:retry_charge","hops":1}
{"action":"open","path":"payments.py","start_line":1,"end_line":80}
{"action":"describe_pending","limit":20}
{"action":"describe_put","descriptions":[{"id":"payments.py:4:retry_charge","text":"..."}]}
{"action":"refresh"}
{"action":"stats"}
```

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

## Not here yet

Provider-backed embeddings, Tree-sitter parsing, and a SQLite/ANN storage layer
for repositories past the measured JSON envelope. Agent-authored descriptions
are deliberately the cheaper answer to the same problem provider embeddings
solve: they keep the zero-dependency, offline, reproducible-index properties,
and produce text a human can read and correct rather than opaque floats. See
[docs/ROADMAP.md](docs/ROADMAP.md).

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
