"""Unique reduction, aggregation unit, and the corpus floor."""

from __future__ import annotations

import statistics

import pytest

from bindnum import (
    AmbiguousReduction,
    CandidateCouldNotRun,
    NoReductionReproduces,
    WrongReductionDeclared,
    assert_aggregation_unit,
    assert_corpus_floor,
    assert_unique_reduction,
    mutation_verified,
    units_of,
)

CELLS = {
    "a": [1.0, 2.0, 9.0],
    "b": [2.0, 3.0, 10.0],
    "c": [4.0, 5.0, 30.0],
}

CANDIDATES = {
    "median": lambda key: statistics.median(CELLS[key]),
    "mean": lambda key: statistics.fmean(CELLS[key]),
    "max": lambda key: max(CELLS[key]),
}


# --------------------------------------------------------------------------
# unique reduction
# --------------------------------------------------------------------------


@mutation_verified(
    "2026-08-04",
    "made reduction_report treat every cell as reproduced",
    result="AmbiguousReduction -- all three candidates win; reverted; passes",
)
def test_exactly_one_candidate_wins():
    published = {"a": "2.00", "b": "3.00", "c": "5.00"}
    assert assert_unique_reduction(published, CANDIDATES, declared="median") == "median"


@mutation_verified(
    "2026-08-04",
    "made the winners list fall back to the declared name when empty",
    result="this test stops raising; reverted; passes",
)
def test_no_winner_means_the_table_and_the_data_diverged():
    published = {"a": "2.00", "b": "3.00", "c": "7.77"}
    with pytest.raises(NoReductionReproduces, match="no candidate reduction reproduces"):
        assert_unique_reduction(published, CANDIDATES)


@mutation_verified(
    "2026-08-04",
    "took winners[0] instead of raising when more than one reduction reproduced",
    result="this test stops raising, which is the whole failure mode; reverted; passes",
)
def test_many_winners_is_a_finding_not_a_pass():
    """Two reductions that agree on every published cell mean the table cannot
    verify its own methodology sentence."""
    flat = {"a": [2.0, 2.0], "b": [5.0, 5.0]}
    candidates = {
        "median": lambda key: statistics.median(flat[key]),
        "mean": lambda key: statistics.fmean(flat[key]),
    }
    with pytest.raises(AmbiguousReduction, match="do not discriminate"):
        assert_unique_reduction({"a": "2.00", "b": "5.00"}, candidates, declared="median")


@mutation_verified(
    "2026-08-04",
    "deleted the `declared is not None and winner != declared` check",
    result="this test stops raising; reverted; passes",
)
def test_the_declared_reduction_must_be_the_winning_one():
    published = {"a": "2.00", "b": "3.00", "c": "5.00"}
    with pytest.raises(WrongReductionDeclared, match="declares the 'mean' reduction"):
        assert_unique_reduction(published, CANDIDATES, declared="mean")


@mutation_verified(
    "2026-08-04",
    "removed the len(table) < 2 and len(candidates) < 2 guards",
    result="this test stops raising and a one-cell table silently `verifies` its "
    "reduction; reverted; passes",
)
def test_one_cell_or_one_candidate_is_refused_up_front():
    """Both degenerate shapes 'pass' vacuously, so neither is allowed."""
    with pytest.raises(AssertionError, match="at least two cells"):
        assert_unique_reduction({"a": "2.00"}, CANDIDATES)
    with pytest.raises(AssertionError, match="at least two candidate reductions"):
        assert_unique_reduction({"a": "2.00", "b": "3.00"}, {"median": CANDIDATES["median"]})


@mutation_verified(
    "2026-08-04",
    "removed the try/except around the candidate call in reduction_report",
    result="ValueError escapes raw instead of being collected; reverted; passes",
)
def test_a_candidate_that_raises_does_not_crash_the_check_with_its_own_exception():
    """The candidate's exception is collected, not propagated.

    This is the half of the original contract that was right. The other half
    -- that the check then went on to CERTIFY the survivor -- was the bug: see
    the next test.
    """
    published = {"a": "2.00", "b": "3.00", "c": "5.00"}

    def explodes(_key):
        raise ValueError("no such column")

    with pytest.raises(AssertionError) as caught:
        assert_unique_reduction(published, dict(CANDIDATES, broken=explodes), declared="median")
    assert not isinstance(caught.value, ValueError)
    assert "no such column" in str(caught.value)  # reported, as evidence, not raised


