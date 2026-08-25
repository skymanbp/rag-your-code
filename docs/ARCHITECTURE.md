# RAG Your Code architecture

## Goal

Turn a repository into a searchable layer that a coding agent can use before it
edits code. That layer must be inspectable: every result points to a real file
and line range, includes source, and explains why the unit was indexed.

## What this is, precisely

It is the retrieval half of RAG. There is no generation here and no model
anywhere in the process — the agent calling it supplies both.

That framing is load-bearing, because the embedder is a **signed feature hash**
and cosine over it is a normalised measure of *token overlap*, not of meaning:

| pair | cosine |
|---|---|
| `retry failed card charge` vs itself | 1.0000 |
| `sum two numbers` vs `add a pair of integers` | **0.0000** |
| `计算两个数的和` vs `sum two numbers` | **0.0000** |
| `sum two numbers` vs `delete the user database table` | 0.0000 |

A trained embedding model scores row 2 around 0.8. Here the synonym pair and
the unrelated pair are indistinguishable, because no shared token is no shared
token. What makes retrieval work regardless is that the prose people write
about code — docstrings, comments, descriptions — is already natural language.

Identifiers are *not* part of that, and it is worth being exact about it.
`retry_charge` tokenizes to one opaque term, not to `retry` and `charge`; so
does `TestRetryCharge`, and so does `_find_hardcoded_secret`. Splitting them
was implemented and measured against all three rulers, with the query and the
stored vectors rebuilt together so the comparison was not confounded, and it
was **equal or worse on every one**: the pieces it produces are `get`, `find`,
`check`, `test`, `handler`, which are exactly the words rarity weighting then
discounts to nothing, while the exact-identifier signal is diluted among them.
The words already reach retrieval through docstrings and through the
humanised name in the generated description.

What none of this can do is reach a concept nobody wrote down — which is what
agent-authored descriptions exist to fix, and why they are described below as
keyword expansion rather than as semantics.

### Seven schemes measured, none adopted

Six replacement embeddings were implemented and measured on all three rulers --
character n-grams, corpus co-occurrence via random indexing, truncated SVD by
power iteration, posting-list signatures, a rarity- and field-weighted hash,
and call-graph diffusion -- along with two changes that were not embeddings at
all: expanding a unit's lexical postings with its graph neighbours' terms, and
embedding only the authored fields. On the foreign-repository ruler, hit@3
never once exceeded its no-vector value of 0.429.

The binding constraint is not the representation. `candidate_ids =
lexical_scores.keys()` -- a vector reorders what the lexical half already
found and cannot make anything retrievable, and pure cosine fires only when
nothing matched at all, on 1 question of 35. Postings expansion, the one
change that *could* alter retrievability, was measured worse at every sharing
weight tried (hit@1 0.257 to 0.171 to 0.114 to 0.086) because borrowed
vocabulary makes every neighbour match every neighbour's question.

Two mechanism-level results are worth keeping. Corpus-learned semantics need
orders of magnitude more text than a repository has: 65% of the foreign
corpus's 6000 terms appear in four or fewer units, so a co-occurrence row is a
handful of sightings rather than a distribution. And on a described corpus the
shipped hash helps *because* it is blunt -- mean cosine between random unit
pairs is around 0.38, an undifferentiated echo of description words -- so
every scheme that sharpened it lost ground there.

### What the vector is actually contributing

`vector[bucket(term)] += sign` accumulates a term frequency, and the vector is
then divided by its own magnitude. So the cosine is term frequency with length
normalisation — the two things the old lexical score lacked — delivered
through 384 lossy buckets. That is why switching it off used to cost 0.114 of
hit@1, and why, once BM25 did those two things properly, the same ablation
costs **nothing at all on a foreign repository** and one question of seventy
on this one. It carries no semantics and never did.

## Current end-to-end path

```text
rag-your-code.toml  ----------------.
                                     v
repository
  -> deterministic file walker (configured ignores, suffixes, size cap)
  -> language parser (Python AST; line scanner + rule table for 14 others)
  -> CodeUnit records (stable id, serial, signature, calls, imports, lines)
  -> descriptive text: generated, or authored by an agent  <--- descriptions.json
  -> local deterministic embedding + JSON/float32 persistence
  -> inverted lexical index + hybrid vector retrieval
  -> bounded calls/imports/contains graph expansion (GRAG)
  -> bounded research/open/neighbors/describe/refresh actions (ARAG)
  -> context or JSON-lines response for an agent
```

