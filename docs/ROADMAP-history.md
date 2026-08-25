# Roadmap history — the v0.2.0 audit through 0.7.0

Split out of [ROADMAP.md](ROADMAP.md) when that file reached its size budget.
Nothing here was edited in the move. It is the record of the five root causes
the audit produced, the eight phases that closed them, and the releases that
followed — including every change measured and rejected along the way.

## Root-cause grouping

| Root cause | Symptoms it produces | Phase |
|---|---|---|
| **A.** `FUNCTION_RE` is one whole-file regex doing five jobs at once (locate, name, dispatch by language, delimit scope, imply the line number) | catastrophic backtracking; wrong `start_line`; empty `signature`; cross-line swallowing; TypeScript yielding zero units | P3 |
| **B.** Line model disagrees with the tokenizer: `str.splitlines()` breaks on `\x0b \x0c \x1c-\x1e \x85    `, `ast` counts only `\n \r\n \r` | Python function bodies silently truncated or lost | P3 |
| **C.** `write_index` trusts a path read out of the index file it is replacing | running the documented `index` command deletes an arbitrary in-tree file, exit code 0 | P1 |
| **D.** Process I/O follows the OS locale codepage instead of the protocol's encoding | the long-lived `agent` subprocess dies on non-ASCII output; CJK queries silently mis-decode and return `[]` | P1 |
| **E.** The vector-candidate set replaces the lexical candidate set instead of narrowing what gets a cosine score | `--limit 8` returns 1 result on this repo's own 116 units | P4 |

Measured evidence for each is recorded in the phase sections below.

## Design principles

1. **One root cause, one change.** Seven symptoms above collapse into five
   edits, not seven patches.
2. **Make the error structurally impossible**, do not add a check for it. A
   line number that *is* the loop index cannot drift; no assertion required.
3. **Data over code.** Adding a language becomes a table row, not a regex edit.
4. **Build the ruler before reshaping the thing being measured.** The
   multi-language golden set (P2) lands *before* the parser rewrite (P3).
5. **The contract does not move.** `CodeUnit`, index schema 2, and the
   JSON-lines agent protocol are unchanged throughout; every fix sits beneath
   them.

## Phases

### P0 — Foundation *(landed)*

Version control, ignore rules, removal of stray run artifacts, this document.
Not a polish item: without git, no later phase is revertible or bisectable.

### P1 — Stop the bleeding (root causes C, D) *(landed)*

Two edits, each deleting a wrong assumption rather than adding machinery.

- **C:** the sidecar to delete is derived from this run's own naming scheme, not
  read out of the previous index. Measured before: a repository shipping a
  crafted `.rag-your-code/index.json` whose `vector_store.path` names any file
  under the index directory causes `index` to delete that file and report
  success (`exit code = 0`, `PRECIOUS.py exists = False`).
- **D:** `main()` pins stdin/stdout/stderr to UTF-8. Measured before: on a
  cp936 console (`sys.stdout.encoding == 'gbk'`), one non-representable
  character in a result kills the agent subprocess; a UTF-8 CJK query is
  mis-decoded and returns `results: []` with exit 0.

### P2 — Build the ruler *(landed)*

The golden set currently holds seven queries, all resolving to Python units, so
the parser can regress arbitrarily on the seven other languages README.md names
while the suite stays green. This phase adds per-language fixtures with expected
unit names, line ranges, and signatures — the ground truth P3 is graded against.

Ordering is deliberate: written after P3, these fixtures would encode whatever
the new parser happens to do.

### P3 — Parser: three-layer rewrite (root causes A, B) *(landed)*

Replace the single whole-file regex with three separated layers:

```
Layer 1  line scanner       one match attempt per line; line number is the loop index
Layer 2  language rule table  per-language anchored declaration patterns
Layer 3  span closer        brace balance / `end` keyword / next-declaration fallback
```

Because a pattern now sees exactly one line, the cross-line quantifiers that
caused four of the five symptoms (`[^;]*` consuming newlines, `(?:...|\s)+`
consuming blank lines) cannot exist. The backtracking input size drops from
"file" to "line".

Measured before, on this machine:

| Input | Result |
|---|---|
| `.js`: one function + N whitespace-only lines | n=40 (230 B) 0.256 s · n=60 (330 B) 1.295 s · n=80 (430 B) 4.764 s · n=100 (530 B) **12.630 s** (~n^4.3) |
| idiomatic TypeScript class, 3 methods + constructor | **0 units** |
| `.js`, 4 functions separated by one blank line | 3 of 4 have a wrong `start_line` and an empty `signature` |
| `.py` with `\x0c` inside a string literal | `alpha` source truncated mid-literal; `beta`'s entire body lost |

Layer 3 is conservative by design: brace balancing for `{}` languages, the `end`
keyword for Ruby, and the existing next-declaration fallback where neither
applies. Its limits are documented rather than guessed at.

### P4 — Retrieval correctness (root cause E) *(landed)*

- Candidate set becomes the full lexical set; the selective set decides only
  *which candidates additionally receive a cosine score* — the intent already
  stated in `search.py`'s own comment. Measured before: 116 units, threshold 64,
  `search('sqlite function using json', limit=8)` returns **1** result.
  The latency reason for the current shape is real (a naive full scan measured
  0.49 ms -> 27.53 ms at 10k units), so the fix must keep the selective set for
  vector work while restoring lexical recall.
- Graph edges resolved by bare leaf name currently contradict this module's own
  "omitted rather than guessed" contract; leaf fallback gets constrained.
- `build_units` and `write_index` walk the tree separately, so a write landing
  between them records a fresh hash beside stale units and every later
  incremental run reuses them while reporting `stale: false`. One snapshot,
  shared.

### P5 — Agent protocol robustness *(landed)*

Catch-all around the request loop (a single `1e400` in a request currently kills
the subprocess), a real output bound on `open`, and an ignore list for it.

### P6 — Release bar *(landed)*

`LICENSE` (pyproject declares MIT with no license text in the tree or the built
wheel), `.claude-plugin/marketplace.json`, an install step in `SKILL.md` (which
today tells an agent to run a module that nothing installs), pyproject
classifiers/URLs/dev extra, `py.typed`, `requires-python` corrected to match the
`tomllib` import in the test suite, and CI. CI lands last so it gates the fixed
suite rather than the broken one.

## Decided since

The plugin manifest and marketplace entry now carry `homepage` and `repository`
pointing at `https://github.com/skymanbp/rag-your-code`. They were left empty
through P6 because the repository had no remote and a URL that resolves to
nothing is worse than an absent field; the remote now exists.

## Distribution, closed

Every path a stranger can take to this project has been walked end to end, on
a machine other than the one that built it where that was possible.

| path | verified by |
|---|---|
| GitHub repository, CI on 3.10-3.13 x Linux/Windows | 11 of 11 jobs green |
| release artifacts | downloaded from the release page, installed into a clean environment, documented commands run |
| PyPI (`pip install rag-your-code`) | installed by name into a clean environment; a CI job now runs the skill's own install line verbatim |
| Claude Code plugin | installed via `/plugin marketplace add` + `/plugin install`; present in both local registries; `claude plugin details` reports one skill, ~39 always-on tokens |

The one thing still unverified is whether the skill fires on its own in a fresh
session, which needs an interactive session rather than a command.


## 0.4.0

0.3.0 closed the gap between what the code claimed and what it did. 0.4.0 is
the first pass that adds a claim, and it rests on one measured fact. Both
phases have landed; what each turned up while being built is recorded below.

### The measurement that motivates it

The embedder is a signed feature hash (`embeddings.py`), so `cosine` is a
normalised measure of *token overlap*. It carries no semantics whatever:

| pair | cosine |
|---|---|
| `retry failed card charge` vs itself | 1.0000 |
| `sum two numbers` vs `add a pair of integers` | **0.0000** |
| `计算两个数的和` vs `sum two numbers` | **0.0000** |
| `sum two numbers` vs `delete the user database table` | 0.0000 |

A real embedding model scores row 2 around 0.8. Row 4 is the control: a synonym
pair and an unrelated pair are indistinguishable, because zero shared tokens is
zero either way.

