# RAG Your Code

`rag-your-code` is the **R** in RAG: a local, explainable retrieval index over a
codebase. The generation half stays in your agent. It scans functions, methods
and classes across Python and fourteen other languages, assigns stable serial
numbers, and answers queries with a file, a line range, the terms that matched,
and the source itself.

No network calls and no runtime dependencies, by design rather than by
omission — it is meant to run over a private repository on a machine with the
network turned off, and to produce an index you can read.

## What the embedding does, and what it does not

This matters more than any feature list, so it is stated up front rather than
in a footnote.

The embedder is a **signed feature hash**: it hashes tokens into 384 buckets.
Cosine similarity over those vectors is therefore a normalised measure of
*token overlap*, and it carries no semantics whatever:

| pair | cosine |
|---|---|
| `retry failed card charge` vs itself | 1.0000 |
| `sum two numbers` vs `add a pair of integers` | **0.0000** |
| `计算两个数的和` vs `sum two numbers` | **0.0000** |
| `sum two numbers` vs `delete the user database table` | 0.0000 |

A trained embedding model scores row 2 around 0.8. Here a synonym pair and an
unrelated pair are indistinguishable, because zero shared tokens is zero either
way.

Retrieval works anyway, because **identifiers and docstrings are already
natural language**: `retry_charge` contains the words *retry* and *charge*. But
it reaches only concepts someone wrote down. Two mechanisms close the rest of
the gap, and neither of them is a model:

- **Your agent rewrites the query.** It has the conversation; turning "重试扣款"
  into `retry charge payment gateway` costs it nothing.
- **Your agent writes the descriptions** (see below), which puts the missing
  vocabulary into the index once instead of into every query.

## Quick start

```bash
# Not on PyPI. Take the wheel from the latest release, or install the source:
#   https://github.com/skymanbp/rag-your-code/releases
pip install ./rag_your_code-0.4.0-py3-none-any.whl
#   ... or, from a clone:  python -m pip install -e .

rag-your-code index .
rag-your-code search "where are HTTP retries handled" --json
rag-your-code search "what calls the retry handler" --graph --hops 1 --json
rag-your-code annotate
```

The index and annotations are written under `.rag-your-code/`; source files are
never modified. Use `--json` when feeding results to an agent.

For a large repository prefer `rag-your-code index . --compact`. Later
`index` runs and the agent's `refresh` reuse unchanged files and preserve
global serials; `--full` discards the cache.

## Agent-authored descriptions

Every unit carries a description, and that description is indexed. By default
it is generated without a model: the identifier humanised, the parameter and
callee names listed, the docstring appended. That introduces no vocabulary the
source did not already contain, which is exactly why retrieval cannot reach a
concept nobody wrote down.

The agent already reading this index can supply those words:

```bash
rag-your-code describe status                 # coverage, and what is pending
rag-your-code describe export --limit 20      # a batch, with source and a brief
rag-your-code describe import written.json    # store what the agent wrote
rag-your-code index .                         # apply it
```

or, in the JSON-lines protocol, `describe_pending` and `describe_put` — which
take effect in the same session, without a refresh.

Measured on the fixture repository, replacing one generated sentence with an
agent-written bilingual one:

| query | generated description | agent description |
|---|---|---|
| `exponential backoff` | no lexical evidence | **#1**, 1.0172 |
| `double billing safety` | no lexical evidence | **#1**, 0.3404 |
| `支付网关超时` | no lexical evidence | **#1**, 0.8632 |

**What this is:** it moves the semantic work from query time to index time.
Matching stays lexical — a description saying `retry` still cannot answer a
query saying `resend` unless the description also says so. It is LLM-authored
keyword expansion, and its reach is bounded by how many ways of saying the
thing the agent thought to write down.

Descriptions live in `rag-your-code.descriptions.json` at the repository root
and are meant to be committed, so one person's pass benefits everyone who
clones. Each is keyed by unit id **and a digest of the unit's source**: when
the code changes the description is not applied, the unit returns to the
pending queue, and retrieval falls back to the generated sentence. A
description that outlived its code would be a confident wrong answer, which is
the one thing this index is built not to give.

