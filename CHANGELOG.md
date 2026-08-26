# Changelog

Notable changes per release. Dates are the release date; measurements are from
the development machine (Windows 11, CPython 3.13) and are directional.

## 1.5.0 — 2026-08-26

Closing every item on the "could be done, has not been" list. One of them —
whether the skill fires unprompted — could not be closed and is named as such.

### A third graded repository, and the first that is not Python

`benchmarks/corpus/cobra/` is cobra v1.9.1 at commit `40b5bc1`, Apache-2.0,
602 units of Go. Four constants — `search.min_coverage`,
`search.min_concentration`, `COMMON_TERM`, `COVERAGE_FULL_STRENGTH` — had been
fitted on two corpora that were both Python and both carried their
documentation *inside* the declaration, where the AST hands it over. Go writes
it above, outside the unit's span, so this ruler grades the line scanner and
the rule table on prose the parser has to pick up.

| gate | E cobra hit@1/3/MRR | cobra silence |
|---|---|---|
| neither | 0.100/0.200/0.146 | 0.000 |
| coverage only | 0.075/0.175/0.121 | 0.767 |
| concentration only | 0.075/0.150/0.108 | 0.833 |
| **both (shipped)** | 0.075/0.150/0.108 | **0.900** |

**Not one constant moved.** Both bars together give the best silence there, as
on the other two corpora, and this one arrived four releases after the defaults
were fixed.

It also publishes the lowest number this project has: **0.075 hit@1**, against
0.200 on Flask and 0.429 here. The cause is not the language — Go documents in
one terse sentence beginning with the identifier, which the parser captures
correctly and which shares almost nothing with the words a user asks in. Cold
retrieval tracks prose density. Chinese scores 0.000 on all forty questions,
the same limit rulers A and B already report.

Chosen over two other candidates by counting collisions with the absent ruler's
subject words: cobra 8, gin 17, chi 18. It still fired the absence guard twice
on the day it landed, and both questions were rewritten rather than the corpus
exempted.

### The describe queue was an instruction to make retrieval worse

`describe status` reported 283 units pending. **270 were test functions**,
which 1.0.0 measured and rejected describing — five real answers and six false
silences. Nothing in the tool said so, so an agent working the queue to the end
would have made retrieval worse while believing the opposite.

New setting **`describe.skip`**: path patterns whose units are withheld from
the queue. Empty by default, because the measurement behind it is n=1, and set
in this repository's own `rag-your-code.toml`. What it withholds is counted and
reported as `declined`, never subtracted in silence — a queue that shrinks
without explanation reads as "nothing left to do". Patterns match with
`PurePosixPath.match`, so `tests/*.py` does not reach `tests/fixtures/**`;
describing the parser fixtures was measured to cost nothing.

`describe import` now reports the same `remaining` as `describe export` and
`bootstrap`. Two disagreeing counts is how an agent decides the queue is
unfinished and keeps asking for a batch that will always come back empty.

### Describing a well-documented declaration loses ground

Every unit the measurement says to describe is now described: 314 of 601, with
287 withheld and counted. Twelve of the thirteen genuinely undescribed units were free or
better. The thirteenth cost a graded question every way it was tried:

| `parser.py::_generic_units` | C hit@1/3/MRR |
|---|---|
| left to its generated sentence | **0.429/0.600/0.498** |
| a long authored description | 0.414/0.557/0.471 |
| a short authored description | 0.414/0.557/0.471 |

An authored description **replaces** the generated sentence, and that sentence
is the only route by which the author's own docstring reaches the weight-3
`description` field — so writing one over a declaration whose docstring already
says what a reader would search by demotes it to the weight-1 body.

**Measured and rejected:** appending the docstring after the authored text.
It fixes that declaration and costs the corpus, 0.443 → 0.414 hit@1, because it
lengthens all 314 description fields and BM25F normalises per field length.
`describe.skip` accepts `path::name` so one declaration can be recorded instead.

### The measured envelope was optimistic by more than noise

