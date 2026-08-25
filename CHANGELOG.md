# Changelog

Notable changes per release. Dates are the release date; measurements are from
the development machine (Windows 11, CPython 3.13) and are directional.

## 0.6.0 — 2026-08-25

0.5.0 asked where retrieval's vocabulary comes from. This release asks what
happens to that vocabulary once it is there, and the answer was: not much. The
score was the fraction of a query's words a unit contained. Every word weighed
the same, nothing corrected for size, and it made no difference whether a word
was the declaration's name or the two-hundredth line of its body.

None of the existing rulers could see this. They all graded a repository
written by the same people who wrote the questions, on an index where every
unit under `src/` carries a hand-written bilingual description. Indexed cold
against a foreign repository — 1153 units, no descriptions — the same code
scored 0.086 hit@1 against the 0.457 this project had been reporting.

### Added

- **A third ruler, over code nobody here wrote.**
  `benchmarks/cold_queries.json` asks thirty-five questions about cc-enforcer,
  in English and Chinese, phrased in a user's words rather than in the words
  of the docstring that answers them. Answers were verified one at a time
  against real declarations. The graded repository is external, so the ruler
  is skipped when it is absent rather than silently scored as zero.
- **`repo_queries.py --cold`**, which grades the existing seventy questions
  against units built with no description store — the portable half of the
  same question, and the one that runs anywhere.
- **`omitted_for_budget`** in both JSON search responses, saying how many
  results the context budget dropped.

### Changed

- **Ranking is BM25 over weighted fields.** A term's worth now comes from how
  rare it is in the corpus being searched, its count is normalised against the
  average length of the field it appeared in, and fields are weighted: name 8,
  signature 4, description 3, relations 2, body 1. Rarity is derived rather
  than listed, so there is no stopword table to maintain and the mechanism
  works on Chinese bigrams exactly as it does on English words.

  Measured on identical content, three rulers, nine metrics, all up:

  | ruler | hit@1 | hit@3 | MRR |
  |---|---|---|---|
  | cold, foreign repository (35) | 0.086 → **0.257** | 0.229 → **0.400** | 0.157 → **0.314** |
  | cold, this repository (70) | 0.200 → **0.271** | 0.357 → **0.486** | 0.271 → **0.367** |
  | described, this repository (70) | 0.457 → **0.500** | 0.657 → **0.800** | 0.545 → **0.631** |

- **`CodeUnit.searchable_fields`** is the single definition of what retrieval
  may match, and `searchable_text` is now derived from it. The unit vectors
  are unchanged, bit for bit: the join differs by one whitespace character and
  the tokenizer does not distinguish them.
- **The context budget bounds the results, not only the context.** `search
  --json` at its default limit served 65,025 characters against a stated
  budget of 12,000, because the cap applied to the context string while every
  result was serialised beside it in full — and the results are the half an
  agent reads. The same budget now decides how many results there are. The
  first result is always returned even when it alone exceeds the budget,
  because finding something and returning nothing is worse than one oversized
  answer.

### Measured and rejected

Four changes were implemented and dropped, which is what three rulers are for.
Excluding curated text from a unit's length, counting authored words instead
of tokeniser output, and lowering `b` each moved one to four questions in both
directions at once. **Splitting identifiers into words** — the largest-looking
win available, since `retry_charge` currently tokenizes to one opaque term —
was equal or worse on all three rulers once the query and the stored vectors
were rebuilt together: the pieces are `get`, `find`, `check`, `test`, which
rarity weighting immediately discounts to nothing.

### Known limits

A test declaration often outranks the code it tests: 11 of 35 top-1 results on
the cold ruler, improved from 14. It repeats that code's vocabulary and adds
its own assertions, which BM25 counts as evidence. A path heuristic would fix
the number and be wrong in principle.

