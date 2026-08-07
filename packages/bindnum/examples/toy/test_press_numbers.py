"""RESULTS.md must agree with results.csv. The worked example, end to end.

Run it:

    cd oss/bindnum && python -m pytest examples/toy -q

Then try breaking it, in either direction -- both are real failures:

    * edit "1.46×" in RESULTS.md            -> test_bindings_hold fails
    * edit a press_ms cell in results.csv   -> test_bindings_hold fails
    * swap the gasket and spindle lines     -> test_bindings_hold fails on the pair
    * delete the spindle rows from the CSV  -> test_the_sweep_covers_every_part fails
    * point make_chart at literals instead  -> test_the_chart_actually_reads fails

Every test below carries a @mutation_verified marker recording the break that
was actually performed against it. `pytest --mutation-todo examples/toy` lists
any that do not.
"""

from __future__ import annotations

import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import derive_press as derive  # noqa: E402

from bindnum import (  # noqa: E402
    Doc,
    assert_aggregation_unit,
    assert_corpus_floor,
    assert_reads,
    assert_unique_reduction,
    binds,
    binds_pair,
    bindings,
    mutation_verified,
    reads_of_script,
)

DOC = Doc(os.path.join(HERE, "RESULTS.md"))


# --------------------------------------------------------------------------
# the bindings: a stated value, located by (section, label), and a derivation
# --------------------------------------------------------------------------


@binds(DOC, section="Headline", label="faster than the fold arm")
def headline_ratio() -> float:
    return derive.headline_ratio()


@binds(DOC, section="Per-part table", label="| bracket |")
def bracket_ratio() -> float:
    return derive.part_ratio("bracket")


@binds(DOC, section="Per-part table", label="| flange |")
def flange_ratio() -> float:
    return derive.part_ratio("flange")


@binds_pair(
    DOC,
    first=dict(section="near unity", label="gasket:"),
    second=dict(section="near unity", label="spindle:"),
    window=0.02,
    note="1.02 and 0.98 are the shape where an arm swap hides.",
)
def near_unity_pair() -> tuple[float, float]:
    return derive.near_unity_pair()


# Snapshot the registry the moment this module's bindings are declared, so the
# tests below iterate exactly these four and never inherit another module's.
TOY_BINDINGS = bindings()


@mutation_verified(
    "2026-08-04",
    "changed RESULTS.md headline 1.46x -> 1.47x; and separately results.csv "
    "bracket/11/1 press_ms 40.00 -> 44.00",
    result="both fail; reverted; passes",
)
@pytest.mark.parametrize("binding", TOY_BINDINGS, ids=lambda b: b.name)
def test_bindings_hold(binding):
    binding.check()


# --------------------------------------------------------------------------
# the table verifies its own methodology sentence
# --------------------------------------------------------------------------


@mutation_verified(
    "2026-08-04",
    "pointed all three names in derive_press.REDUCTIONS at statistics.median",
    result="AmbiguousReduction; reverted; passes",
)
def test_exactly_one_reduction_reproduces_the_table():
    """RESULTS.md declares median-then-geomean. Prove the table can tell.

    With one cell this would be meaningless: several reductions land on the
    same value at two decimal places. Across four cells, only one survives.
    """
    published = {"bracket": "2.40", "flange": "1.90", "gasket": "1.02", "spindle": "0.98"}
    winner = assert_unique_reduction(
        published,
        {name: (lambda part, r=name: derive.part_ratio(part, r)) for name in derive.REDUCTIONS},
        declared="median",
        what="the per-part table in RESULTS.md",
    )
    assert winner == "median"


# --------------------------------------------------------------------------
# the unit of aggregation, not the row count
# --------------------------------------------------------------------------


@mutation_verified(
    "2026-08-04",
    "deleted the six spindle rows from results.csv (a well-formed 18-row CSV)",
    result="fails naming 3 parts vs 4; reverted; passes",
)
def test_the_sweep_covers_every_part():
    rows = derive.read_rows()
    assert_aggregation_unit(
        rows, derive.UNIT, 4, unit="part", source="results.csv", also_expect_rows=24
    )


# --------------------------------------------------------------------------
# the provenance sentence is about behaviour, so observe the behaviour
# --------------------------------------------------------------------------


@mutation_verified(
    "2026-08-04",
    "pointed the assertion at chart_hardcoded.py, whose literals are correct",
    result="fails naming results.csv as never opened; reverted; passes",
)
def test_the_chart_actually_reads_the_csv():
    assert_reads(
        lambda: reads_of_script(os.path.join(HERE, "make_chart.py")),
        ["results.csv"],
        why="RESULTS.md: the chart 'reads results.csv directly'",
    )


@mutation_verified(
    "2026-08-04",
    "gave chart_hardcoded.py a real read of results.csv",
    result="the pytest.raises stops raising; reverted; passes",
)
def test_the_hardcoded_chart_is_caught_even_though_its_numbers_are_right():
    """The specimen. Correct literals, no read, and only the structural check sees it."""
    namespace, _log = reads_of_script(os.path.join(HERE, "chart_hardcoded.py"))
    for part, value in namespace["BARS"]:
        assert round(value, 2) == round(derive.part_ratio(part), 2), (
            "the counterexample's literals are supposed to be numerically correct -- "
            "that is what makes it a counterexample"
        )
    with pytest.raises(AssertionError, match="never opened"):
        assert_reads(
            lambda: reads_of_script(os.path.join(HERE, "chart_hardcoded.py")),
            ["results.csv"],
        )


# --------------------------------------------------------------------------
# the floor, last in the module
# --------------------------------------------------------------------------


@mutation_verified(
    "2026-08-04",
    "made @binds skip its _REGISTRY.append, so nothing registers",
    result="fails at the floor rather than passing with zero bindings; reverted; passes",
)
def test_the_binding_registry_is_not_empty():
    assert_corpus_floor(
        TOY_BINDINGS,
        4,
        what="registered bindings",
        built_by="@binds / @binds_pair at import time",
        was="4 on 2026-08-04",
    )
