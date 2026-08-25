# Testing and evaluation

## End-to-end coverage

`tests/test_e2e_cli.py` runs the real subprocess entry point through `index`,
`search --json`, `annotate`, and `agent`. It also edits a source file and
asserts that the old index reports `stale: true`; stale annotation generation
is rejected with exit code 2. The agent protocol test covers malformed JSON
recovery and a subsequent valid request.

## Full debug coverage

The test suite currently covers:

- Python AST units, nested qualified names, imports, calls, serials, and vectors;
- generic parser declarations across Ruby, Kotlin, Swift, PHP, Go, Rust, Shell,
  C# and JavaScript, including a no-trailing-newline edge case;
- JSON index round trips and vector persistence;
- zero-result limits and agent output contracts;
- schema 1 migration, embedding-version invalidation, global serial stability,
  compact vector sidecars, atomic cleanup, and explicit degraded state;
- conservative call/import/containment graph edges, graph evidence and ARAG
  step/stop contracts;
- malformed/non-object requests, numeric bounds, path traversal and missing
  index errors;
- plugin-facing CLI help and source-preserving annotations;
- a crafted `vector_store.path` in a shipped index failing to delete a source
  file, and orphaned sidecars being reclaimed;
- the agent subprocess answering a UTF-8 CJK query and echoing an
  outside-the-codepage character on a simulated non-UTF-8 console;
- the daemon's failure contract: non-finite numeric fields, an injected
  unanticipated handler exception, the preserved `invalid_request` code, and
  `open` bounded by size as well as by line count;
- retrieval correctness: `limit` filled when a rare term joins common ones,
  every lexically matching unit reachable, an index self-reporting stale after a
  write between parse and publish, and call edges omitted for foreign module
  prefixes while local-module and receiver calls still resolve;
- configuration: every default restated against the 0.3.0 literal it replaced,
  nine kinds of bad file refused with a reason, the build fingerprint proved to
  move for the four settings that decide what an index contains and to stay put
  for the eight that do not, each setting traced to the behaviour it names, and
  `config set` shown to preserve every comment it does not consume;
- descriptions: an authored one reaching three queries the generated one cannot
  (including a Chinese query), a source edit removing it from use while the
  entry survives on disk, a mismatched digest never applied, an index predating
  the feature not reported stale, every rejection reason, and a description
  taking effect inside the same agent session;
- documentation harvesting across seven language families, with a licence
  header, commented-out code and a separator rule each shown *not* to be
  harvested, an annotation shown not to hide the block above it, and prose
  wrapping on a comma shown to survive;
- the parser as a recorded input: a changed parser forcing a rebuild, an index
  predating the field rebuilding once, and the fingerprint being derived from
  the module rather than declared;
- ranking: a word in almost every unit shown unable to decide an ordering, a
  two-hundred-line declaration shown not to win on size in a corpus large
  enough that no vector score is computed, the same word shown to count for
  more in a name than in a body, every searchable field shown to carry a
  weight, and the evidence list shown to survive postings that now carry a
  weight beside each id;
- the context budget: shown to bound the results an agent reads and not only
  the string beside them, and shown to return the first result even when that
  result alone is larger than the budget;
- promotion: a patch `git apply` actually applies for four language families,
  every supported language having a documentation convention, an already
  documented declaration left alone, CRLF endings preserved, several
  insertions in one file not shifting each other, and — the defect this
  guards — promoting a description not discarding it.

Subprocess tests pin `PYTHONPATH` to `src/` through `cli_env()`, so they
exercise the working tree rather than whatever copy pip has installed.

Two invariants are asserted rather than assumed. `index.suffixes` must equal
the parser's own dispatch table, because a suffix on only the walker's list is
read, parsed to nothing, and reported as a clean index. And the 3.10 TOML
reader is checked against `tomllib` over sixteen inputs on every version that
ships one, so the fallback cannot drift away from the real grammar in silence.

## The three rulers

