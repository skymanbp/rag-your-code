# Changelog

Notable changes per release. Dates are the release date; measurements are from
the development machine (Windows 11, CPython 3.13) and are directional.

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