@mutation_verified(
    "2026-08-05",
    "restored the old behaviour: dropped the CandidateCouldNotRun guard entirely",
    result="the broken-rival case certifies 'median' again; reverted; passes",
)
def test_a_rival_that_never_ran_is_not_a_rival_that_lost():
    """Regression for the silent-certification bug found 2026-08-04.

    `assert_unique_reduction` collected candidate exceptions and interpolated
    them into failure messages only -- so when the rivals raised, the honest
    candidate won by walkover and was returned as a verified unique reduction.
    The module's whole argument is that "many candidates reproduce" is a
    finding rather than a pass; the symmetric collapse to one was reported as
    the strongest pass it can give.
    """
    published = {"a": "2.00", "b": "3.00", "c": "5.00"}

    def explodes(_key):
        raise ImportError("no module named 'scipy'")

    with pytest.raises(CandidateCouldNotRun, match="never tested"):
        assert_unique_reduction(published, dict(CANDIDATES, broken=explodes), declared="median")

    # And the escape hatch still works, for the caller who means it.
    assert (
        assert_unique_reduction(
            published,
            dict(CANDIDATES, broken=explodes),
            declared="median",
            allow_candidate_errors=True,
        )
        == "median"
    )


@mutation_verified(
    "2026-08-05",
    "made CandidateCouldNotRun fire on ANY error, dropping the lost-on-the-merits carve-out",
    result="this case starts raising instead of certifying; reverted; passes",
)
def test_a_rival_that_raised_but_also_lost_a_cell_it_ran_is_beaten_not_unproven():
    """The carve-out that keeps the new guard from crying wolf.

    A candidate that raised on one cell but *mismatched* another it did run
    lost on the merits. Its error cannot have changed the verdict, so refusing
    here would be a false alarm -- and false alarms are what get a guard
    switched off with allow_candidate_errors=True everywhere.
    """
    published = {"a": "2.00", "b": "3.00", "c": "5.00"}

    def half_broken(key):
        if key == "a":
            raise ValueError("no such column")
        return 99.0  # ran, and is nowhere near the published value

    assert (
        assert_unique_reduction(
            published, dict(CANDIDATES, broken=half_broken), declared="median"
        )
        == "median"
    )


# --------------------------------------------------------------------------
# aggregation unit
# --------------------------------------------------------------------------

ROWS = [
    {"part": "a", "seed": "1", "v": "1"},
    {"part": "a", "seed": "2", "v": "2"},
    {"part": "b", "seed": "1", "v": "3"},
    {"part": "b", "seed": "2", "v": "4"},
]


@mutation_verified(
    "2026-08-04",
    "compared len(rows) instead of len(distinct units) in assert_aggregation_unit",
    result="the truncated 2-row case stops raising; reverted; passes",
)
def test_the_unit_count_is_pinned_not_the_row_count():
    assert assert_aggregation_unit(ROWS, "part", 2, unit="part") == 2
    with pytest.raises(AssertionError, match="short of the intended sweep"):
        assert_aggregation_unit(ROWS[:2], "part", 2, unit="part")


@mutation_verified(
    "2026-08-04",
    "compared len(rows) instead of len(distinct units) in assert_aggregation_unit",
    result="this test stops raising; reverted; passes",
)
def test_a_row_count_that_looks_right_does_not_rescue_a_missing_unit():
    """Four rows, two of them duplicated: the row count is intact and one
    whole unit is gone. This is the shape a half-finished sweep leaves."""
    truncated = ROWS[:2] + ROWS[:2]
    assert len(truncated) == len(ROWS)
    with pytest.raises(AssertionError, match="1 distinct part"):
        assert_aggregation_unit(truncated, "part", 2, unit="part")


@mutation_verified(
    "2026-08-04",
    "deleted the also_expect_rows block from assert_aggregation_unit",
    result="this test stops raising; reverted; passes",
)
def test_uneven_coverage_is_reported_separately():
    with pytest.raises(AssertionError, match="uneven coverage"):
        assert_aggregation_unit(ROWS, "part", 2, unit="part", also_expect_rows=6)


@mutation_verified(
    "2026-08-04",
    "dropped the `if callable(key)` branch from _keyfn",
    result="TypeError; reverted; passes",
)
def test_the_key_may_be_a_callable():
    assert units_of(ROWS, lambda row: row["part"] + row["seed"]) == {"a1", "a2", "b1", "b2"}


# --------------------------------------------------------------------------
# the floor
# --------------------------------------------------------------------------


@mutation_verified(
    "2026-08-04",
    "changed the comparison in assert_corpus_floor from < to <= -1 (always false)",
    result="the empty-corpus assertion stops raising; reverted; passes",
)
def test_a_collapsed_corpus_fails_instead_of_passing_silently():
    assert assert_corpus_floor(["a", "b", "c"], 3, what="documents") == 3
    with pytest.raises(AssertionError, match="corpus builder has collapsed"):
        assert_corpus_floor([], 3, what="documents", built_by="glob('*.md')")


@mutation_verified(
    "2026-08-04",
    "dropped the isinstance(corpus, int) branch from assert_corpus_floor",
    result="TypeError on len(7); reverted; passes",
)
def test_the_floor_accepts_a_bare_count():
    assert assert_corpus_floor(7, 5, what="files") == 7
