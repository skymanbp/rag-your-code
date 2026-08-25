# Contributing

## Setup

```bash
python -m pip install -e ".[dev]"
pytest -q
```

The package itself has no runtime dependencies and that is a design constraint,
not an accident — it is what makes the index reproducible and usable on a
private repository with no network. A change that adds one needs to argue for
itself in the pull request.

## What the tests are for

Two suites carry contracts rather than coverage, and both will fail you loudly
if you change behaviour without meaning to.

- **`benchmarks/golden.json`** pins retrieval ranking. Its paraphrase queries
  already caught one real regression, where a first attempt at hybrid scoring
  dropped top-1 accuracy from 1.0 to 0.857. Do not adjust the expected results
  to match new output; if a ranking change is right, say why in the pull
  request and record the before and after numbers.
- **`tests/fixtures/languages/`** grades the non-Python parser. `SPEC.md` there
  states what counts as a unit — *a named declaration that owns a body span* —
  and `expected.json` lists every declaration, its line, its signature, the
  identifiers a naive regex would wrongly capture, and the constructs the spec
  deliberately excludes with the rule that excludes each one.

Adding a language means adding rows to the rule table in `parser.py` and a
fixture with its expected units. The line scanner does not change, and
`index.suffixes` picks the new suffix up automatically because its permitted
values are the parser's dispatch table.

`tests/test_metadata.py` carries a third kind of contract: it executes the
documentation. Every subcommand and protocol action named in `README.md` or
`SKILL.md` must exist, and every `pip install` line must name an installable
source. Both audits of this project found the same defect in that step — an
instruction no gate ever ran — so the gate now exists.

## Ground rules for a change

1. **Measure before and after.** The claims in `docs/ARCHITECTURE.md` are
   numbers from `benchmarks/`, not impressions. If your change moves one,
   regenerate `large-benchmark-result.json` and update the prose in the same
   commit — a stale published number is worse than no number.
2. **A test that cannot fail is not a test.** Before trusting a new test, run it
   against the code as it was. `git worktree add --detach <tmp> HEAD` gives you
   that tree; copy the test in and confirm it goes red.
3. **Fix the cause, not the instance.** If two symptoms share a root, they get
   one change. The audit that produced 0.3.0 found 94 findings resting on five
   causes, and the parser rewrite closed four symptoms at once because it
   removed their shared precondition rather than patching each site.
4. **Say what you did not check.** An honest "this path has no coverage" is
   worth more than a confident summary that quietly generalises from a green
   gate to the parts it does not exercise.
5. **Check the instrument before believing it.** Three runs of the large-repo
   benchmark once made an unchanged query path look like a real regression;
   the estimator was ten cold samples of a sub-millisecond call. When a number
   moves, establish the noise band before deciding what the movement means.
6. **A number in prose is a claim, and claims get gates.** Two of this
   project's defects were sentences nobody checked: an install line that named
   a package index it did not publish to, and a count of excluded constructs
   copied from the line above it. Both are now asserted in
   `tests/test_metadata.py`. If you state a figure in a document, prefer
   deriving it from the data, and if you cannot, assert it.
7. **Compare item sets, not totals.** A pass count that stayed at six while
   one test was deleted and another added looks exactly like no change. When
   claiming nothing regressed, diff the node ids, the keys, or the names — this
   rule caught a silently removed test during the 0.4.2 documentation pass.

## Rules learned the hard way

**An input the index does not record is an input that will go stale.** Three
times now: the settings, the descriptions, and the parser itself. Reuse is
keyed on a file's bytes, and cached units are a function of the bytes *and* of
everything that decided what a unit is. If you add something that shapes the
output, put it in `build_fingerprint`.

**A guard must not fire on a change that cannot make it wrong.** The digest
deciding whether a description still applies used to cover the unit's
documentation, so writing that description into the source as a docstring
discarded it. Before adding a check, ask what it is protecting against and
whether the thing it watches can actually cause that harm.

**A ruler over your own repository cannot see the first-time user.** Rarity
weighting was implemented in 0.5.0, measured on this project's own questions,
and dropped as "no evidence". It was measured in the one place the defect is
masked: an index where every unit carries a hand-written bilingual
description. On a foreign repository with none, the same change tripled hit@1.
If a feature exists to help someone who has not set anything up yet, measure
it on a repository that has not been set up.

**A constant tied to a scale is a defect waiting for the scale to move.** The
research loop stopped early when the top score passed 0.8. Ranking became
BM25F, the score scale moved, and the stop silently ceased to exist -- only 3%
of queries could reach 0.8 at all, and no test noticed because the assertion
was `stop_reason in {all four values}`. It is a margin between two scores from
the same query now, which cannot drift. Prefer a ratio to a threshold.

**Before comparing two configurations, check they are comparable.** Measuring
a tokenizer change against stored indexes made the query vectors and the unit
vectors disagree, and the resulting numbers described nothing. The comparison
only became honest once both sides were rebuilt together — and it then
reversed the conclusion.

## Adding a setting

`config.py` holds one settings table. Add a row and the loader, the validator,
the fingerprint, `config list` and the generated template all pick it up — no
other file needs editing. Two decisions come with the row:

- `affects_build` is true only if the setting changes what an index *contains*.
  Those force a full rebuild when they change, so marking a retrieval-time knob
  this way makes the fingerprint an obstacle rather than a safeguard.
- Bounds are not optional. A value that is out of range must be refused, not
  clamped: a setting silently adjusted is indistinguishable from one that had
  no effect.

## Scope

The evolution plan in `docs/ARCHITECTURE.md` lists what is deliberately not here
yet: Tree-sitter parsing, and a SQLite/ANN storage layer for repositories past
the measured JSON operating envelope. Work toward those is welcome; silently
making one of them a hard requirement is not.

Provider-backed embeddings arrived in 0.8.0 and the trade was made the only
way it could be: **as something a user turns on.** The default opens no
socket, adds no dependency, and produces the same reproducible index it always
did, and a test asserts that by making the transport raise. If you touch the
provider path, that test is the one that matters — everything else in
`tests/test_providers.py` is only worth having if the default still works with
the network switched off.

Agent-authored descriptions remain the cheaper answer to the same problem, and
they are not made redundant by a model: they put missing vocabulary into the
index once instead of hoping an embedding bridges it, and a human can read and
correct them.