## Configuration

Twelve settings live in `rag-your-code.toml` at the repository root:

```bash
rag-your-code config init                       # a commented file, all defaults
rag-your-code config list                       # effective values and their source
rag-your-code config set index.ignore '["vendor", "generated"]'
rag-your-code config set search.vector_weight 0.25
```

Resolution is CLI flag > file > built-in default. There is no environment
layer: an index is an artifact of a repository, not of a shell.

| section | settings |
|---|---|
| `[index]` | `ignore`, `suffixes`, `max_file_bytes` |
| `[embedding]` | `dimensions` |
| `[search]` | `vector_weight`, `limit`, `max_chars` |
| `[agent]` | `max_open_bytes`, `max_open_chars` |
| `[describe]` | `languages`, `batch`, `max_chars` |

An unknown key or an out-of-range value is an error, not a shrug — a setting
that is silently dropped is indistinguishable from one that had no effect.
`index.suffixes` may only name suffixes the parser has rules for, because a
suffix it cannot read is walked, parsed to nothing, and reported as a clean
index of zero units.

The four settings under `[index]` and `[embedding]` determine what an index
*contains*, so a digest of them is recorded in the index and a change forces a
full rebuild. The rest take effect immediately and never invalidate anything.

## Agent protocol

`rag-your-code agent --root PATH` reads JSON lines from stdin and writes JSON
lines to stdout:

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

No single request can end the session: numeric fields saturate at their bounds,
`open` is bounded in both lines and bytes, and anything unanticipated is
reported in-band with its exception type. Streams are pinned to UTF-8 rather
than following the OS codepage.

The bundled Claude plugin skill documents the recommended workflow: index at
session start, retrieve narrowly, inspect returned source, describe what is
pending, and re-index after substantial changes.

## Design notes

- Python uses the standard-library AST, so nested functions, methods, calls,
  imports, signatures and source line ranges are precise.
- Other languages use a line-oriented declaration scanner: a per-language rule
  table matched one line at a time, then a span closer (brace balance, Ruby's
  `end`, or the next declaration). Because a pattern never sees a second line,
  the reported line number is the scanner's own loop index and cannot drift,
  and a declaration cannot swallow the ones after it. Fourteen languages are
  covered and graded against source-controlled fixtures in
  `tests/fixtures/languages/`; `SPEC.md` there states what counts as a unit.
- Retrieval combines lexical overlap and cosine similarity. Every result is
  explainable: you can read why it matched.
- Schema 2 supports incremental per-file reuse, repository-global serials,
  graph edges, and optional compact float32 vector storage (`index --compact`).
- GRAG expands bounded `calls`/`imports`/`contains` neighbours with edge-path
  evidence, and omits an edge it cannot resolve rather than guessing one. ARAG
  exposes bounded, observable `research`, `neighbors`, `open` and `refresh`.
- The generated `RAG[00001] ...` comments live in a sidecar Markdown file,
  which avoids rewriting your code while preserving the numbered layer that
  gets embedded.

## What lives where

| path | authored or generated | committed |
|---|---|---|
| `rag-your-code.toml` | authored | yes |
| `rag-your-code.descriptions.json` | authored by your agent | yes |
| `.rag-your-code/` (index, vectors, annotations) | generated | no |

Nothing authored lives under `.rag-your-code/`: that directory is what people
delete to clear the cache.

## Development

```bash
python -m pip install -e ".[dev]"
pytest -q
```

No runtime dependencies; `pytest` and, below Python 3.11, `tomli` come from the
`dev` extra. CI covers Python 3.10 through 3.13 on Linux and Windows and
installs the built wheel into a clean environment to check that the workflow
the bundled skill documents actually runs from a published artifact. See
[CONTRIBUTING.md](CONTRIBUTING.md) for what the golden set and the language
fixtures are protecting, and [docs/ROADMAP.md](docs/ROADMAP.md) for what is
deliberately not here yet.