Ablating the vector layer now costs nothing measurable on a foreign repository
and one question of seventy here, where it used to cost 0.114 of hit@1. That
earlier contribution was term frequency and length normalisation delivered
through a lossy hash — the two things BM25 now does properly — and never
semantics. The vectors remain 55% of an index's size.

## 0.5.0 — 2026-08-25

0.4.0 asked where retrieval's vocabulary comes from and answered "whatever an
agent writes into a sidecar". That is one rung of three, and the least durable
one: text in the code needs no bookkeeping, while text beside it needs a
digest, a relocation lookup, a fingerprint and a pruning rule — all of them
simulating a property the first has for free.

### Added

- **Documentation the author already wrote is now indexed.** Fourteen of the
  fifteen supported languages put it immediately above a declaration — JSDoc,
  Javadoc, KDoc, rustdoc, Go doc comments, XML doc comments, PHPDoc — and a
  unit's span begins at the declaration, so all of it sat outside the indexed
  text. The same sentence reached thirteen searchable words as a Python
  docstring and two as a JavaScript comment; both now reach thirteen. Measured
  over the language fixtures: zero of ninety-five non-Python declarations
  carried documentation into the index, sixteen now do, contributing 171
  searchable words.

  A licence header separated by a blank line, code somebody commented out, and
  a row of dashes are each deliberately excluded — indexing them invents
  vocabulary the author disowned.

- **`describe promote`** emits a unified diff that moves a stored description
  into the source as a doc comment in the language's own convention, for
  declarations that have none. Standard output is the patch so it pipes into
  `git apply`; the tool still never writes source. Only the half meant for a
  reader is promoted, so a bilingual description leaves its second language in
  the store.

- **A ruler that can tell an improvement from noise.** Seventy natural-language
  questions over this repository's own source, in English and Chinese, each
  listing every unit that genuinely answers it. Four candidate scoring changes
  measured over the previous eight-question set all landed between five and six
  correct, which is the instrument's resolution rather than a ranking of
  options. Its score is asserted nowhere — it falls whenever the repository
  gains undescribed code — but `tests/test_repo_queries.py` enforces that every
  acceptable answer names real code, that both languages are present, and that
  some question still fails.

  First measurement, and the honest version of a figure previously given as
  2 of 8:

  | | generated | agent-written |
  |---|---|---|
  | hit@1 | 0.171 | **0.500** |
  | hit@3 | 0.314 | **0.729** |
  | MRR | 0.240 | **0.605** |
  | answered with no shared word | 15.7% | **0%** |

### Fixed

- **Upgrading the parser reached no existing index.** Reuse is keyed on a
  file's bytes, but cached units are a function of the bytes *and* of the code
  that parsed them, so every unchanged file kept units the old parser produced
  until it happened to change. That was the third input the index did not
  record, after the settings and the descriptions; since all three mean the
  same thing and call for the same action they are now one `build_fingerprint`,
  over the build settings and a digest of the parser's own source.

- **Promoting a description discarded it.** The digest deciding whether a
  description still applies covered the unit's documentation, so inserting that
  description as a docstring changed the digest and dropped the entry — taking
  whatever part of the text had not been promoted. Measured here: 64 of 124
  descriptions lost, and Chinese hit@1 from 0.583 to 0.417. Documentation is
  now excluded from that digest, because documentation is not code and cannot
  make a description wrong. This also stops a hand-edited docstring from
  discarding a description of code that did not change, and makes Python
  consistent with the fourteen languages whose documentation was already
  outside the span.

  Re-measured with the fix, promoting all 68: nothing discarded, Chinese
  unchanged at 0.667, hit@1 0.443 → 0.457.

### Measured and rejected

A conservative suffix stripper and term-rarity weighting were both implemented
and measured before the ruler existed. On eight questions, stemming fixed one
query and broke another; rarity weighting changed nothing at all, because the
failing query's two informative words matched no unit under any weighting.
Both were dropped for want of evidence rather than of an implementation, and
the ruler now exists to settle them.

