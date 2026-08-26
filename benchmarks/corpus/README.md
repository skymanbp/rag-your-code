# The vendored corpus

`flask/` is a copy of [Flask](https://github.com/pallets/flask) at tag
**3.1.3**, commit `22d924701a6ae2e4cd01e9a15bbaf3946094af65`, released
2026-02-18. It is third-party code. This project did not write it, does not
maintain it, and does not modify it — `docs/` and `.git/` are omitted and
everything else at that tag is present as published.

Its licence is BSD-3-Clause and travels with it, at
[`flask/LICENSE.txt`](flask/LICENSE.txt).

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
Without it, eighteen hundred units of somebody else's code would enter this
project's own index — which is not merely noise. Two of the four rulers measure
retrieval over *this* repository, and `benchmarks/absent_queries.json` asserts
that nothing here answers thirty questions, a claim a vendored web framework
would falsify by accident.

`tests/test_absent_queries.py` checks that claim against this corpus too, which
is the half that used to be unenforceable.

## Working with it

```powershell
python -m ragyourcode.cli index benchmarks/corpus/flask
python -m benchmarks.repo_queries --index benchmarks/corpus/flask --questions benchmarks/cold_queries.json
python -m benchmarks.repo_queries --index benchmarks/corpus/flask --questions benchmarks/absent_queries.json
python -m benchmarks.grep_baseline --index benchmarks/corpus/flask --questions benchmarks/cold_queries.json --root benchmarks/corpus/flask
```

The index lands in `benchmarks/corpus/flask/.rag-your-code/`, which is ignored
by Git — the corpus is committed, the artifact built from it is not.

## Replacing it

Bumping to a later tag is a change to a ruler, not a change to code, and every
figure taken against the old one stops being comparable. Do it deliberately:

1. Re-vendor the tree at the new tag, keeping the same omissions.
2. Run `python -m benchmarks.repo_queries --index benchmarks/corpus/flask
   --questions benchmarks/cold_queries.json`. Its integrity check names every
   graded declaration that moved; repoint them or retire the question.
3. Run the suite — the absence guard checks this corpus for the vocabulary the
   fourth ruler asserts is absent everywhere.
4. Re-measure every published figure that cites this corpus, and replace the
   fingerprint beside it. A stale fingerprint next to a fresh number is the
   defect the fingerprint exists to prevent.