Re-measured on 10,000 synthetic units: full build **3.45 s** (was 1.84),
incremental **0.286 s** (was 0.207), speedup **12.1x**, isolated load **79.3
ms** (was 45.4), inverted index **420 ms** (was 117.7), RSS **72.2 MiB** (was
58.7), and query **15.6 ms mean / 14.6 ms median** — against a published 3.90
ms carried since before BM25F replaced the scoring it was taken under. Compact
storage is unchanged at 35.6%. Three runs bound the spread.

Query latency on this repository is **0.49 ms** median [0.45–0.58] at 601 units
`ac3ae43a33e7`, p95 0.85 ms, refusal 0.016 ms, ~30× cheaper. The same
measurement read 0.99 ms while a coverage run was in progress: *idle* is
load-bearing, and nothing in the report can see which one it took.

### Also

- **Line coverage is published**: 91% of 2,190 statements, with
  `pytest --cov=ragyourcode` as the command. Nothing is asserted on it — a
  coverage floor rewards tests that execute lines rather than tests that check.
- **The four diagrams in `docs/FLOW.md` are parsed by a test.** A mermaid block
  GitHub cannot render fails silently: a grey box, no error, nothing noticed.
  They shipped in 1.4.2 with no gate. `tests/test_diagrams.py` refuses an
  unquoted label carrying punctuation, a `\n` where `<br/>` belongs, an arrow
  naming an undeclared node, and a `style` line pointing at nothing — and feeds
  each check a known-bad case, because a gate nobody has seen fail is a gate
  nobody has seen work.
- **CI grades the third corpus** and runs its Grep baseline.
- **Two absent questions were rewritten** so no subject word of the ruler
  occurs in any of the three graded repositories.

**387 tests**, up from 356. Corpus fingerprints: **C** 601 units
`ac3ae43a33e7`, **B** `566616fbe1e7`, **A** 1,572 `5fd51169eacc`, **E** 602
`3eabaa705477`.

### Still not measured

Whether the skill fires unprompted in a fresh session. `claude plugin eval`
grades exactly this and is gated behind an account-level early access this
project does not have, so the suite cannot be run once to see whether it even
loads. It is the only claim in this repository with no command behind it, and
it is named here rather than left off the list.

## 1.4.3 — 2026-08-25

A documentation audit, run as eleven parallel readers over every live document
with each finding independently verified against the code before it was
believed. Thirty-two survived. Three of them were in the plugin's own commands.

### The commands told an agent to run things that do not exist

`/rag-your-code:index` offered `--compact` on `bootstrap`, which has no such
flag — `bootstrap . --compact` exits 2. `/rag-your-code:search` sent a reader
to `open` for results the context budget dropped; `open` is an action of the
JSON-lines `agent` protocol, not a subcommand. `/rag-your-code:status` said
"any command warns when it is stale", and none of the three commands it
prescribes does: staleness is a field (`stale_index` in `describe status`,
`stale` in `search --json`), and `config list` never opens the index at all.

### Two published numbers were wrong, not stale

The vectors are **72.1%** of an index, not 65.3% — re-derived from the two
indexes that ship (5,229,592 B against 1,459,238 B with the vectors removed;
74.8% on the Flask copy). The figure entered in 1.2.0 and was never re-measured
through four releases.

**301 units carry a written description**, not 304. The sidecar has held 303
entries since 1.4.0 and two are superseded, so no state of this repository ever
had 304; `describe status` has been answering the question all along.

### A retired subject was still being quoted as current

"On the foreign ruler a test declaration is 11 of 35 top-1 results" was
measured on the repository retired in 1.4.0. On Flask it is **0 of 35** — none
of its 1,094 test units reaches rank 1 at all. Re-derived across the three
rulers as they ship, a test displaces an accepted answer on **9 of 175**
questions, where 10 was published, and the illustrative case named in ROADMAP
(`test_readme_badge_match`) exists in no corpus a reader can open. It was a
test in the retired subject. Both examples are now live ones.

### Also

- `search.vector_recall` is gated on a semantic embedder (`search.py:509`), so
  the default hash never scans a vector. README section 11 listed the full scan
  as an unqualified current cost while section 9 already said it stays off.