`CodeUnit` is the contract between all stages. The index never mutates source
files; annotations go to `.rag-your-code/annotations.md` so a user can review,
commit, or discard them independently.

Two inputs are **authored** and belong in version control —
`rag-your-code.toml` and `rag-your-code.descriptions.json`, both at the
repository root. Everything under `.rag-your-code/` is generated and
disposable. The split is deliberate: that directory is what a person deletes to
clear the cache, and authored work must survive it.

## Why the embedder is local

It is deterministic, offline and dependency-free. That gives a reproducible
baseline for a private repository and makes tests exact. It is also an adapter
boundary: a provider can implement `embed(text)` and keep the same records,
persistence and retrieval API.

Agent-authored descriptions are deliberately the cheaper answer to the same
problem a provider embedder would solve. They keep `dependencies = []`, keep
source on the machine, need no API key, and produce output a human can read and
correct instead of opaque floats.

## Parsing

Python goes through the standard-library AST. Every other language goes through
three separated layers:

```text
Layer 1  line scanner    one match attempt per line; the line number IS the
                         loop index, so it cannot drift
Layer 2  rule table      per-language declaration patterns, each anchored
                         inside a single line
Layer 3  span closer     brace balance, or Ruby's `end`, or the next declaration
```

The separation is what fixes things, not the individual patterns. One whole-file
regex previously did all three jobs at once and the coupling produced three
defects at once: catastrophic backtracking (a 530-byte `.js` file took 12.6 s,
growing as roughly n^4.3), an `[^;]*` that consumed newlines and swallowed every
declaration up to the last `)` in a file, and a leading `\s*` that began matches
on preceding blank lines so 9 line numbers in 10 were wrong and the signature was
the blank line. A pattern that cannot see a second line cannot consume one, and
the same rewrite closed all three. Measured after: the same 530-byte file parses
in 0.37 ms and a 10 KB one in 1.40 ms, so growth is linear.

Adding a language is adding rows to the rule table; the scanner does not change.
What counts as a unit is stated once in `tests/fixtures/languages/SPEC.md` -- a
named declaration that owns a body span -- which matches what the Python path
already emits. Layer 3 answers that question too: a declaration reaching `;`
before `{` owns nothing, which is how prototypes, trait and interface method
signatures, Swift protocol requirements and Rust unit structs stay out.

Documentation written immediately above a declaration is collected and
appended to the unit's description, in the same phrasing the Python path uses
for a docstring. Fourteen of the fifteen languages document that way, and a
unit's span begins at the declaration, so all of it previously sat outside the
indexed text: the same sentence reached thirteen searchable words as a Python
docstring and two as a JavaScript comment. Adjacency is required so a licence
header separated by a blank line is not read as documentation of the first
declaration, annotation lines are stepped over because `@Override` between
Javadoc and its method is the normal Java shape, and lines that end in `;`,
`{` or `}` are dropped as commented-out code. `,` and `)` were on that list
until a measurement showed them rejecting the first line of an ordinary JSDoc
block: prose wraps on a comma far more often than code ends on one.

The parser is also an input the index records. Cached units are a function of
a file's bytes *and* of the code that parsed them, but reuse was keyed on the
bytes alone, so upgrading the parser left every unchanged file carrying units
the old one produced until that file happened to change. That was the third
such input after the settings and the descriptions, and since all three mean
the same thing and call for the same action they are one field: a
`build_fingerprint` over the build settings and a digest of the parser's own
source. Digesting the source rather than declaring a version number costs one
rebuild for a comment-only edit and removes the possibility of a forgotten
bump.

The parser's dispatch table is also the source of truth for which suffixes the
walker accepts. They were separate lists agreeing by coincidence, and a suffix
on only the walker's list produced a file that was read, parsed to nothing, and
reported as a clean index of zero units.

## Configuration

Twelve settings live in one table in `config.py`. The loader, the validator,
the fingerprint, the `config` subcommand and the generated template all read
that table, so a value is named, defaulted, bounded and classified exactly
once. Resolution is CLI flag > `rag-your-code.toml` > built-in default.