## 0.4.2 — 2026-08-25

A closing pass. Every distribution path is now walked end to end, the
documentation is rewritten around what the project is for rather than how it is
built, and one more prose claim turned out to be wrong.

### Fixed

- **`docs/TESTING.md` stated 96 deliberately-excluded constructs; the fixtures
  hold 89.** The wrong figure was the count of expected units, copied from the
  line above. It survived because a number in a sentence is exactly the kind of
  claim no gate looks at — the same cause as the install line that was wrong in
  two consecutive releases. All five fixture counts are now asserted against
  `expected.json` itself, in whichever document states them.

### Changed

- `README.md` is rewritten for someone arriving without context: what the
  problem is, what installing it gets you, how it works, what the embedding
  genuinely does and does not do, and every measured result in one place. The
  Claude Code plugin is now the primary documented install path.
- `docs/ARCHITECTURE.md` gains a section on distribution, including why the
  plugin deliberately ships one skill and no code: an always-on cost is paid by
  every session in every repository, and the measured figure is ~39 tokens.
- `docs/ROADMAP.md` records the verified distribution paths and states the
  three remaining gaps outright — qualified names outside Python, descriptions
  for `tests/` and `benchmarks/`, and the absence of stemming.
- `docs/TESTING.md` gains a section on what the suites do *not* cover, since a
  green suite says nothing about what it never runs.

### Verified

| path | how |
|---|---|
| CI | 3.10–3.13 × Linux and Windows, 11 of 11 jobs |
| release artifacts | downloaded from the release page, installed into a clean environment, documented commands run |
| PyPI | `pip install rag-your-code` by name into a clean environment |
| Claude Code plugin | installed through `/plugin`, present in both local registries, `claude plugin details` reporting one skill and ~39 always-on tokens |

Still unverified, and stated rather than implied: whether the skill fires on
its own in a fresh session, which needs an interactive session rather than a
command.

Suite: 208 tests.

## 0.4.1 — 2026-08-25

The first release published to PyPI, and two defects that only appeared once
0.4.0's own features were used on a real corpus rather than a fixture.

### Added

- A release workflow that publishes to PyPI through trusted publishing, so no
  API token exists to leak or rotate. It refuses to publish when the tag and
  the declared version disagree, and installs the built wheel into a clean
  environment and runs the documented commands before uploading anything.
- This repository now describes its own implementation: all 120 units under
  `src/` carry an agent-written bilingual description, committed in
  `rag-your-code.descriptions.json`.

### Fixed

- **A description was orphaned when its code merely moved.** Unit ids embed
  the line a declaration starts on, so inserting a comment near the top of a
  file gives every declaration below it a new id while changing none of them.
  Adding a seven-line comment to `config.py` orphaned nineteen descriptions
  that described code which had not changed by a single byte. A description is
  now found by file and code digest when its id no longer resolves, and
  pruning keeps an entry whose code is still live. Two declarations in one file
  with identical source and different stored text stay ambiguous and resolve to
  nothing rather than to a guess.
- **`describe.max_chars` was set inside the normal range.** 600 was chosen
  before any real corpus existed. Measured over the 120 descriptions written
  for this project's own `src/` tree the median is 349 characters but the 90th
  percentile is 662, so the cap rejected roughly one good-faith description in
  eight — and rejected them at the complex units retrieval most needs help
  with, since nothing is truncated to fit. The default is now 1000, which
  covers the whole observed range.

### Measured

Ten natural-language questions about this repository, before and after
describing `src/`: units matching the expected file went from 2 of 8 to 6 of 8,
Chinese queries from 0 of 4 to 3 of 4, and the number of queries answered only
by the no-overlap cosine fallback — that is, with no lexical evidence at all —
from 4 to 0.

Two still miss, and both are worth stating. One query says `catastrophic
backtracking` where the description says `backtracks catastrophically`: there
is no stemming, so those share no token, which is exactly the limit this
feature is documented to have. The other returned a unit that answers the
question from a different file than the one predicted, so the expectation was
wrong rather than the retrieval.

