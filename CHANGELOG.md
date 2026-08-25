# Changelog

Notable changes per release. Dates are the release date; measurements are from
the development machine (Windows 11, CPython 3.13) and are directional.

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