There is deliberately no environment-variable layer. An index is an artifact of
a repository, not of a shell, and a setting that changes what gets indexed has
to be visible to everyone who clones it.

An unknown key or an out-of-range value raises rather than being dropped: a
setting silently ignored is indistinguishable, from outside, from one that had
no effect, so the user cannot tell a typo from a misunderstanding.

Four of the twelve — `index.ignore`, `index.suffixes`, `index.max_file_bytes`
and `embedding.dimensions` — decide what an index *contains*. A digest of just
those is written into the index, and a mismatch forces a full rebuild rather
than reuse; reuse is keyed on file content, which cannot notice that the rules
changed. The `embedding.dimensions` case in particular used to fail in silence,
because `search` skips the cosine term when vector widths disagree instead of
raising, so the only symptom was quietly worse ranking. The remaining eight
settings take effect immediately and never invalidate an index.

`tomllib` is standard library from 3.11. Below that, a subset reader in
`config.py` covers what the settings table can express and refuses everything
else with a line number; a differential test checks it against `tomllib` on
every version that ships one. The alternative was a `tomli` runtime dependency,
which would falsify what this project claims about having none.

## Descriptions

Every unit carries a description and that description is part of
`searchable_text`, so its words reach both the inverted index and the vector.
By default it is generated without a model — identifier humanised, parameter
and callee names listed, docstring appended — which introduces no vocabulary
the source did not already contain.

An agent can replace it. `describe_pending` hands out a batch with each unit's
source and a brief; `describe_put` takes descriptions back, validates them, and
applies them to the live units immediately so the same session retrieves on the
new words. The `describe` subcommand offers the same round trip for hosts not
speaking the protocol.

Measured on the fixture repository, one generated sentence replaced by an
agent-written bilingual one:

| query | generated | authored |
|---|---|---|
| `exponential backoff` | no lexical evidence | #1, 1.0172 |
| `double billing safety` | no lexical evidence | #1, 0.3404 |
| `支付网关超时` | no lexical evidence | #1, 0.8632 |

**This is not semantic generalisation.** Matching stays lexical; it moves the
semantic work from query time to index time, and its reach is bounded by how
many ways of saying the thing the agent wrote down. That is what the brief
handed out with each batch asks for, and it is why the default asks for two
languages: the tokenizer emits CJK bigrams, so a Chinese query can only reach a
unit whose indexed text contains Chinese.

Each entry is keyed by unit id **and a digest of the unit's code**. When the
code changes the entry is retained but not applied, the unit returns to the
pending queue, and retrieval falls back to the generated sentence. A
description outliving its code would be a confident wrong answer, which is the
one thing this index exists not to produce. Incremental indexing keeps the cost
proportional: only units in changed files need describing again.

*Code*, not source: documentation is excluded from that digest. Adding or
rewriting a docstring changes nothing about what a function does and so cannot
make a description wrong, and while the digest covered it the guard fired on
its own reflection — promoting a description into the source inserted that
very description, changed the digest, and discarded the entry along with
whatever part of the text had not been promoted. Measured here, that cost
Chinese retrieval twenty-eight percent of its hit rate. Two digests are stored:
the whole source, which is a single hash and hits for every unit whose file did
not change, and the documentation-excluded one, computed only after the cheap
one has missed. The parse is therefore paid once per genuinely changed unit
rather than once per unit per run, and an entry written before the second field
keeps working through the first.

## Promotion

`describe promote` turns a stored description into a doc comment in the
language's own convention and emits a unified diff. The store buys
independence from the file and pays for it with a digest, a relocation lookup,
a fingerprint and a pruning rule — all of which simulate a property text in
the source has for free. So the store is the fallback and the code is the
destination.

The tool still never writes source: the patch is reviewed and applied by a
person. Only declarations with no documentation at all are touched, because
the author's words outrank an agent's and are already harvested. Only the half
meant for a reader is promoted, so a bilingual description leaves its second
language where retrieval still uses it.

## Evaluation

Two rulers, measuring different things. `benchmarks/golden.json` grades ranking
over a five-file synthetic fixture: small, stable, and asserted in CI as a
regression tripwire. `benchmarks/repo_queries.json` grades seventy
natural-language questions over this repository's own source, in English and
Chinese, each listing every unit that genuinely answers it.