## 0.4.0 — 2026-08-24

0.3.0 made the existing claims true. 0.4.0 is the first release that adds one,
and it rests on a measurement: the embedder is a signed feature hash, so cosine
over it is normalised token overlap and carries no semantics. `sum two numbers`
against `add a pair of integers` scores **0.0000** — the same as against
`delete the user database table`. A trained model scores that pair around 0.8.

### Added

- **A configuration layer.** Twelve settings in `rag-your-code.toml` at the
  repository root, resolved CLI flag > file > default, with a `config`
  subcommand (`init`, `list`, `get`, `set`, `path`). `set` preserves every
  comment it does not consume. There is no environment layer: an index is an
  artifact of a repository, not of a shell.

  An unknown key or an out-of-range value is refused with a reason. A setting
  silently dropped is indistinguishable from one that had no effect.

  The four settings that decide what an index *contains* are fingerprinted into
  the index, and a change forces a full rebuild — reuse is keyed on file
  content, which cannot notice that the rules changed. `embedding.dimensions`
  used to fail in silence, because `search` skips the cosine term when widths
  disagree rather than raising.

  No new dependency: `tomllib` from 3.11, and below that a subset reader that
  refuses what it cannot parse and is differential-tested against `tomllib`.

- **Agent-authored descriptions.** `annotate.py` says it in its own first line:
  it describes a unit *without an LLM*, so it introduces no vocabulary the
  source did not already contain. The agent already reading this index can
  supply those words, through `describe_pending`/`describe_put` in the protocol
  or `describe status|export|import` on the command line. They are stored in
  `rag-your-code.descriptions.json` at the repository root, meant to be
  committed.

  Measured on the fixture repository, one generated sentence replaced by an
  agent-written bilingual one: `exponential backoff`, `double billing safety`
  and `支付网关超时` each went from no lexical evidence to rank 1.

  **This is not semantic generalisation.** Matching stays lexical; the work
  moves from query time to index time, and its reach is bounded by how many
  ways of saying the thing the agent wrote down.

  Each entry is keyed by unit id and a digest of the unit's source. When the
  code changes the description is not applied and the unit returns to the
  pending queue — a description outliving its code would be a confident wrong
  answer, which is the one thing this index exists not to give.

### Fixed

- **The walker's suffix list and the parser's dispatch table were separate**
  and agreed only by coincidence. A suffix on the first but not the second was
  walked, read, parsed to nothing, and reported as a clean index of zero units.
  `index.suffixes` now derives both its default and its permitted values from
  the parser.
- **`incremental` in the index report described the wrong thing.** It was
  computed from whether a previous index existed, not from whether its units
  were reused, so the run that rebuilt everything was the run that claimed
  reuse. A `rebuilt_for_config` field now says why.
- **SKILL.md's install step named a package index this project does not
  publish to.** The 0.2.0 audit found that step telling an agent to run a
  module nothing installs; 0.3.0's fix was equally unrunnable and no gate
  noticed either time. The instruction now names a real source, a test asserts
  that every documented `pip install` names an installable one, and a CI job
  runs the command as written.
- **The query benchmark was too coarse to be evidence.** Ten cold samples of a
  sub-millisecond call made an unchanged query path look like a real regression
  across three runs. It now warms up, takes 200 samples, and records the median
  beside the mean.

### Changed

- `stats` reports `index_behind` alongside `stale`. They answer different
  questions, and after a `describe_put` the first is true while the second is
  correctly false.
- Version consistency is now asserted across `marketplace.json` too, which
  states it twice and was outside the check.
- Documentation states what the embedder does and does not do, up front rather
  than in a footnote. `README.md` no longer describes this as a
  retrieval-augmented *generation* index: there is no generation here.

## 0.3.0 — 2026-08-24