- ARCHITECTURE said "there is no network code to disable". There has been since
  0.8.0; the true claim is the narrower one `providers.py` itself makes — the
  *default provider* opens no socket.
- ARCHITECTURE said the local-model arm was unmeasured "because this project
  has no key". A local model needs no key and was measured in 1.4.0.
- Four of twelve settings decide what an index contains → **seven of
  twenty-two**, the number `config.py` has carried since `embedding.provider`
  arrived. "Two rulers" → four. The agent protocol's action list was missing
  `bootstrap`. The golden fixture is nine units, not sixty. Flask is 1,572
  units, not "eighteen hundred". The parse regression was a 530-byte file at
  0.37 ms, not 441 bytes at 0.36.
- Concentration 0.1691 is *more* than a sixth, so "no declaration holds a
  sixth" contradicted the JSON block above it.
- Only one of the four rulers grades both repositories; 35 + 70 + 70 + 30 + 30
  is where 235 comes from.
- CI now runs `bootstrap`, `search --graph` and `describe promote` in the
  clean-wheel job. It claimed to run every documented command and ran none of
  those three — including the one SKILL.md prescribes first.

356 tests, unchanged. Every published figure re-reproduced: C 0.443/0.614/0.509
at `c9df00350cbd`, B 0.314/0.471/0.383 at `fb1f841fa43a`, A 0.200/0.286/0.238
at `5fd51169eacc`, silence 0.967 own and 0.833 foreign.

## 1.4.2 — 2026-08-26

Documentation, and one claim the plugin was shipping.

### The command that tells an agent to write descriptions was citing a reversed result

`/rag-your-code:describe` argued its case with "losing 31.4% vs 34.3% on an
undescribed repository". That figure came from the subject retired in 1.4.0 and
had reversed when it was re-measured against a second one: a cold index beats a
Grep loop on Flask, 37.1% to 22.9%. The command now says what is actually true
— which side wins undescribed depends on how much prose the repository already
carries — and keeps the part that does not depend on it, 22.9% against 58.6%
once descriptions exist.

This surface had been swept for fingerprints and unit counts in 1.3.0 and 1.4.0
and passed both times, because neither sweep looked for bare percentages. The
sweep was the thing that was wrong.

### docs/FLOW.md

Four diagrams: the loop a user lives in, indexing, the answering path with both
evidence bars and all four refusal reasons, and the three surfaces — four
commands, one skill, and the nine-action JSON-lines protocol. Nothing in it is
a figure that cannot be re-derived from `benchmarks/`.

### Also

- The README says how to *update* the plugin, not only how to install it.
  `claude plugin update rag-your-code` is refused with `Plugin "rag-your-code"
  not found`, which reads like the plugin is missing rather than like the
  argument is short: it takes the full `name@marketplace` id, and the
  marketplace cache has to be refreshed first or the check finds nothing new.

356 tests, unchanged: the only `.py` change was the version constant, which
creates no indexed unit, so every corpus fingerprint published in 1.4.1 holds.

## 1.4.1 — 2026-08-26

Found by installing 1.4.0 from PyPI into a clean environment and using it on an
unfamiliar repository, which is the one thing no test in this project does.

### A result printed the author's docstring twice

A generated description ends with the author's own docstring, because that is
how a docstring becomes searchable. The block then printed the source below it,
which contains the same docstring. On Flask, **2,381 of 3,382 characters of
prose header were a verbatim repeat of the code beneath it** — a fifth of
everything a query returned, paid for twice.

It never showed on this repository's own rulers: the descriptions here are
agent-written and are *not* in the source, so there was nothing to duplicate.
It took a corpus whose authors wrote docstrings, which arrived in 1.4.0.

`_visible_description` drops the quoted half when the code below already shows
it, and keeps it when it does not — an authored description is the one part of
a block a reader cannot recover by reading the code. `searchable_text` is
untouched, so the docstring stays exactly as findable and no ruler moved.

The saving is not in characters, it is in answers. At the same 12,000-character
budget:

| | before | after |
|---|---|---|
| declarations delivered, Flask, 30 answered | 92 | **119** |
| declarations delivered, this repo, 60 answered | 305 | **323** |