The second exists because the first cannot resolve a change to how vocabulary
reaches the index — four candidate scoring changes measured over an
eight-question set all landed between five and six correct, which is the
instrument's resolution rather than a ranking of options. Questions are keyed
on file path and declaration name, never on line, so the ruler survives the
edit that orphaned nineteen descriptions in 0.4.1, and every acceptable answer
is checked against the index before anything is scored: a question that
quietly stops matching would read as a regression, and one quietly removed
would read as progress.

Its score is asserted nowhere. It falls whenever the repository gains code
nobody has described yet, which is ordinary development. CI reports it;
`tests/test_repo_queries.py` enforces that the ruler still refers to real
code, that both languages are present, and that some question still fails.

A store change is invisible to a file fingerprint, so the index also records a
digest of the authored text — the same defect class the configuration
fingerprint covers.

## What a reply carries

Every reply has the same shape, and one rule decides it: **a result is
navigation, and the code arrives once.** `results` carries the identifier,
path, line range, signature, description, score and matched terms.
`context` carries the source, trimmed to `max_chars`, and
`omitted_for_budget` says how many results it did not reach.

This was three separate overruns before it was one rule. `search --json` at
its default limit served 65,025 characters against a stated budget of 12,000;
`research` served 111,843, because reporting two retrieval steps meant
serialising the same eight units three times with their source attached; and
`neighbors` served 27,473 with no budget at all. Bounding each emitter would
have left the next one free to overrun, so the source came out of
`SearchResult.to_dict` instead -- a result that has no source cannot carry it
twice. A step in a research trace now reports only id, score and matched
terms, because a trace exists to show how the answer was reached, not to
repeat it.

Measured after, on the same 1153-unit repository: 24,403 / 24,429 / 13,848.
The remainder above the budget is result metadata, and `search.max_chars` is
the *context* budget -- it bounds the context exactly, and the envelope around
it is larger.

## Retrieval strategy

Results combine a weighted lexical score (exact symbols, error names, rare
domain terms) with cosine similarity (ranking among lexical matches). The JSON
response includes score, matched terms, location, description and source.
Agents should treat retrieval as navigation evidence, then open the cited
source before editing.

### How a match is scored

BM25F: for each query term, how often it occurs in each of a unit's fields,
divided by how long that field is against the average for that same field,
scaled by what the field is worth, saturated so a repeated word cannot run
away, and weighted by how rare the term is across the corpus.

| field | weight | why |
|---|---|---|
| `name` | 8 | what the author decided to call the thing |
| `signature` | 4 | what it takes and returns |
| `description` | 3 | what it is for, generated or written |
| `relations` | 2 | what it calls and imports |
| `body` | 1 | everything it happens to mention |

Three properties matter, and none of them was present before 0.6.0:

- **Rarity, derived from the corpus, not from a stopword list.** A word in
  nearly every unit says nothing about which unit is wanted. On a foreign
  repository `calls` reached 97% of units and `the` 49%, while `daemon`
  reached two and `warm` none — and the score was four-sixths decided by the
  words carrying no information. Deriving this from the corpus is what makes
  it work in any language: a Chinese bigram earns its weight the same way.
- **Length, per field rather than per unit.** The largest declaration held 539
  distinct terms against a median of 52, so it could contain any query by
  accident, and it came back for four questions out of six. Normalising each
  field against its own average is the part that matters: measured against one
  length for the whole unit, a long body's advantage in raw count almost
  exactly cancelled its penalty for being long.
- **Where the word is.** A term in a name is what a declaration is called; the
  same term two hundred lines into a body is a mention.

`CodeUnit.searchable_fields` is the single definition of what retrieval may
match, and `searchable_text` — what a unit is embedded from — is derived from
it, so a field added for ranking cannot go missing from the vector. A test
asserts the weight table covers every field.

The known limit is that a test declaration often outranks the code it tests,
because it repeats that code's vocabulary and adds assertions of its own. On
the foreign ruler that is 11 of 35 top-1 results, down from 14.

Two candidate sets, with distinct jobs. Every unit reached by any query term is
scored, so recall is complete. A *selective* subset — the units reached by a term
occurring in under a tenth of the corpus — additionally receives a cosine score,
because a 384-dimension dot product for every unit a stopword-class term touches
is pure cost. Letting the selective set decide who gets scored *at all* was a
defect: units matching more query terms went unranked and `--limit 8` returned a
single result on a 116-unit repository.

