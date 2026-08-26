---
description: Search this repository in plain language and report the declarations that answer it, each with its file, exact line range and the words it matched on.
argument-hint: "<question>   e.g. where are HTTP retries handled"
---

# /rag-your-code:search

Retrieve focused context for: **$ARGUMENTS**

## What to do

```bash
python -m ragyourcode.cli search "$ARGUMENTS" --json --limit 8
```

Add `--graph --hops 1` when callers, callees or containment are relevant.
Prefer one hop; use two only when the first produced concrete edge evidence.

Then **read the returned files and line ranges directly** before saying
anything about the code. Results are navigation, not the file: `results` carries
the identifier, path, line range, signature, description, score and matched
terms, and the code arrives once in `context`, trimmed to a budget.
`omitted_for_budget` says how many results the context did not reach — read
those from the `path` and line range each result reports, or raise
`--max-chars`. (`open` is an action of the JSON-lines `agent` protocol, not a
subcommand.)

Cite every claim as `path:line`, taken from the result rather than remembered.

## Matching is lexical by default

The default embedder is a feature hash, so a query sharing no word with a unit
scores zero against it — synonyms do not match. Ask in the vocabulary the code
uses: prefer `retry charge gateway timeout` over "重试扣款失败", and try two or
three wordings before concluding something is absent.

## An empty result is an answer, not a failure

Retrieval returns nothing rather than the unit that ranked least badly. Read
`diagnosis.reason`:

| reason | what it means | what to do |
|---|---|---|
| `no_query_term_in_index` | no word of the question is here | re-ask in the code's vocabulary, or check the index root |
| `only_ubiquitous_terms_matched` | only words used throughout matched | add a term specific to what you want |
| `too_little_of_the_query_matched` | most of the question is absent | ask something narrower, or write descriptions |
| `matched_terms_are_scattered` | the words are here, never together | the subject is probably not in this repository — say so and stop |

**Never respond by lowering `search.min_coverage` or
`search.min_concentration`.** That restores the guessing this exists to
prevent. If two or three rephrasings all come back empty, report that the
repository does not appear to contain it — do not keep going until something
is returned.

If the reason is one of the first three and coverage is low, the honest next
move is `/rag-your-code:describe`, not another rephrasing.
