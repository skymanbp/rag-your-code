# The vendored corpora

Two repositories nobody here wrote, carried at pinned tags. Both are
third-party code: this project did not write them, does not maintain them, and
does not modify them. Each licence travels with its copy.

| | `flask/` | `cobra/` |
|---|---|---|
| upstream | [pallets/flask](https://github.com/pallets/flask) | [spf13/cobra](https://github.com/spf13/cobra) |
| tag | **3.1.3** | **v1.9.1** |
| commit | `22d924701a6ae2e4cd01e9a15bbaf3946094af65` | `40b5bc1437a564fc795d388b23835e84f54cd1d1` |
| released | 2026-02-18 | 2025-02-16 |
| licence | BSD-3-Clause, [`flask/LICENSE.txt`](flask/LICENSE.txt) | Apache-2.0, [`cobra/LICENSE.txt`](cobra/LICENSE.txt) |
| omitted | `docs/`, `.git/` | `site/`, `assets/`, `.git/` |
| language | Python | Go |
| units | 1,572 `5fd51169eacc` | 602 `3eabaa705477` |

`cobra/` arrived in 1.5.0 and is the first graded repository that is not
Python. That is its point. Four constants — `search.min_coverage`,
`search.min_concentration`, `COMMON_TERM` and `COVERAGE_FULL_STRENGTH` — were
fitted on two corpora that were both Python and both carried their
documentation *inside* the declaration, where the AST hands it over. Go writes
it above, outside the unit's span, so a Go corpus grades the line scanner and
the rule table instead, on prose the parser has to pick up rather than read out
of a syntax tree. It was chosen over two other candidates by counting
collisions with the subject words of `benchmarks/absent_queries.json`: cobra 8,
gin 17, chi 18.

## Why a copy and not a path

The foreign ruler grades retrieval on a repository nobody here wrote, which is
the only way to see what a first-time user sees: no descriptions, and a
vocabulary this project did not choose. Until 1.4.0 that repository was a
checkout on one machine, and it cost the project three separate things:

- Two graded questions pointed at a declaration that repository had renamed.
  The ruler's integrity check refused to grade, correctly, and the failure went
  unnoticed because nothing ran it.
- A published score moved from 0.257 to 0.229 hit@1 with no code change, purely
  because the subject had grown by ninety units.
- The local-model comparison in [ROADMAP](../../docs/ROADMAP.md) has a row
  whose two arms were taken against two states of that repository *while it was
  being edited*, so it says nothing about the model. That row is the reason
  this directory exists.

A vendored copy at a pinned tag is reproducible by anyone who clones this
repository, needs nothing of the machine it was written on, and lets CI run the
foreign ruler as an ordinary job.

## It is not indexed as part of this project

`rag-your-code.toml` at the repository root adds `corpus` to `index.ignore`.
Without it, 2,174 units of somebody else's code would enter this project's own
index — which is not merely noise. Two of the five rulers measure retrieval
over *this* repository, and `benchmarks/absent_queries.json` asserts that
nothing here answers thirty questions, a claim a vendored web framework would
falsify by accident.

`tests/test_absent_queries.py` checks that claim against **both** corpora,
which is the half that used to be unenforceable. Adding the second one cost two
question rewrites on the day it landed: cobra names one guarded word in a
completion example and produces a second by lower-casing a mixed-case
identifier, so two questions were one ordinary token from being answerable
there. Both were reworded rather than exempted per corpus — a guard with an
exemption list weakens every time it is tested.

## Working with it

```powershell
python -m ragyourcode.cli index benchmarks/corpus/flask
python -m benchmarks.repo_queries --index benchmarks/corpus/flask --questions benchmarks/cold_queries.json
python -m benchmarks.repo_queries --index benchmarks/corpus/flask --questions benchmarks/absent_queries.json
python -m benchmarks.grep_baseline --index benchmarks/corpus/flask --questions benchmarks/cold_queries.json --root benchmarks/corpus/flask

python -m ragyourcode.cli index benchmarks/corpus/cobra
python -m benchmarks.repo_queries --index benchmarks/corpus/cobra --questions benchmarks/cobra_queries.json
python -m benchmarks.repo_queries --index benchmarks/corpus/cobra --questions benchmarks/absent_queries.json
python -m benchmarks.grep_baseline --index benchmarks/corpus/cobra --questions benchmarks/cobra_queries.json --root benchmarks/corpus/cobra
```

Each index lands in that corpus's own `.rag-your-code/`, which is ignored by
Git — the corpus is committed, the artifact built from it is not.

## Replacing it

Bumping to a later tag is a change to a ruler, not a change to code, and every
figure taken against the old one stops being comparable. Do it deliberately:

1. Re-vendor the tree at the new tag, keeping the same omissions.
2. Run that corpus's ruler. Its integrity check names every graded
   declaration that moved; repoint them or retire the question.
3. Run the suite — the absence guard checks this corpus for the vocabulary the
   fourth ruler asserts is absent everywhere.
4. Re-measure every published figure that cites this corpus, and replace the
   fingerprint beside it. A stale fingerprint next to a fresh number is the
   defect the fingerprint exists to prevent.