With no lexical overlap anywhere, scoring falls back to pure cosine so a query
still returns something. On a small corpus that fallback returns units with an
empty `matched_terms` and a near-zero score, which is the honest signal that
nothing actually matched.

Complete recall is not free. Measured at 10,000 units, mean query time went from
1.63 ms to 3.90 ms — the earlier figure was cheap because it scored a subset and
under-filled the result list. Scoring accumulates match counts straight from the
posting lists, materialises only the `limit` results actually returned, and
recovers each one's matched terms by binary search over the sorted postings;
without those three the same recall measured 16.9 ms.

## Large repositories

Index schema 2 stores per-file hashes. One `RepositorySnapshot` is taken per run
and shared by parsing and publication: hashing in a second walk let a save
landing between the two record a file's new hash beside units parsed from its
old content, after which `fingerprint` reported the index fresh and every later
incremental run reused the stale units permanently. Sharing the snapshot also
took a run from four tree walks to one. Re-indexing reuses parsed units and
vectors for unchanged files while preserving repository-global serials. Use
`index --full` to discard that cache. Use `index --compact` to move 384-d
vectors from verbose JSON numbers into a float32 sidecar; the metadata remains
inspectable JSON. Index publication is atomic: content-addressed vector files
are written before an atomic JSON pointer replacement, and stale sidecars are
removed after publication. Embedding provider/version metadata invalidates
incompatible cached vectors automatically.

Search tokenization is cached in an in-memory inverted index for an agent
session. Graph expansion is capped by hop count and per-unit edge budgets.
Symlinked source files and source files above `index.max_file_bytes` (5 MiB by
default) are skipped, to prevent repository escape and generated-file memory
spikes. Beyond roughly 100k units, JSON loading and the no-overlap vector
fallback become the next bottlenecks; the appropriate next storage layer is
SQLite metadata plus an ANN vector index, not a larger JSON file.

## GRAG

The current graph contains only conservative, inspectable relationships:
`calls`, `imports`, and `contains`. A call resolves on an exact match of the
text the parser recorded. Falling back to the last dotted segment is a guess and
is allowed only when the head of the path is attributable to this repository —
`self`/`cls`, or a module some file here defines. Unrestricted, that fallback
gave `os.path.join` a `calls` edge into an unrelated local `join`; foreign
prefixes now resolve to nothing, as this section already promised. `search --graph --hops 1` retrieves normal
seeds and propagates a decayed score to bounded neighbors. Every
expanded result carries the exact graph path as evidence. Unresolved or
ambiguous symbols are omitted or capped rather than guessed.

## ARAG

The JSON-lines agent supports `search`, `research`, `neighbors`, `open`,
`describe_pending`, `describe_put`, `refresh`, and `stats`. `research` is a
deterministic two-stage controller: search, then at most one graph expansion
when confidence is low. It returns each step and a stop reason. `open` rejects
paths outside the repository root, refuses files above `agent.max_open_bytes`,
and truncates its reply at `agent.max_open_chars` with `truncated: true` — a
line count is not a size, and a three-line file can hold megabytes on one line.
Graph/research hop and step budgets are capped, and non-finite numeric fields
saturate at their bound rather than raising.

No single request may end a session. The loop reports a malformed field as
`invalid_request` and anything unanticipated as `request_failed` with the
exception type, then serves the next line. Enumerating expected exception types
was the earlier design and the reason `limit: 1e400` terminated the daemon. This is the safe
contract for a future LLM planner; an LLM may propose follow-up queries but
must not bypass these budgets or evidence requirements.

`stats` distinguishes two questions that are easy to conflate. `stale` says
whether the index still describes the repository; `index_behind` says whether
descriptions stored this session have reached the published index. After a
`describe_put` the live units are current and the file on disk is not, so the
first is correctly `false` while the second is `true`.

Request and response lines are UTF-8 in both directions regardless of the
console codepage: `main()` pins the process streams rather than inheriting the
OS locale. Without that pin a non-UTF-8 console silently mis-decoded a UTF-8
query into a zero-result, exit-0 answer, and a response holding a character
outside the codepage terminated the subprocess.

## Measured envelope