`benchmarks/golden.json` grades ranking over the five-file synthetic fixture
and is asserted in CI. It is a regression tripwire, and it cannot resolve a
change to how vocabulary reaches the index: seven queries over sixty units
have no resolution, and four candidate scoring changes measured over an
eight-question set all landed between five and six correct.

`benchmarks/repo_queries.json` grades seventy natural-language questions over
this repository's own source, in English and Chinese, each listing every unit
that genuinely answers it rather than one expected file — a single expected
answer once made a correct result read as a miss. Questions are keyed on file
path and declaration name, never on line, so the ruler survives the edit that
orphaned nineteen descriptions in 0.4.1. Run it with `--cold` and it grades
the same questions against units built with no description store, which is
what a repository nobody has run `describe` on contains.

`benchmarks/cold_queries.json` grades thirty-five questions about
**cc-enforcer**, a repository nobody here wrote, indexed with no descriptions
at all. It exists because the other two cannot see what a first-time user
gets. Every defect fixed in 0.6.0 was invisible to them and obvious here:
scoring by the fraction of query words present put the single largest
declaration in the top three for four questions out of six, and left `calls`
(97% of units) outweighing `daemon` (two units). Its questions are phrased in
a user's words rather than in the words of the docstring that answers them, so
a hit means retrieval bridged a paraphrase instead of echoing a string it was
handed. The graded repository is external: when it is absent the ruler is
skipped, never silently scored as zero.

A change that helps one ruler and hurts another is a trade, not an
improvement, and that is not visible from a single one. Three variations on
length normalisation were measured across all three before 0.6.0 settled, and
two were dropped because they moved one to four questions in both directions
at once — this instrument's noise.

`tests/test_repo_queries.py` guards the rulers rather than the score. Every
acceptable answer must name a unit that exists, both languages must be
present, ids must be unique, and at least one question must still fail — a
ruler everything passes cannot measure an improvement. The score itself is
asserted nowhere: it falls whenever the repository gains code nobody has
described yet, which is ordinary development and not a regression. It caught a
rename the moment it happened, loudly, instead of quietly scoring lower. The
one comparison that *is* asserted is the relative one: written descriptions
must beat generated ones, which used to be a comment quoting two numbers that
had both gone stale.

### What the ranking still gets wrong

A test declaration often outranks the code it tests. It repeats that code's
vocabulary and adds the vocabulary of its assertions, and BM25 counts that as
evidence — correctly, by its own lights. On the foreign ruler this is 11 of 35
top-1 results, improved from 14 but not solved. A path heuristic would fix the
number and be wrong in principle, since sometimes the test *is* the answer.

