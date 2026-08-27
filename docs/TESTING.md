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
  move for build settings and to stay put for retrieval ones — with the
  seven-member build set pinned by name, so a new one cannot arrive uncovered —
  each setting traced to the behaviour it names, and
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
- the context budget: shown to bound what an agent reads and not only the
  string beside it, and shown to return the first result even when that result
  alone is larger than the budget;
- the reply contract: a search result shown to carry no source and to keep
  everything needed to go and look, a research reply shown to carry the code
  once with its steps reduced to id/score/matched-terms, and a stored unit
  shown to still round-trip its source through the index;
- the research early stop: shown to fire when the top result dominates and not
  when the field is close, and its margin shown to be unchanged when every
  score is scaled by the same factor -- the property the absolute threshold
  lacked, and the reason it died silently when ranking changed;
- the rung report: an undescribed repository told to describe, a described one
  told to promote, a fully documented one told it is ready, the report shown
  to be resumable rather than remembered, every rung shown to say why and how,
  and the command line and the agent protocol shown to report the same rung
  from the same implementation;
- the provider boundary: the default shown to open no socket at all by making
  the transport raise, an OpenAI-compatible stub on loopback shown to supply
  the vectors an index then records, one request shown to cover a whole batch,
  an unchanged repository shown to cost no request, a changed model shown to
  discard the old vectors, a width the settings refuse shown to be named with
  both numbers, a rejected credential shown not to be retried, a transient
  failure shown to be retried with growing backoff and then to give up rather
  than fall back, out-of-order rows shown to be reordered by the index they
  report, a credential shown never to appear in a failure report and never to
  cross a cleartext connection to anything but loopback, and semantics shown
  to make a unit retrievable that the words never reach while the hash is
  shown not to;
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

## The five rulers

`benchmarks/golden.json` grades ranking over the five-file synthetic fixture
and is asserted in CI. It is a regression tripwire, and it cannot resolve a
change to how vocabulary reaches the index: seven queries over nine units have
no resolution, and four candidate scoring changes measured over an
eight-question set all landed between five and six correct.

`benchmarks/repo_queries.json` grades seventy natural-language questions over
this repository's own source, in English and Chinese, each listing every unit
that genuinely answers it rather than one expected file — a single expected
answer once made a correct result read as a miss. Questions are keyed on file
path and declaration name, never on line, so the ruler survives the edit that
orphaned nineteen descriptions in 0.4.1. Run it with `--cold` and it grades
the same questions against units built with no description store, which is
what a repository nobody has run `describe` on contains.

`benchmarks/absent_queries.json` grades thirty questions whose answer is in
none of the three repositories, where returning nothing is the only correct
reply. The others are structurally blind to this: all of them ask questions
that have an answer, so all of them can only score whether it was found. Scored on
silence, never folded into hit@k -- averaging a question that should return
something with one that should return nothing yields a figure that improves
when either half gets worse. It read 0.000 on both repositories when it was
first run, which is the measurement that motivated the coverage bar.

Its own honesty is enforced by `tests/test_absent_queries.py`, and this is the
ruler that most needs it: the claim "nothing here answers this" rots in the
opposite direction to every other question in the suite, so the day this
repository grows a DNS resolver, a correct answer would score as a failure to
stay quiet. Each question therefore carries the `subject` vocabulary that makes
it the question it is, and a test asserts none of those words reaches a single
unit. It fired the first time it ran, on three separate causes: `webhook` and
`hostname` had been in this repository all along and were written into the
ruler by eye rather than by the check, and `cuda`/`kernels` became present
*because the source explains the coverage bar using that example*. The GPU
questions were retired for it. Documentation and ruler cannot own the same
vocabulary.

It fired again in 1.1.0, for the same reason and against the same author: a
docstring explaining the new concentration bar spelled out a worked example
using an absent question's own words, and that question promptly became
answerable. The example was removed and the docstring now says why it is
missing. **This is not a lesson that stays learned by being written down once**
— which is the argument for the mechanical check rather than for care.

`benchmarks/cold_queries.json` grades thirty-five questions about **Flask
3.1.3**, a repository nobody here wrote, indexed with no descriptions at all
and carried in this repository at `benchmarks/corpus/flask` so the ruler is
reproducible rather than dependent on somebody's checkout. It exists because
the other two cannot see what a first-time user gets. Every defect fixed in 0.6.0 was invisible to them and obvious here:
scoring by the fraction of query words present put the single largest
declaration in the top three for four questions out of six, and left `calls`
(97% of units) outweighing `daemon` (two units). Its questions are phrased in
a user's words rather than in the words of the docstring that answers them, so
a hit means retrieval bridged a paraphrase instead of echoing a string it was
handed. Through 1.3.0 the graded repository was external and the ruler was
skipped when absent; it is now vendored, so the skip cannot happen and CI runs
it on every push.

