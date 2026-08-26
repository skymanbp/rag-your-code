"""Guards for the three ranking defects a cold foreign repository exposed.

Measured on cc-enforcer -- 1153 units, no written descriptions -- the single
largest declaration came back in the top three for four questions out of six,
and the words deciding the ranking were the ones present in nearly every unit.
Three causes, all in how a match was scored:

H: every query word counted the same, so `the` (49% of units) and `calls`
   (97%) outweighed `daemon` (2 units) and `warm` (none).
I: nothing normalised for size, and the largest unit held 539 distinct terms
   against a median of 52, so it could contain any query by accident.
J: a term in a declaration's name counted no more than the same term two
   hundred lines into a body, which put test units above the code they test.

Each test is built so that the previous rule -- the fraction of query words
present anywhere in the unit -- ranks the *wrong* answer first.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

from ragyourcode.indexer import build_units
from ragyourcode.models import CodeUnit
from ragyourcode.search import FIELD_WEIGHTS, _block, build_search_index, context, search, within_budget

RARE_QUERY = "handle the request and return the response quiesce"


def _with_a_word_nothing_else_uses(root: Path) -> Path:
    """One more unit, whose only distinguishing word appears nowhere else."""
    (root / "rare.py").write_text(
        "def quiesce(attempt):\n"
        '    """Settle down."""\n'
        "    return attempt\n",
        encoding="utf-8",
    )
    return root


def test_a_word_in_almost_every_unit_cannot_decide_the_ranking(tmp_path: Path, skewed_corpus):
    """Rarity is evidence; ubiquity is not.

    Under the previous rule the unit matching six common words out of seven
    scored 0.857 and the only unit that answers the question scored 0.286.
    Nothing here is a stopword list: `the` and `request` earn their low weight
    from this corpus, which is why the mechanism works on a repository written
    in any language, including one where the tokens are Chinese bigrams.
    """
    units = build_units(_with_a_word_nothing_else_uses(skewed_corpus(tmp_path)))
    results = search(units, RARE_QUERY, limit=3)
    assert results[0].unit.name == "quiesce", [result.unit.id for result in results]


def test_matched_terms_survive_the_posting_list_lookup(tmp_path: Path, skewed_corpus):
    """Postings now carry a weight beside each id, and are searched by id.

    A membership test comparing whole entries would report no matched terms at
    all, turning every result's evidence -- the thing that makes a result
    checkable -- into an empty list.
    """
    units = build_units(_with_a_word_nothing_else_uses(skewed_corpus(tmp_path)))
    results = search(units, RARE_QUERY, limit=8)
    assert all(result.matched_terms for result in results), [
        (result.unit.id, result.matched_terms) for result in results
    ]


def test_a_long_unit_does_not_win_on_size_alone(tmp_path: Path, skewed_corpus):
    """Containing a word is not the same as being about it.

    The corpus has to be this large for the defect to appear at all. Every
    query word here reaches all eighty-one units, which puts its posting list
    past the selective threshold, so no vector score is computed and the
    lexical rule decides alone. In a two-unit fixture the feature-hash vector
    hides the problem, because normalising by a unit's token mass is itself a
    crude length normalisation -- which is why the defect was visible on a
    1153-unit repository and invisible in the small benchmark.
    """
    filler = "\n".join(f"    step_{number} = compute(step_{number - 1})" for number in range(1, 200))
    (skewed_corpus(tmp_path) / "aggregate.py").write_text(
        "def process_everything(request, response):\n"
        '    """Handle request and return response."""\n'
        f"{filler}\n"
        "    return response\n",
        encoding="utf-8",
    )
    units = build_units(tmp_path)
    results = search(units, "handle the request and return the response", limit=3)
    # Same words as every handler, two hundred lines of unrelated code, and it
    # came back first: matched-word count made them equal and the tie fell to
    # the unit id.
    assert "process_everything" not in [result.unit.name for result in results], [
        result.unit.id for result in results
    ]


def test_the_same_word_counts_for_more_in_a_name_than_in_a_body(tmp_path: Path):
    """Where the author wrote a word says how much it meant.

    Both units are the same size and mention the word once, so nothing but the
    field it appears in can separate them. The vector is switched off because
    it would answer this question by a different route -- its cosine already
    favours the unit where the word is a larger share of the text -- and the
    lexical rule is what changed. Without that, both scored exactly 1.0 and
    the tie fell to the unit id.

    This is the mechanism, not its limit: a body repeating a word forty times
    still outranks the declaration named after it, because forty occurrences
    over an average-length body is genuinely a lot of evidence. See
    docs/TESTING.md for what that still costs.
    """
    (tmp_path / "named.py").write_text(
        'def checkpoint(job):\n    """Do the work and hand it back."""\n    return job\n',
        encoding="utf-8",
    )
    (tmp_path / "mentions.py").write_text(
        'def worker(job):\n    """Do the work and hand it back."""\n    # checkpoint\n    return job\n',
        encoding="utf-8",
    )
    units = build_units(tmp_path)
    results = search(units, "checkpoint", limit=2, vector_weight=0.0)
    assert results[0].unit.name == "checkpoint", [result.unit.id for result in results]


def test_every_searchable_field_carries_a_weight(tmp_path: Path):
    """A field with no weight would vanish from ranking the moment it appeared.

    The two live in different modules on purpose -- one says what retrieval may
    match, the other how much each part counts -- so this is the join that
    keeps them from drifting apart.
    """
    (tmp_path / "one.py").write_text("def f(a):\n    return a\n", encoding="utf-8")
    unit = build_units(tmp_path)[0]
    assert set(unit.searchable_fields) == set(FIELD_WEIGHTS)


def test_searchable_text_is_every_field_and_nothing_else(tmp_path: Path):
    """The text a unit is embedded from must not lose a field ranking uses."""
    (tmp_path / "one.py").write_text(
        '"""Module."""\n\n\ndef f(a):\n    """Add one."""\n    return a + 1\n',
        encoding="utf-8",
    )
    unit = build_units(tmp_path)[0]
    assert unit.searchable_text == "\n".join(unit.searchable_fields.values())


def _budgeted(root: Path) -> list:
    for index in range(6):
        (root / f"unit_{index}.py").write_text(
            f"def widget_{index}(value):\n"
            f'    """Widget {index} handles the value."""\n'
            + "".join(f"    line_{number} = value\n" for number in range(40))
            + "    return value\n",
            encoding="utf-8",
        )
    return search(build_units(root), "widget handles the value", limit=6)


def test_the_budget_bounds_the_results_not_only_the_context(tmp_path: Path):
    """`search --json` served 65,025 characters against a budget of 12,000.

    The cap applied to the context string while every result was serialised
    beside it in full, so the half an agent reads was the half that overran.
    """
    results = _budgeted(tmp_path)
    assert len(results) > 1, "the fixture must produce enough results to be trimmed"
    budget = len(_block(results[0])) + 10
    kept = within_budget(results, budget)
    assert len(kept) < len(results)
    assert sum(len(_block(result)) for result in kept) <= budget
    assert context(kept, budget) == context(results, budget)


def test_a_single_result_larger_than_the_budget_is_still_returned(tmp_path: Path):
    """Finding something and returning nothing is worse than one oversized hit."""
    results = _budgeted(tmp_path)
    assert [result.unit.id for result in within_budget(results, 0)] == [results[0].unit.id]


def test_a_field_every_unit_leaves_empty_does_not_divide_by_zero():
    """Each field is normalised against that field's own average length.

    A corpus where nobody fills one in -- no signature, no body, no written
    description -- makes that average zero, and the average is a denominator.
    """
    unit = CodeUnit(
        id="empty.py:1:nothing",
        path="empty.py",
        language="python",
        kind="function",
        name="nothing",
        qualified_name="nothing",
        signature="",
        start_line=1,
        end_line=1,
        source="",
        description="",
        serial=1,
    )
    index = build_search_index([unit])
    assert search([unit], "nothing", limit=1, search_index=index)[0].unit.id == unit.id


def test_a_block_does_not_reprint_the_docstring_the_code_below_it_shows(tmp_path: Path):
    """The author's own words reached the block twice: once quoted into the
    generated description so they are searchable, once in the source.

    Measured on a repository whose author wrote them, 2,381 of 3,382
    characters of prose header were a verbatim repeat of the code beneath it.
    At a fixed budget that is answers crowded out by their own duplicate: the
    same twelve thousand characters carried 92 declarations before this and
    119 after.

    Both halves are asserted. Dropping the quote must not drop what only the
    header says, and it must not touch what the index can find -- the docstring
    stays in `searchable_text`, which is why no ruler moves.
    """
    (tmp_path / "billing.py").write_text(
        'def charge(amount):\n'
        '    """Charge the amount against the stored card and return a receipt."""\n'
        '    return amount\n',
        encoding="utf-8",
    )
    unit = build_units(tmp_path)[0]
    index = build_search_index([unit])
    rendered = _block(search([unit], "charge the amount", search_index=index, limit=1)[0])

    quoted = "Charge the amount against the stored card and return a receipt."
    assert rendered.count(quoted) == 1, "the docstring is printed once, by the code"
    assert rendered.index(quoted) > rendered.index("```"), "the surviving copy is the one in the source"
    assert "This method charge" in rendered, "the generated half is not in the source and must stay"
    assert quoted in unit.searchable_text, "dropping it from the block must not drop it from the index"


def test_a_written_description_the_source_does_not_carry_survives(tmp_path: Path):
    """The rule is "the code already shows it", not "it came after the marker".

    An authored description is the one part of a block a reader cannot recover
    by reading the code, so a rule that keyed on the marker alone would delete
    exactly the text this project spends tokens to produce.
    """
    (tmp_path / "billing.py").write_text(
        'def charge(amount):\n'
        '    """Charge the card."""\n'
        '    return amount\n',
        encoding="utf-8",
    )
    unit = build_units(tmp_path)[0]
    unit = dataclasses.replace(
        unit, description="This method charge. Documented intent: retries a declined authorisation once."
    )
    index = build_search_index([unit])
    rendered = _block(search([unit], "charge the amount", search_index=index, limit=1)[0])
    assert "retries a declined authorisation once." in rendered