Identifier splitting was the obvious candidate fix and is measured *not* to
work; the reasoning and the numbers are in
[ARCHITECTURE.md](ARCHITECTURE.md#what-this-is-precisely).

## Tests that read the documentation

`tests/test_metadata.py` treats the documentation as something to execute
rather than to trust. It asserts that every subcommand and protocol action
named in `README.md` or `SKILL.md` exists, that every documented `pip install`
names a source that resolves — the project's own distribution name being
allowed only while a workflow here actually uploads under it — and that the
fixture counts stated in prose match `expected.json`.

Each of those guards exists because the claim it checks had already gone wrong.
The install line was wrong in two consecutive releases, both times because
nothing ran it; the exclusion count was wrong because nothing counted it. A
number in a sentence is exactly the kind of claim no gate looks at, until one
does.

## What the suites do not cover

Stated plainly, because a green suite says nothing about what it never runs.

- **Whether the bundled skill fires on its own.** Installation is verified end
  to end, and the commands the skill prescribes are executed verbatim by CI,
  but whether an agent decides to load the skill in a fresh session is a
  property of the host, not of anything here.
- **Description quality.** Coverage is measured and applicability is enforced;
  whether a written description is a *good* one is judged only by the
  seventy-question ruler, whose questions were written by the same party that
  wrote the descriptions. That measures "can retrieval find the thing the
  author meant", not "is the author's meaning discoverable by a stranger".
  The cold ruler removes one half of that circle — nobody here wrote the code
  it grades — but not the other: the questions are still ours.
- **Retrieval on a repository with no English in it.** Both cold rulers score
  Chinese questions at zero, because the code they grade contains no Chinese
  for a Chinese query to match. That is a property of those repositories, not
  a measurement of the CJK path, and nothing here covers the case of a
  codebase commented in Chinese and queried in English.
- **Repositories much past 10,000 units.** The measured envelope is the
  synthetic benchmark's; beyond roughly 100k units the JSON storage layer is
  expected to be the limit, and that expectation is untested.

Run:

```powershell
pytest -q
python -m compileall -q src tests benchmarks
```

`pip check` may report conflicts from unrelated globally installed packages;
this project has no runtime dependencies and its wheel builds with
`python -m pip wheel . --no-deps`.

## The multi-language ruler

`tests/fixtures/languages/` holds 15 realistic fixture files across JavaScript,
TypeScript, Go, Rust, Java, Kotlin, C#, Scala, C, C++, Ruby, PHP, Swift and
shell, plus `expected.json`: 96 expected units (91 core, 5 stretch), 237
negative cases, and 89 constructs the spec deliberately excludes with the rule
that excludes each one.

Those five numbers are asserted against `expected.json` itself by
`test_the_documented_fixture_counts_are_the_real_ones`. The exclusion count
read 96 until 0.4.2 — copied from the count of expected units — because
nothing compared it to the data.

`SPEC.md` states the eligibility rule once — *a unit is a named declaration that
owns a body span* — so "what counts as a unit" is not re-invented per language.
It matches what the Python path already does: `parser.py` emits units only for
`FunctionDef`, `AsyncFunctionDef` and `ClassDef`, never for a module constant or
a class attribute. The one deliberate departure is a binding whose right-hand
side is syntactically a function literal, because `const f = () => {}` is how
JavaScript and TypeScript declare most functions.

This ruler was written **before** the parser rewrite it grades. Written after,
it would have encoded whatever the new parser happened to do. Measured against
the parser as of P2, over the 91 core entries: 28 found (31%), 4 with the
correct `start_line` (4%), 5 with a usable signature (5%), and 24 phantom units
invented from control flow, string literals and commented-out code.

`PENDING_PARSER_REWRITE` in `tests/test_language_fixtures.py` was the known-gap
ledger — 57 of 75 parametrised cases. Its marks were `strict`, so every entry had
to be removed by a case that actually started passing; the parser rewrite emptied
it. All 91 core entries are now found, with the correct `start_line` and a usable
signature, no phantom units and no SPEC-excluded construct indexed. Three of the
five `stretch` entries are reached; the remaining two stay recorded as documented
limits with the reason each needs cross-line context.

## Baseline versus hybrid

Run:

```powershell
python -m benchmarks.run_benchmark --output benchmark-result.json
```

The source-controlled [golden set](../benchmarks/golden.json) contains seven
queries, including paraphrases that are deliberately harder than exact symbol
lookups. The benchmark compares lexical-only retrieval to cached lexical plus
vector retrieval and reports precision@3, recall@3, top-1 accuracy, MRR,
mean/P95 query latency, parse/embed latency, and inverted-index build latency.

Golden tests are warranted now. Retrieval ranking is a user-visible contract,
and the paraphrase queries caught a real regression where the first hybrid
scoring rule reduced top-1 accuracy from `1.0` to `0.857`. Making lexical
evidence dominant restored `1.0` without giving up vector tie-breaking. Keep
the set small and reviewable; add repository-specific cases before changing
the embedding provider or ranking weights.

The graph fixture also measures a cross-function workflow. Hybrid retrieval
has related-callee recall@3 of `0.0`; bounded graph expansion recovers the
called function at recall@3 `1.0`, with the `calls` path attached as evidence.