`benchmarks/cobra_queries.json` grades forty questions about **cobra v1.9.1**,
in Go, at `benchmarks/corpus/cobra`. It is the third graded repository and the
first that is not Python, which is its whole point: four constants —
`search.min_coverage`, `search.min_concentration`, `COMMON_TERM` and
`COVERAGE_FULL_STRENGTH` — were fitted on two corpora that were both Python and
both carried documentation inside the declaration, where the AST hands it over.
Go writes it above, outside the unit's span, so this ruler grades the line
scanner and the rule table on prose the parser has to pick up. None of the four
moved: both bars together still give the best silence there (0.900, against
0.833 for concentration alone). It also publishes the lowest number this
project has: **0.075 hit@1**, twenty subjects each asked in two languages, and
Chinese scores zero on all of them.

Forty questions resolves a change of several, not of one. It was chosen over
two other candidates by counting collisions with the absent ruler's subject
words — cobra 8, gin 17, chi 18 — and it still cost two question rewrites on
the day it landed.

A change that helps one ruler and hurts another is a trade, not an
improvement, and that is not visible from a single one. Three variations on
length normalisation were measured across all three before 0.6.0 settled, and
two were dropped because they moved one to four questions in both directions
at once — this instrument's noise. **Stemming is the clearest case of the
trade**: it improves both own-repository rulers and costs the foreign one 3 of
35 hit@3, which is precisely why 0.5.0's eight-question set could not settle it
and why it is rejected rather than shipped.

**Every report stamps the corpus it graded** — unit count and a fingerprint of
every unit's id and searchable text. A score from these rulers means nothing
without one: two runs of an unchanged `search.py` against the foreign
repository returned 0.257 and 0.229 hit@1, because that repository had grown by
ninety units in between. Both numbers were right and comparing them was
worthless, and nothing in the output said so. Two of the five rulers read this
repository's live working tree, so **editing the source moves the corpus and
the change at the same time**; the only sound comparison is one corpus with the
setting varied, which is why every knob `search` takes is reachable from
`evaluate()` and from a command-line flag.

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

A test declaration sometimes outranks real code: it repeats that code's
vocabulary and adds the vocabulary of its assertions, and BM25 counts that as
evidence — correctly, by its own lights. `python -m benchmarks.displacement`
measures it, holding one language-aware definition of a test file so that a
count and a claim about it cannot disagree: **9 of 215** questions across the
four positive rulers put a test at rank 1 with an accepted answer at rank 2–3,
and **none of the nine is on a foreign ruler**. So it is a property of this
repository's own two rulers rather than a general one, and a path heuristic
would fix the number while being wrong in principle, since sometimes the test
*is* the answer.

Identifier splitting was the obvious candidate fix and is measured *not* to
work; the reasoning and the numbers are in
[ARCHITECTURE.md](ARCHITECTURE.md#what-this-is-precisely).

## What the suite covers, as a number

```powershell
python -m pytest --cov=ragyourcode
```

**91%** of 2,190 statements, 198 uncovered. Per module: `search` 99%,
`workflow` 98%, `descriptions` 97%, `parser` 96%, `embeddings` and `graph` 95%,
`document` 94%, `indexer` 90%, `config` 86%, `providers` 83%, `cli` 81%.
`agentic`, `annotate`, `models` and `__init__` are complete.

The figure is published with its command and nothing is asserted on it. A
coverage floor in CI rewards tests that execute lines, and this suite's value
is in the assertions its files are named after — the uncovered remainder is
mostly `cli` argument-parsing branches and `providers` network error paths,
which is where a line-executing test would be least worth writing.

## The diagrams are checked too

`tests/test_diagrams.py` parses the four mermaid blocks in `docs/FLOW.md` and
refuses an unquoted label carrying punctuation, a `\n` where `<br/>` belongs,
an arrow naming a node no diagram declares, and a `style` line pointing at
nothing. A mermaid block GitHub cannot render fails *silently* — a grey box,
no error, and nothing in the repository notices. The blocks shipped in 1.4.2
with no gate at all. A final case feeds each check a known-bad line, because a
gate nobody has seen fail is a gate nobody has seen work; writing it caught the
first version reading `with --compact` inside a node's own label as an edge
from a node called `with`.

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

Six benchmark scripts exist and [benchmarks/README.md](../benchmarks/README.md)
is the index of them: the five rulers, the query-latency timer, the Grep
head-to-head, the scale harness and the cold-process loader. Two of the figures
this project published used to come from scripts that were never committed;
every published figure is now a command that prints its corpus fingerprint.
This section covers only the golden-fixture tripwire.

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