The budget was already the binding constraint, so removing the duplicate does
not make a reply smaller — it makes it carry a third more distinct code.

### One marker, one home

`"Documented intent:"` was spelled out as a literal in three modules that have
to agree on it: `annotate` writes it for Python, `parser` writes it again for
the other fourteen languages, and `document` looked for it to decide which
declarations are undocumented. It now lives in `annotate` and the other two
import it. A string three modules must agree on is a rename away from a silent
disagreement, and the thing it decides — whether a declaration counts as
documented — has been wrong before.

### Also

- The comparison is against whitespace-collapsed source, because the quoted
  docstring is re-flowed onto one line where the code has it indented across
  many. The first attempt matched nothing at all for a subtler reason: the
  description's sentence joiner appends a period the source does not have.
- Republished with fresh fingerprints: B 584 `fb1f841fa43a`, C 584
  `c9df00350cbd`. Ruler A is untouched at `5fd51169eacc` — the vendored corpus
  does not move when this repository does, which is the point of vendoring it.
- Latency on a quiet machine: median 0.61 ms, p95 1.09 ms, refusal 0.017 ms.

356 tests (from 354; **+2 added, 0 removed** by node-id set diff against
v1.4.0). Both assert the rendering: that the docstring is printed once and by
the code, and that a written description the source does not carry survives.

## 1.4.0 — 2026-08-26

The foreign ruler graded a repository on one machine. It is now a copy of
Flask 3.1.3 carried in this repository, and repeating the measurements against
a corpus that holds still reversed two published conclusions.

### The corpus is in the repository

`benchmarks/corpus/flask/` is Flask 3.1.3 at commit `22d9247`, BSD-3-Clause,
`docs/` and `.git/` omitted and the rest as published — 1,572 units of code
nobody here wrote, indexed with no descriptions, which is what a first-time
user's index looks like. `rag-your-code.toml` at the repository root keeps it
out of this project's own index; without that, those units would enter two
rulers that measure retrieval over *this* repository
and falsify a third that asserts nothing here answers thirty questions.

Through 1.3.0 the subject was a checkout that changed by the hour. It cost:
two graded questions silently pointing at a renamed declaration, a published
score that moved 0.257 → 0.229 with no code change, and a model comparison
taken against two states of it at once.

Three things became possible the moment it was vendored:

- **CI runs the foreign ruler**, the foreign absent ruler and the foreign
  head-to-head. None of the three could run in CI before.
- **The absence claim became a test.** `tests/test_absent_queries.py` now
  checks the fourth ruler's vocabulary against the vendored corpus as well as
  this repository — the half that could only be asserted before. It caught a
  generic English verb standing in for a specific term in one question's
  subject list on the first run.
- **The model comparison became attributable**, and inverted.

### The local model is worse or identical on every ruler

1.1.0 published the comparison as "better on every positive ruler". Repeated
with both arms against one fingerprint per row:

| ruler | corpus | signed hash | MiniLM, local |
|---|---|---|---|
| A foreign, cold (35) | 1,572 `5fd51169eacc` | **0.200 / 0.286 / 0.238** | 0.171 / 0.257 / 0.214 |
| B own, cold (70) | 581 `8e1e71942c1c` | 0.314 / 0.471 / 0.383 | 0.314 / 0.471 / 0.383 |
| C own, described (70) | 581 `978a1d48a82a` | **0.443 / 0.614 / 0.507** | 0.429 / 0.600 / 0.500 |
| D silence, own / foreign | as above | 0.967 / 0.833 | 0.967 / 0.833 |

The A-row gain was a repository that had grown between the two runs. The B and
C gains were one or two questions, inside the noise of a two-unit change to the
corpus, and they reverse sign under it. The extra stays shipped, with its cost
stated: it buys the cross-language and paraphrase pairs the hash scores zero
on, and nothing these rulers can see.

### Concentration does not subsume coverage after all