A hardening pass following an adversarial audit of 0.2.0. The audit's 94 raw
findings collapsed to five root causes, and the work is grouped by cause rather
than by symptom. `CodeUnit`, index schema 2, and the JSON-lines agent protocol
are unchanged; every fix sits beneath them. Details and measurements per phase
are in [docs/ROADMAP.md](docs/ROADMAP.md).

### Fixed

- **Running `index` against a repository could delete one of its files.**
  `write_index` derived the vector sidecar to delete from `vector_store.path`
  read out of the index it was replacing — a file that lives inside the scanned
  repository and is therefore untrusted. The supersede set is now enumerated
  from this run's own naming scheme, which also reclaims sidecars orphaned by an
  earlier run whose index was unreadable.
- **The agent subprocess died on non-ASCII output.** Process streams are pinned
  to UTF-8 rather than following the OS codepage. On a cp936 console a result
  holding an outside-the-codepage character raised `UnicodeEncodeError` and
  ended the session, and a UTF-8 CJK query was mis-decoded into an empty,
  exit-0 answer.
- **A single malformed request could end an agent session.** `int(1e400)` raises
  `OverflowError`, which is neither `TypeError` nor `ValueError`, so it escaped
  the request loop. Numeric fields now saturate at their bound, and the loop
  reports anything unanticipated as `request_failed` and keeps serving.
- **`--limit` came back under-filled.** The vector-candidate set had replaced the
  lexical candidate set, so units matching more query terms went unscored: 116
  units, `--limit 8`, one result. Recall is complete; the selective set now only
  decides who additionally receives a cosine score.
- **A save landing mid-index poisoned incremental reuse permanently.** Parsing
  and publication walked the tree separately, so the index could record a file's
  new hash beside units parsed from its old content and then report itself
  fresh. One snapshot is now shared, which also took a run from four tree walks
  to one.
- **Call edges were guessed.** `os.path.join` resolved to an unrelated local
  `join`, against this module's own promise. The leaf fallback now requires a
  repository-attributable prefix.
- **The non-Python parser is rewritten.** One whole-file regex did five jobs;
  its coupling produced catastrophic backtracking (a 530-byte `.js` file took
  12.6 s), a `[^;]*` that swallowed declarations across lines, and wrong line
  numbers and empty signatures. Three separated layers replace it. Measured
  against the new multi-language fixtures: 91 of 91 core declarations found,
  each with the correct `start_line` and a usable signature, no phantom units.
  The same 530-byte file now parses in 0.37 ms.
- **Python bodies were silently truncated.** `_line_offsets` split on characters
  `ast` does not treat as newlines, so one form feed inside a string literal
  desynchronised every later offset.
- **`open` bounded only line count.** A three-line file holding one 2 MB line
  returned 2,000,119 bytes on a single JSON line.

### Added

- 14 languages graded against source-controlled fixtures in
  `tests/fixtures/languages/`, with `SPEC.md` stating once what counts as a unit.
- `LICENSE`, `py.typed`, package classifiers and keywords, a `dev` extra
  declaring `pytest`, and `.claude-plugin/marketplace.json`.
- An install step in the bundled skill: a plugin install copies the skill but
  not the Python package.
- CI across Python 3.10–3.13 on Linux and Windows, plus a job that installs the
  built wheel into a clean environment and runs the documented workflow.

### Changed

- Retrieval memory at 10,000 units dropped from 70.5 MiB to 57.8 MiB and
  inverted-index build from 129 ms to 89.5 ms. Complete recall costs query time:
  1.63 ms to 3.82 ms. Golden retrieval quality is unchanged.

## 0.2.0

Incremental per-file reuse, repository-global serials, graph edges, and optional
compact float32 vector storage (`index --compact`).

## 0.1.0

First release: deterministic offline indexing, hybrid lexical/vector retrieval,
sidecar annotations, and the JSON-lines agent protocol.