One representative synthetic Windows run (500 files, 20 functions/file, 10,000
units) took **1.84 s** for full parsing and embedding and **0.207 s** for a
one-file incremental refresh (**8.9x**). Compact storage was **35.6%** of
readable JSON (20.8 MB against 58.3 MB). In an isolated agent process, 10,000
units loaded in **45.4 ms**, built a 10,509-term inverted index in **117.7 ms**,
used **58.7 MiB** current and **65.0 MiB** peak RSS, and full-recall hybrid
queries averaged **3.90 ms** (median 3.22 ms over 200 warmed samples). A full
stale stat walk cost **60.4 ms**; the one-second monitor cache made repeated
checks effectively free (0.0004 ms).

Four runs bound the spread: build and walk timings vary by a few percent, and
`compact_write_ms` and `search_index_ms` by considerably more, so treat any
single figure as directional rather than as a service level. The archived run
is the one closest to the four-run centre and is `large-benchmark-result.json`.

The query estimator was itself a defect until 0.4.0: ten cold samples of a
sub-millisecond call once made an unchanged query path look like a real
regression across three runs. It now warms up and takes 200 samples, and
records the median beside the mean so a reader can judge what the number is
worth.

## Distribution

Two artifacts ship from one repository, and they are deliberately separate.

The **Python package** on PyPI is the whole implementation. Publishing goes
through trusted publishing, so no API token exists to leak or rotate, and the
workflow refuses a tag that disagrees with the declared version, verifies the
wheel still carries its licence and typing marker, and installs the built
artifact into a clean environment to run the documented commands before
uploading anything.

The **Claude Code plugin** contains one skill and nothing else: no hooks, no
agents, no MCP server. Measured with `claude plugin details` on an installed
copy, it adds **~39 tokens to every session** and ~1.4k only when the skill
fires. That asymmetry is the reason the plugin carries no code: an always-on
cost is paid by every session in every repository, whether or not anyone
searches anything, while the implementation is only needed once someone does.

The seam between them is step 0 of the skill, which installs the package if
importing it fails. That one line has been wrong twice — first naming a module
nothing installed, then naming a package index this project did not publish
to — both times because no gate ever ran it. It is now executed verbatim by a
CI job that extracts it from the skill, and a test asserts that every
documented install target names a source that resolves.

## Evolution plan

1. **Provider adapters:** optional OpenAI/Ollama/sentence-transformer
   embeddings selected by configuration, with a local fallback and recorded
   provider/version. Agent-authored descriptions are the cheaper answer to the
   same problem and land first deliberately; a provider would buy true synonym
   matching at the cost of the no-dependency, no-network, reproducible-index
   properties, and that trade should be made knowingly.
2. **Richer parsing:** Tree-sitter for JavaScript/TypeScript/Go/Rust/Java/C++,
   capturing definitions, references, tests, inheritance and configuration
   symbols. This would also supply `qualified_name` for non-Python languages,
   which the line scanner currently sets equal to `name`.
3. **Persistent scale layer:** SQLite metadata and an ANN vector index once
   repositories exceed the measured JSON envelope.
4. **Richer GraphRAG:** `implements`, `tests`, `configures` and git co-change
   edges, with confidence and provenance on every edge.
5. **LLM planner:** bounded follow-up queries, preserving the current tool
   budgets, privacy policy and observable stop reasons.
6. **Evaluation:** multi-hop graph questions and real repository tasks in the
   golden set; recall@k, citation and edge accuracy, latency, context budget.

## Safety and privacy

No source leaves the machine. There is no network code to disable.

A repository being scanned is untrusted input, and that includes any
`.rag-your-code/index.json` it ships. Nothing read out of an index may name a
filesystem path to act on: the vector sidecars a run supersedes are enumerated
from the naming scheme `write_index` itself uses, never from the index being
replaced. Enumerating also reclaims sidecars orphaned by an earlier run whose
index was unreadable.

`rag-your-code.descriptions.json` is committed and will therefore meet merge
conflicts and hand-editing. A malformed one is treated as empty rather than
fatal: the cost is retrieval quality, which describing again recovers, where
refusing to search until it is repaired would not be recoverable at all.

External embedding providers, when added, must be opt-in, clearly reported in
the index metadata, and support path and content exclusion rules.