On the retired subject the two bars were interchangeable and the README said
so. On Flask they are not: both together silence **0.833** of the foreign
absent questions, against 0.800 for concentration alone and 0.733 for coverage
alone. One question, and the first measurable reason in four releases to keep
both.

A sweep says the shipped 0.28 stays. Every step up buys foreign silence out of
the answers — at 0.50 the foreign absent ruler is silent on all thirty while
ruler A falls to 0.086 hit@1 from 0.200, B to 0.214, C to 0.329. The default
was chosen before this corpus existed and survived meeting it.

### Which side wins against Grep depends on the repository

Through 1.3.0 the README said flatly that a Grep loop wins on an undescribed
repository. That was one subject generalised. On Flask it reverses: **37.1%
right file first against Grep's 22.9%**, and 57.1% against 45.7% in the top
three, with no description added. The cold index there is retrieving against
docstrings the author wrote; on the previous subject, a tool with terse
comments and long identifiers, there was nothing for it to retrieve against and
Grep won by a similar margin.

What does not depend on the subject is what descriptions buy: on this
repository, 58.6% against 22.9%, and half the payload.

Both sides decline exactly the same five of the 35 foreign questions, and they
are the five Chinese ones — a Chinese word is neither a substring of English
source nor a token in an index built from it.

### Also

- **Foreign silence is 0.833**, down from 0.933 on the retired subject, and the
  cause is a limit rather than a defect: a word counts as evidence unless it
  occurs in more than 5% of units, which makes `how`, `when`, `does` and `are`
  ubiquitous here — 301 units carry written prose — and discriminating across
  1,572 units of short, undocumented methods.
- **The absence guard fired for the fourth and fifth times**, both on the
  author. Once on a declaration named after the statistic it computes, once on
  a docstring explaining that very fix. `CONTRIBUTING.md` carries both rules: a
  declaration name is indexed, and so is a docstring.
- `benchmarks/corpus/README.md` carries the provenance, the licence, and the
  procedure for bumping the tag — which invalidates every figure taken against
  the old one, so it is written down rather than left to judgement.
- `compileall` in CI skips the vendored corpus; gating on somebody else's
  release is not this project's business.

354 tests (from 353; **+1 added, 0 removed** by node-id set diff against
v1.3.0). The addition is
`test_no_subject_of_an_absent_question_exists_in_the_vendored_corpus`, which
was unwritable until the corpus lived here.

## 1.3.0 — 2026-08-25

1.2.1 declared the roadmap empty. Checking that claim by running the commands
turned up four published figures with no command behind them, and one ruler
that had stopped running altogether.

### The Grep head-to-head is now a command

README section 7 — the strongest claim the project makes, that retrieval beats
an agent driving Grep once a repository has been described — was published from
a script that was never committed. Nothing in it could be checked, and "a Grep
loop" had no definition precise enough to argue with.

**`benchmarks/grep_baseline.py`** is that script, written to the description in
the README and then measured. It takes the query's words, drops the ones the
corpus itself shows are everywhere, runs one substring search per remaining
word over exactly the files the index was built from, ranks each file by how
many distinct words hit it, and breaks ties on path. Both arms are scored at
file granularity, and both payloads are counted in characters — the old table
counted one side in lines and the other in characters, which compares nothing.

Reconstruction reproduced this side's figures exactly (58.6% / 75.7% / 60 of 70
answered) and moved the baseline's, which is the expected shape: the ranked arm
was always a call into shipped code and the baseline never was. The qualitative
result is unchanged and both directions still hold — Grep wins on an
undescribed repository, 40.0% to 28.6%; on a described one it is 22.9% to
58.6%. The payload advantage is a factor of 1.7, not the order of magnitude the
old mismatched units implied.

### Latency is a command too, and was quoted to more figures than it has

`0.83 ms / p95 1.68 ms` came from the same kind of uncommitted script, on a
557-unit corpus that no longer exists. **`benchmarks/query_latency.py`** repeats
the whole measurement and prints the spread, because a single run does not have
the precision three figures claim.

