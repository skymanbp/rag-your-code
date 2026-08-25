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

**A default argument is bound when the function is defined.** The first sweep
over `search.min_coverage` set `search.DEFAULT_MIN_COVERAGE` on the module
between runs. Every threshold scored identically, which reads exactly like a
setting that does not matter — and it very nearly was recorded as one. Pass the
override into the call; `evaluate()` and `--min-coverage` exist for that. This
is the second confounded measurement in three releases, and both looked like
results rather than like mistakes.

**A number that moves for two reasons at once tells you nothing.** Two of the
rulers grade this repository's live tree, so editing any file moves them. Every
before-and-after in this project has to hold the corpus fixed: build one unit
list, vary only the thing under test. When 227 descriptions were removed, the
score did not move at all — and the reason was not that descriptions do not
matter, it was a bug that went on serving them.

**A ruler's own claims rot too, and sometimes in the opposite direction.**
`absent_queries.json` asserts that nothing here answers its questions. Three
separate things falsified that within an hour of writing it: two subject words
this repository had always contained, and two more that appeared *because the
source explains the feature using them as an example*. Documentation and ruler
cannot own the same vocabulary. The check is mechanical for that reason — and
it has now caught the identical mistake in three consecutive releases, twice
from the author who had just written this paragraph. Some lessons do not stay
learned by being written down; that is an argument for the gate, not for more
care.

The third instance added a detail worth knowing: **a query string inside a test
is indexed.** Prose documents are exempt because `.md` is not a source suffix,
so quoting an absent question in README or CHANGELOG is free — but the same
sentence used as the query argument in `tests/test_e2e_cli.py` put `oauth` into
the corpus and made that question answerable. Pick test queries out of
vocabulary nothing else claims, and check it against
`benchmarks/absent_queries.json` rather than by eye.

**Patch the binding the caller resolved, not the one you imported.** A sweep
over the `name` field weight scored identically at every setting, which is the
same signature as the default-argument trap above. The cause was different:
`benchmarks/repo_queries` had done `from ...search import build_search_index`
at import time, so rebinding it on `search` reached nothing. Third confounded
measurement in four releases, and the tell is always the same — **a table whose
rows are all equal is a broken experiment until proven otherwise**, never a
finding.

**Check the instrument before believing what it says about the subject.** A
first stemming run looked mixed, and the stemmer turned out to map `classes` to
`clas` while `class` kept its `s` — splitting the commonest word in code
instead of merging it. The measurement was fine; the thing being measured was
broken. Fix it and re-measure before drawing anything from a surprising result.

**A reasoned exemption is a claim, and claims get measured.** 1.0.0 exempted
semantic embedders from the evidence bar with an argument that was entirely
sound and a conclusion that was wrong, and it shipped because there was no
model here to check it against. When you cannot measure something, say so at
the point of the code and treat it as debt — not as settled.

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

**A dependency is a user's choice, never a default.** That rule is settled, and
it has two implementations to copy. Provider-backed embeddings arrived in 0.8.0
and a local `sentence-transformers` model in 1.1.0; both are selected by
`embedding.provider`, both are absent from `dependencies = []`, and both import
their package inside a constructor rather than at module level. The default
opens no socket, adds no dependency, and produces the same reproducible index
it always did — and two tests assert exactly that, one by making the transport
raise and one by making the optional import raise. If you touch either path,
those are the tests that matter; everything else in `tests/test_providers.py`
and `tests/test_local_model.py` is only worth having while the default still
works with the network switched off and nothing extra installed.

Agent-authored descriptions remain the cheaper answer to the same problem, and
they are not made redundant by a model: they put missing vocabulary into the
index once instead of hoping an embedding bridges it, and a human can read and
correct them.