The golden set's paraphrase queries still reach top-1, but on a thin margin
supplied by the developer's own docstring: `check whether a credential is valid
and has not expired` matches `verify_session_token` on the single content word
`expired` (0.3293) ahead of `retry_charge` (0.2401) — whose only matched terms
are the stopwords `a` and `and`.

### P7 — Configuration layer *(landed)*

Seven classes of tunable are module constants today and can only be changed by
editing installed source: ignore list and source suffixes and size cap
(`indexer.py`), embedding dimensions (`embeddings.py`), the 0.15 hybrid weight
(`search.py`), the `limit`/`max_chars` defaults and the agent `open` bounds
(`cli.py`).

Resolution order is CLI flag > `.rag-your-code/config.toml` > built-in default.
No environment variables and no new dependencies: `tomllib` is standard library
from 3.11, and the 3.10 leg reads the same file with a minimal parser rather
than adding `tomli` to the runtime.

One trap this phase must handle rather than discover later: changing
`dimensions` or `suffixes` invalidates an existing index, and a dimension
mismatch is currently *silent* — `search.py`'s guard drops the vector score to
zero rather than raising. The index must record a fingerprint of the
configuration that produced it and force a full rebuild when it differs.

### P8 — Agent-authored descriptions *(landed)*

`annotate.py` says it in its own first line: descriptions are generated
*without an LLM*. `describe_python` humanises the identifier, lists parameter
and callee names, and appends the docstring verbatim. It introduces no
vocabulary that was not already in the source, which is exactly why retrieval
cannot reach a concept the author never wrote down.

The architecture already has the seam. `description` is part of
`searchable_text` (`models.py`), the vector is computed from the description
plus that text (`indexer.py`), and incremental reuse copies whole `CodeUnit`s
for unchanged files, so a better description survives re-indexing untouched.

So the agent already consuming this index writes the descriptions, at index
time, through two new protocol actions (`describe_pending` / `describe_put`)
and a `describe` subcommand for the non-protocol case. They are stored in
`.rag-your-code/descriptions.json`, keyed by unit id **and source hash** so a
description can never outlive the code it describes, and committed to Git so
one person's pass benefits the team and CI.

Measured on `benchmarks/fixture`, replacing one template description with an
agent-written bilingual one:

| query | template description | agent description |
|---|---|---|
| `exponential backoff` | not in top 3 | **#1**, 1.0175 |
| `double billing safety` | not in top 3 | **#1**, 0.3369 |
| `支付网关超时` | not in top 3 | **#1**, 0.8636 |
| `resend a payment after a transient upstream error` | #1, 0.3211 | #1, **0.9178** |

Three queries move from missing entirely to first. The fourth already matched;
its margin stops depending on a stopword.

**What this is, stated plainly:** it moves the semantic work from query time to
index time. It is not semantic generalisation — matching stays lexical, so a
description saying `retry` still cannot answer a query saying `resend` unless
the description also says so. It is LLM-authored keyword expansion, and its
quality is bounded by how many ways of saying the thing the agent thought to
write down. Descriptions are bilingual by default (configurable), because the
row above shows a Chinese query going from unreachable to first.

### What building them turned up

Both phases surfaced defects older than themselves, which is the usual return
on touching every call site of something.

The walker's suffix list and the parser's dispatch table were separate lists
agreeing by coincidence. A suffix on the first and not the second is walked,
read, parsed to nothing, and reported as a clean index of zero units --
precisely what `suffixes = [".vue"]` produced. `index.suffixes` now takes both
its default and its permitted values from `parser.EXTENSIONS`.

`incremental` in the index report was computed from whether a previous index
existed, not from whether its units were reused. A configuration change
discards them, so the run that rebuilt everything was the run that claimed
reuse.

SKILL.md's step 0 named a package index this project does not publish to. The
0.2.0 audit had already found that step telling an agent to run a module
nothing installs; the 0.3.0 fix was equally unrunnable, and neither time did
any gate notice, because nothing ever ran it. There is now a test asserting
every documented `pip install` names an installable source, and a CI job that
runs the command as written.

The query benchmark was itself too coarse to be evidence: ten cold samples of a
sub-millisecond call made an unchanged query path look like a real regression
across three runs, and a direct 1000-sample probe put the two trees within
noise and reversed which was faster between rounds. It now warms up, takes 200
samples, and records the median beside the mean.

Two migration traps were caught before release rather than after. An index
predating each new fingerprint carries no such key; read as "unknown" rather
than as "defaults" and "no descriptions", every 0.3.0 index would have reported
itself permanently stale, or forced one pointless full rebuild, on upgrade.

### What 0.4.1 turned up

Describing this repository's own `src/` was meant as dogfooding, and found two
defects a single-unit fixture could not.

A description was orphaned when its code merely moved. Unit ids embed the line
a declaration starts on, so adding a seven-line comment to `config.py` gave
every declaration below it a new id and orphaned nineteen descriptions -- of
code that had not changed by a byte. The digest already answered "is this the
same code?"; it now answers "where did that code go?" as well. Pruning had the
matching hazard and would have deleted exactly the entries that lookup exists
to rescue.

`describe.max_chars` was set inside the normal range rather than above it. Over
the 120 descriptions written here the median is 349 characters and the 90th
percentile is 662, so a 600 cap rejected roughly one good-faith description in
eight -- and rejected them at the complex units retrieval most needs help with,
since nothing is truncated to fit.

A third followed in 0.4.2, from the same cause as the install line: a number
stated in prose that nothing compared to the data. `docs/TESTING.md` claimed 96
deliberately-excluded constructs where the fixtures hold 89, the count of
expected units copied one line up. The counts are now asserted against
`expected.json` itself.

## 0.5.0 — the vocabulary ladder

0.4.0 asked where retrieval's vocabulary comes from and answered "whatever an
agent writes into a sidecar". That was one rung of three, and the least
durable one.

Every source of words, ordered by what it costs and by whether it survives a
refactor:

| source | who wrote it | lives in | survives a move | cost |
|---|---|---|---|---|
| identifier, signature, body | author | the code | by construction | free |
| Python docstring | author | the code | by construction | free |
| doc comment, 14 languages | author | the code | by construction | free |
| agent description | agent | a sidecar | needs machinery | tokens |
| promoted doc comment | agent | the code | by construction | none extra |

Read the fourth column. Text in the code needs no bookkeeping; the digest,
the relocation lookup, the fingerprint and the pruning rule all exist to
simulate a property it has for nothing. So the sidecar is the fallback and
the code is the destination, and the work went in that order.

**Level 0** indexes the documentation the author already wrote. Free, and it
was being discarded: fourteen of fifteen languages document above the
declaration, outside the unit's span. Zero of ninety-five non-Python fixture
declarations carried documentation into the index; sixteen now do.

**Level 1** offers to move an agent's description into the code as a patch a
person reviews. Not performed — the tool still never writes source.

**Level 2** is the sidecar, unchanged in mechanism and demoted in role.

### What the ladder turned up

Two prerequisites, both defects older than the work.

Reuse was keyed on a file's bytes, but cached units are a function of the
bytes and of the parser. Upgrading the parser reached no existing index. That
was the third unrecorded input after the settings and the descriptions, so the
three became one `build_fingerprint`.

The digest deciding whether a description still applies covered the unit's
documentation, so promoting a description discarded it — the guard firing on
its own reflection. Measured here, that cost Chinese retrieval twenty-eight
percent of its hit rate before it was found. Documentation is now excluded
from that digest, which also stops a hand-edited docstring from discarding a
description of code that did not change.

### The instrument came first

Four candidate scoring changes measured over an eight-question set all landed
between five and six correct. That is the resolution limit of the instrument,
not a ranking of options, and it is the same mistake as the ten cold samples
that made an unchanged query path look like a regression in 0.4.0. So seventy
questions were written before anything else, and its own score is asserted
nowhere: it falls whenever the repository gains undescribed code, which is
ordinary development.

## 0.6.0 — ranking, measured somewhere it could fail

Every ruler this project had graded a repository its own authors wrote, and
0.5.0's own summary said the score was 0.457 hit@1. Indexed cold against
cc-enforcer — 1153 units, no descriptions, questions in a user's words — the
same code scored **0.086**, and the reason was not the vocabulary the previous
release worked on. It was ranking.

| defect | how it showed | fix |
|---|---|---|
| Every query word weighed the same | `calls` reached 97% of units and `the` 49%, against `daemon` at two and `warm` at none; the score was four-sixths noise | inverse document frequency, derived from the corpus, so it needs no stopword list and works in any language |
| Nothing corrected for size | largest declaration held 539 distinct terms against a median of 52, and led the top three for four questions of six | BM25 length normalisation, per field |
| A word counted the same wherever it was | test declarations outranked the code they test | field weights: name 8, signature 4, description 3, relations 2, body 1 |

Measured on identical content, all three rulers moved in the same direction. These are 0.6.0's figures and are kept as its record; the current ones are in README.md:

| ruler | hit@1 | hit@3 | MRR |
|---|---|---|---|
| cold, foreign repository (35) | 0.086 → **0.257** | 0.229 → **0.400** | 0.157 → **0.314** |
| cold, this repository (70) | 0.200 → **0.271** | 0.357 → **0.486** | 0.271 → **0.367** |
| described, this repository (70) | 0.457 → **0.500** | 0.657 → **0.800** | 0.545 → **0.631** |

### What was measured and rejected

Four changes were implemented, measured, and dropped — which is the point of
having three rulers rather than one.

- **Excluding curated text from a unit's length**, on the argument that a
  written description is deliberate rather than incidental: one question
  better on two rulers, three worse on the third.
- **Counting authored words rather than tokeniser output**, so a run of
  Chinese expanded into bigrams would not read as five times the text:
  identical on two rulers of three.
- **Lowering `b` to 0.5 or 0.3**: worse than the standard 0.75 on the cold
  ruler.
- **Splitting identifiers into words** — `retry_charge` into `retry` and
  `charge`. This looked like the largest available win, since identifiers are
  the densest vocabulary in code and are currently opaque. Measured with query
  and stored vectors rebuilt together, it was equal or worse on all three
  rulers: the pieces are `get`, `find`, `check`, `test`, which rarity
  weighting immediately discounts, while the exact-identifier signal is
  diluted among them.

### What the vector turned out to be

Ablating it used to cost 0.114 of hit@1, which read as evidence that the
feature hash was doing something. It was: `vector[bucket] += sign` followed by
a division by the magnitude is term frequency with length normalisation, the
two things the lexical score lacked. Once BM25 supplied both properly, the
same ablation costs **nothing measurable on a foreign repository**. The
vectors are 55% of an index's size and are now earning almost none of it.
Removing them is a schema decision, not a ranking one, and has not been taken.

## 0.7.0 — what a reply carries, and the end of the embedding search

Three defects of one shape, and one investigation that closed a question.

**A result carried the code, and every reply carried it again.** `search
--json` served 65,025 characters against a stated budget of 12,000;
`research` served 111,843, because reporting two retrieval steps meant
serialising the same eight units three times with their source attached; and
`neighbors` served 27,473 under no budget at all. Bounding each emitter would
have left the next one free to overrun, so the source came out of
`SearchResult.to_dict`: a result that has no source cannot carry it twice.
Measured after: 24,403 / 24,429 / 13,848.

**A constant was tied to a scale that moved.** The research loop stopped early
when the top score passed 0.8. BM25F changed the scale, only 3% of queries
could reach 0.8, and the early stop silently ceased to exist — no test noticed,
because the assertion was `stop_reason in {all four values}`. It is a margin
between the top two scores now, which is scale-free by construction.

**Indexing was not the same as being searchable, and nothing said so.**
`bootstrap` reports which rung a repository is on and hands over that rung's
work. It reads state rather than remembering a position, so it is resumable by
running it again. The pure operations moved to `workflow.py`, which is what
lets the command line and the agent protocol run one implementation.

### The embedding question, closed

Eight approaches were implemented and measured against all three rulers: six
replacement embeddings (character n-grams, corpus co-occurrence via random
indexing, truncated SVD, posting-list signatures, a rarity- and field-weighted
hash, call-graph diffusion), lexical postings expansion, and embedding only
the authored fields. **On the foreign-repository ruler, hit@3 never exceeded
its no-vector value of 0.429.**

The constraint is architectural. `candidate_ids = lexical_scores.keys()`: a
vector reorders what the lexical half already found and cannot make anything
retrievable. Postings expansion, the one change that *could*, was worse at
every weight tried. Corpus-learned semantics need orders of magnitude more
text — 65% of the foreign corpus's terms appear in four or fewer units. And on
a described corpus the shipped hash helps *because* it is blunt, so every
scheme that sharpened it lost ground there.

What remains is not a better local embedding. It is either a real model as an
optional dependency, which trades the property this project is built on, or
accepting that retrieval reaches only what somebody wrote down.