Ten invocations across one hour on one machine put the median anywhere from
0.62 to 1.44 ms and p95 from 1.09 to 7.34 ms, depending on nothing but what
else the machine was doing. The old figures sit inside that range — they were
unfalsifiable rather than wrong, which is the harder defect to notice. The
README now publishes two significant figures with the range beside them,
0.65 ms and p95 1.13 ms over five consecutive runs on the final corpus.

The README's "a factor of forty" was right and its own table was not: the two
rows above it divided to twenty-eight. The script derives the ratio now, and it
comes out at 35.

### Ruler A had stopped running

Two questions in `cold_queries.json` pointed at `read_guard.py::_classify_change`
in the foreign repository. That declaration had moved to
`lib/editscale.py::classify_change`, and the ruler's integrity check refused to
grade rather than scoring the questions as misses — which is exactly what that
check exists for, and it had been failing unnoticed because nothing ran it.

Repointed, and re-measured on a foreign corpus that has grown from 1,267 to
1,345 units: A is 0.229 / 0.371 / 0.286, where 0.400 and 0.300 were the
corpus, not retrieval. B, C and both silence rulers are unchanged to three
decimals.

`cold_queries.json` now records what it was graded against: commit
`080424eab89b` plus 18 uncommitted files, 1,345 units, fingerprint
`471b78f9f806`. The commit does not identify that corpus and no commit can.

### Every published table now carries its corpus

The README has said since 1.1.0 that "every report carries a fingerprint of the
corpus it graded". Every report did. **None of the tables printing those
reports did**, which is the half that a reader sees. They do now, and the
ablation table was re-measured to have one — the coverage-only row silences
0.600 where it silenced 0.700, from the same bar on a larger repository.

The visible cost of not having done this: the local-model comparison in the
roadmap has an A row whose two arms were taken against `ecd28fce38a2` and
`9834c411583e`, two states of a repository being edited while the script ran.
It is left in place with the confound named. B and C share a fingerprint across
both arms and remain attributable.

### Counts that had never been re-derived

- `search.py` said "all 32 questions in `benchmarks/absent_queries.json`". That
  file has held 30 since its only commit; it was never 32.
- `tests/test_evidence.py` carried the same 32.
- `config.py` said `min_coverage` was measured "across two repositories, two
  languages and 126 questions" — no question set here has ever summed to 126 —
  and that it "silences 47%", which measures 0.600 today.
- Its `min_concentration` note said the bar "roughly halves" the answers that
  should not have been given, while the ablation table two documents away said
  an order of magnitude.

All four now name the command or the table instead of a number, which is the
rule `repo_queries.py` had already written down and this file had not followed:
a figure in prose is a claim nothing checks.

### The absence guard fired a fourth time

`query_latency.py` named a helper after the statistic it computes. That word is
a subject of a question the absent ruler asserts nothing here answers, and a
declaration named after it puts it in the index. `tests/test_absent_queries.py`
caught it before anything was published — the first firing on a declaration
name rather than on a query string inside a test.

### Also

- **`benchmarks/README.md`** lists all six scripts and the command for each. It
  had documented two, neither of them the four rulers.
- Ruler A's documented command no longer writes an index into the repository it
  grades; a ruler should not need write access to its subject.

353 tests (from 352; **+1 added, 0 removed** by node-id set diff against
v1.2.1). The addition is
`test_metadata.py::test_every_benchmark_script_is_listed_in_its_own_index`,
which fails in both directions: a script in `benchmarks/` its own README does
not name, and a command in that README naming a script that does not exist.
Discovery by glob, so the seventh script cannot be the one nothing checks.

## 1.2.1 — 2026-08-25

A documentation correction, and the claim it corrects had been shipped in three
releases.

Since 1.0.0 the roadmap has carried a section titled "the one thing a command
cannot check", saying that whether the bundled skill fires unprompted "needs an
interactive session with a model deciding, which no test in this repository can
stand in for". **That was wrong.** `claude plugin eval` runs eval cases against
a plugin, and its own `--ablation` help names the mechanism exactly: graders
marked with-only, including `tool_used: Skill`, are a plugin-fired indicator,
against a no-plugin baseline arm.

The honest status is **measurable, and not measured**, for two reasons that are
now stated instead of the false one:

- `claude plugin eval` reports `plugin eval is currently in early access` on
  this account, so neither it nor its `init` scaffold runs. The gate is a
  server-side entitlement; there is no local flag.
- The case schema is not publicly documented — the plugins reference covers
  every other component and not this one — leaving three fragments of `--help`
  text as the only description.

No suite was written on that basis. One assembled from guessed field names
could not be executed even once to see whether it loads, and a suite that
silently fails to load reads as a gate while checking nothing: the exact
failure this project shipped twice with an install line and once with a
threshold sweep that scored every setting identically.

What would close it is recorded in `docs/ROADMAP.md`. Since 1.2.0 it also
matters less: four commands give a deterministic entry path that does not
depend on a model choosing to fire anything.

No code changed; 352 tests unchanged.

## 1.2.0 — 2026-08-25

Every release through 1.1.0 improved retrieval and none of them made it
**findable**. The plugin shipped one skill and nothing else, so every path into
it depended on that skill firing on its own — which `docs/ROADMAP.md` itself
lists as the one property no command in this repository can verify. A user who
installed it had no entry point they could discover, and the largest available
lever on retrieval quality, writing descriptions, was step 5 inside a page that
only loads once a model has already decided to search.

352 tests (from 346; **+6 added, 0 removed** by node-id set diff against v1.1.0).

### Added

- **Four commands**, the surface a user can actually find:

  | | |
  |---|---|
  | `/rag-your-code:index` | index, and report which rung this repository is on |
  | `/rag-your-code:search` | ask in plain language; cite `path:line`; act on a refusal correctly |
  | `/rag-your-code:describe` | the description loop, with the brief and the measured reason it matters |
  | `/rag-your-code:status` | stale? coverage? which embedder? what next? |

  Measured with `claude plugin details` on an installed copy: **~249 always-on
  tokens**, up from ~39 — the skill ~30, each command ~50–60 — and 590 to 2,400
  only when one fires. The increase is the honest price of being findable, and
  it is stated rather than buried. An MCP server was rejected for the same job:
  tool schemas are always-on whether or not anyone searches, and the JSON-lines
  `agent` protocol already serves the subprocess case.

- **The command line says when descriptions are the missing piece**, which
  costs nothing at all and reaches a person who knows about neither the skill
  nor the commands. When a search is **refused** and declarations are still
  undescribed, it says how many and names the next step.

  Tied to a refusal rather than to a weak-looking result, deliberately: "the
  results looked poor" would need a threshold on a score — the failure
  `confidence_threshold = 0.8` already demonstrated — while a refusal is a fact
  and is the moment somebody has actually lost something.

  It stays silent on `matched_terms_are_scattered`, because that reason means
  the words are here but never together, which is what a question about a
  subject the repository does not implement looks like; advising more
  descriptions there would be advice that cannot work. It stays silent once
  nothing is undescribed. **The JSON reply gains nothing** — an agent branches
  on `diagnosis` and does not need prose about a field it already has.

### Gates

Both new behaviours were verified **RED against a deliberately broken nudge**
before being trusted green, because a test that only passes on fixed content
cannot tell a working check from a deleted one.

Command files join the documented-surface checks **by discovery rather than by
name**, so a fifth command cannot become the one file nothing checks — which is
exactly how an install line naming a package index this project does not
publish to shipped twice. Every command must carry a loadable `description`,
and every `/rag-your-code:…` a document offers must exist, in both directions.

The protocol-action anti-vacuity guard moved from per-file to per-set: a command
file documents the command line and has no reason to mention the subprocess
protocol, and requiring one from every document would have made that check pass
only by forcing irrelevant JSON into user-facing pages.

## Earlier releases

1.1.0, 1.0.0 and 0.8.0 are in [docs/CHANGELOG-1.0.md](docs/CHANGELOG-1.0.md);
0.7.0 and everything before it in
[docs/CHANGELOG-0.x.md](docs/CHANGELOG-0.x.md). Both were moved unedited when
this file reached its size budget, and are worth reading for the rulers'
origins and for the changes measured and rejected along the way.
