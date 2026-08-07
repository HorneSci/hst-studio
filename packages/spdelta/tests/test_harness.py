"""The controls. Each test here guards a defect that has actually shipped."""

from __future__ import annotations

import math
import subprocess
import sys

import numpy as np
import pytest

from spdelta import (
    Cell,
    CompactDelta,
    ColumnDeltaCsc,
    FullMatvec,
    MaskedRowScan,
    ReferenceMismatch,
    banded,
    bootstrap_ci,
    drift,
    fanout,
    frozen,
    geomean,
    geomean_counted,
    jump_plain,
    ladder,
    local_sample,
    offset_for,
    order,
    ratio_rows,
    reduce_by_operator,
    reduce_flat,
    reduce_median_then_geomean,
    reference,
    standard_cells,
    summarize,
    sweep,
    Topology,
)
from spdelta.harness import REDUCTIONS, toolchain


# --------------------------------------------------------------------------
# the mean
# --------------------------------------------------------------------------


def test_geomean_of_a_ratio_and_its_inverse_agree():
    xs = [0.5, 2.0, 4.0, 0.25]
    assert geomean(xs) == pytest.approx(1.0 / geomean([1 / x for x in xs]))


def test_geomean_of_nothing_is_nan_not_zero_and_not_an_exception():
    assert math.isnan(geomean([]))


def test_geomean_drops_blanks_and_non_positives_and_says_how_many():
    value, dropped = geomean_counted([2.0, "", None, 0.0, -1.0, 8.0])
    assert value == pytest.approx(4.0)
    assert dropped == 4


def test_geomean_raises_on_a_value_that_is_neither_a_number_nor_a_blank():
    with pytest.raises(ValueError, match="not a number"):
        geomean([1.0, "banana"])


def test_geomean_coerces_strings_because_csv_readers_yield_them():
    assert geomean(["2.0", "8.0"]) == pytest.approx(4.0)


def test_geomean_drops_infinities():
    value, dropped = geomean_counted([2.0, float("inf"), 8.0])
    assert value == pytest.approx(4.0) and dropped == 1


# --------------------------------------------------------------------------
# the reductions
# --------------------------------------------------------------------------


def _rows(spec):
    return [
        {"operator": op, "rho": rho, "ratio": ratio}
        for op, rho, ratio in spec
    ]


def test_flat_and_median_then_geomean_disagree_on_unbalanced_seed_counts():
    """The disagreement is the reason neither is a default."""
    rows = _rows(
        [("A", 0.1, 1.0), ("A", 0.1, 1.0), ("A", 0.1, 1.0), ("B", 0.1, 8.0)]
    )
    value = lambda r: r["ratio"]  # noqa: E731
    assert reduce_flat(rows, value) == pytest.approx(8.0 ** 0.25)
    assert reduce_median_then_geomean(rows, value) == pytest.approx(math.sqrt(8.0))


def test_by_operator_weights_operators_equally_across_unequal_rate_counts():
    rows = _rows(
        [("A", 0.1, 4.0), ("A", 0.2, 4.0), ("A", 0.3, 4.0), ("B", 0.1, 1.0)]
    )
    value = lambda r: r["ratio"]  # noqa: E731
    assert reduce_by_operator(rows, value) == pytest.approx(2.0)
    assert reduce_median_then_geomean(rows, value) == pytest.approx(4.0 ** 0.75)


def test_both_reduction_names_are_registered():
    assert "reduce_flat" in REDUCTIONS
    assert "reduce_median_then_geomean" in REDUCTIONS


def test_median_over_seeds_happens_before_the_geometric_mean():
    rows = _rows([("A", 0.1, 1.0), ("A", 0.1, 100.0), ("A", 0.1, 2.0)])
    value = lambda r: r["ratio"]  # noqa: E731
    assert reduce_median_then_geomean(rows, value) == pytest.approx(2.0)


# --------------------------------------------------------------------------
# uncertainty
# --------------------------------------------------------------------------


def test_bootstrap_resamples_operators_not_rows():
    """Five seeds of one operator are not five observations.

    Two operators with wildly different ratios, one measured many times. An
    operator-level bootstrap must be able to draw an all-A or all-B sample, so
    the interval spans both values. A row-level bootstrap would concentrate
    near A and report a falsely narrow interval.
    """
    rows = _rows([("A", 0.1, 1.0)] * 20 + [("B", 0.1, 100.0)] * 2)
    lo, hi = bootstrap_ci(rows, lambda r: r["ratio"], reps=400, seed=0)
    assert lo == pytest.approx(1.0)
    assert hi == pytest.approx(100.0)


def test_bootstrap_below_two_operators_is_refused():
    """A one-operator bootstrap returned a ZERO-WIDTH interval as a result.

    Resampling operators with one operator draws that same operator every
    time, so every replicate is the same number and the percentile interval
    collapses to a point. `bootstrap_ci` used to return it:

        ci 2.779272111081864 2.779272111081864

    A reader sees extreme precision where there is no measurement at all. The
    docstring explains at length why operators are the resampling unit and
    never said the procedure is undefined below two of them.

    Zero operators returned (nan, nan), which is the same failure wearing a
    quieter face -- nothing distinguishes it from a computation that ran.

    Both now refuse, for the reason the module resamples operators in the
    first place: the operator is the unit that varies, so with fewer than two
    there is no variation to measure.
    """
    with pytest.raises(ValueError, match="at least two operators"):
        bootstrap_ci([], lambda r: r["ratio"], reps=10)

    one = [{"operator": "a", "arm": "hst", "rho": 0.01, "batch": 1,
            "motion": "drift", "ratio": 2.0}]
    with pytest.raises(ValueError, match="at least two operators"):
        bootstrap_ci(one, lambda r: r["ratio"], reps=10)


def test_bootstrap_with_two_operators_still_works():
    """The control. A guard that refused everything would pass the test above.

    Two operators is the smallest honest bootstrap, so it must not be swept up
    by the refusal -- and the interval it returns must have width, or the
    collapse the guard exists to prevent is still happening one operator later.
    """
    rows = [
        {"operator": op, "arm": "hst", "rho": 0.01, "batch": 1,
         "motion": "drift", "ratio": r}
        for op, r in (("a", 1.0), ("b", 100.0))
    ]
    lo, hi = bootstrap_ci(rows, lambda r: r["ratio"], reps=200)
    assert not math.isnan(lo) and not math.isnan(hi)
    assert lo < hi, (
        f"two operators produced a zero-width interval [{lo}, {hi}] -- the "
        f"collapse this guard exists to prevent, one operator later."
    )


# --------------------------------------------------------------------------
# order
# --------------------------------------------------------------------------


def test_order_is_a_rotation_so_neighbours_are_preserved():
    arms = ["a", "b", "c", "d"]
    for cell in [("x", 1), ("y", 2), ("z", 3), ("w", 4), ("v", 5)]:
        got = order(arms, cell)
        assert sorted(got) == sorted(arms)
        start = arms.index(got[0])
        assert got == arms[start:] + arms[:start], "not a cyclic rotation"


def test_order_without_rotation_keeps_the_declared_order():
    """Checked over many cells: one cell can rotate to the identity by luck."""
    arms = ["a", "b", "c"]
    for i in range(40):
        assert order(arms, ("cell", i), rotate=False) == arms
    assert any(order(arms, ("cell", i)) != arms for i in range(40))


def test_rotation_actually_moves_the_first_arm_across_cells():
    arms = ["a", "b", "c"]
    firsts = {order(arms, ("cell", i))[0] for i in range(50)}
    assert firsts == set(arms)


def test_offset_is_stable_across_processes():
    """blake2b, not hash(): hash() is salted per process for strings.

    Run twice under different PYTHONHASHSEED values. If the offset were derived
    from hash(), the two runs would disagree and a recorded order would not
    describe the run that gets reproduced.
    """
    code = (
        "import sys; sys.path.insert(0, %r);"
        "from spdelta import offset_for;"
        "print(offset_for(('band', 'drift', 0.25, 3), 7))"
    ) % str(__import__("pathlib").Path(__file__).resolve().parents[1] / "src")
    outs = []
    for seed in ("0", "12345"):
        outs.append(
            subprocess.run(
                [sys.executable, "-c", code],
                capture_output=True,
                text=True,
                env={**__import__("os").environ, "PYTHONHASHSEED": seed},
                check=True,
            ).stdout.strip()
        )
    assert outs[0] == outs[1]


def test_offset_of_an_empty_arm_list_is_zero():
    assert offset_for(("cell",), 0) == 0


# --------------------------------------------------------------------------
# the statistic
# --------------------------------------------------------------------------


def test_summarize_raises_on_no_samples_rather_than_returning_zero():
    """0.0 downstream reads as an arm of infinite speed."""
    with pytest.raises(ValueError, match="no samples"):
        summarize([])


def test_summarize_raises_on_an_unknown_statistic():
    with pytest.raises(ValueError, match="unknown statistic"):
        summarize([1.0, 2.0], "mode")


def test_summarize_defaults_to_the_median():
    assert summarize([1.0, 2.0, 100.0]) == 2.0
    assert summarize([1.0, 2.0, 100.0], "mean") == pytest.approx(34.3333333)


# --------------------------------------------------------------------------
# cells
# --------------------------------------------------------------------------


def test_local_sample_is_local_but_not_a_solid_interval():
    """A solid interval leaves local drift nowhere to go and silently freezes."""
    cols = local_sample(1000, 40, seed=0, spread=3)
    assert cols.size == 40
    assert np.unique(cols).size == 40
    span = int(cols.max() - cols.min())
    assert span > 40, "not a solid block"
    assert span <= 3 * 40, "still local"


def test_cell_rejects_a_dirty_column_outside_the_operator():
    a = banded(50, 3, 0)
    with pytest.raises(ValueError, match="but the operator has"):
        Cell("op", a, frozen(), np.array([99], dtype=np.int32), 1, 0)


def test_cell_rejects_duplicate_dirty_columns():
    a = banded(50, 3, 0)
    with pytest.raises(ValueError, match="duplicates"):
        Cell("op", a, frozen(), np.array([1, 1], dtype=np.int32), 1, 0)


def test_standard_cells_emits_the_frozen_control_once_per_operator_and_seed():
    a = banded(300, 5, 0)
    cells = standard_cells(
        [("band", a)],
        [
            lambda n, m, r: frozen(),
            lambda n, m, r: jump_plain(int(m.shape[1]), r),
        ],
        rhos=(0.05, 0.25),
        seeds=(1, 2),
        n_dirty=20,
        batch=1,
    )
    frozen_cells = [c for c in cells if c.motion.is_frozen]
    assert len(frozen_cells) == 2  # two seeds, not two seeds x two rates
    assert len(cells) == 2 + 4


# --------------------------------------------------------------------------
# the sweep and its mandatory reference
# --------------------------------------------------------------------------


def make_cells(n_dirty=12, batch=2, seeds=(1,)):
    a = banded(300, 5, 0)
    return standard_cells(
        [("band", a)],
        [lambda n, m, r: drift(Topology.line(int(m.shape[1]), radius=4), r)],
        rhos=(0.25,),
        seeds=seeds,
        n_dirty=n_dirty,
        batch=batch,
    )


class _BrokenArm(FullMatvec):
    """Right amount of work, wrong values -- the shape timings cannot see."""

    name = "broken"

    def step(self, d, y):
        super().step(d, y)
        y *= 1.0000001


def test_sweep_asserts_every_arm_against_the_reference():
    with pytest.raises(ReferenceMismatch, match="disagreed with scratch_reference"):
        sweep(
            [_BrokenArm()],
            make_cells(),
            reference=reference(),
            steps=4,
            repeats=1,
        )


def test_sweep_refuses_a_reference_of_none():
    with pytest.raises(TypeError, match="requires a reference arm"):
        sweep(ladder(), make_cells(), reference=None, steps=4, repeats=1)


def test_sweep_has_no_keyword_that_disables_the_reference():
    import inspect

    params = inspect.signature(sweep).parameters
    assert params["reference"].default is inspect.Parameter.empty
    assert not any(
        "check" in name or "assert" in name or "verify" in name for name in params
    )


def test_sweep_refuses_a_reference_that_is_also_a_timed_arm():
    with pytest.raises(ValueError, match="asserted against itself"):
        sweep(
            [FullMatvec(), ColumnDeltaCsc()],
            make_cells(),
            reference=FullMatvec(),
            steps=4,
            repeats=1,
        )


def test_sweep_refuses_duplicate_arm_names():
    with pytest.raises(ValueError, match="unique"):
        sweep(
            [FullMatvec(), FullMatvec()],
            make_cells(),
            reference=reference(),
            steps=4,
            repeats=1,
        )


def test_sweep_rejects_a_churn_labelled_cell_whose_dirty_set_never_moved():
    """The mislabelled-frozen trap, caught from the other direction."""
    a = banded(60, 5, 0)
    everything = np.arange(60, dtype=np.int32)  # no free neighbour anywhere
    cell = Cell(
        "band", a, drift(Topology.line(60, radius=2), 0.25), everything, 1, 0
    )
    with pytest.raises(ValueError, match="never changed"):
        sweep(ladder(), [cell], reference=reference(), steps=4, repeats=1)


def test_sweep_rows_carry_the_order_position():
    rows = sweep(ladder(), make_cells(), reference=reference(), steps=4, repeats=2)
    assert {r["order_pos"] for r in rows} == {0, 1, 2}
    for r in rows:
        assert r["order_n"] == 3


def test_sweep_rows_carry_conditions_and_counters():
    rows = sweep(ladder(), make_cells(), reference=reference(), steps=4, repeats=1)
    row = rows[0]
    for key in (
        "operator",
        "motion",
        "rho",
        "is_frozen",
        "seed",
        "batch",
        "n_dirty",
        "steps",
        "repeat",
        "arm",
        "delta_kind",
        "order_pos",
        "rotate",
        "stat",
        "seconds_per_step",
        "prepare_seconds",
        "rel_err",
        "tol",
        "slice_weight_first",
        "slice_weight_last",
        "slice_drift",
        "dirty_set_changes",
        "profile",
        "toolchain",
        "control",
        "recompiles",
    ):
        assert key in row, key
    assert row["toolchain"] == toolchain()


def test_the_toolchain_string_names_the_interpreter_and_the_libraries():
    text = toolchain()
    for fragment in ("CPython", "numpy", "scipy"):
        assert fragment in text, fragment
    assert len(text) > 20


def test_sweep_times_preparation_separately_from_the_steps():
    rows = sweep(ladder(), make_cells(), reference=reference(), steps=4, repeats=1)
    for r in rows:
        assert r["prepare_seconds"] > 0.0
        assert r["seconds_per_step"] > 0.0


def test_sweep_gives_every_arm_its_own_delta_objects():
    """One arm must not be able to corrupt another's inputs."""
    seen: list[np.ndarray] = []

    class _Vandal(FullMatvec):
        name = "vandal"

        def step(self, d, y):
            seen.append(d.vals)  # held, so ids cannot be recycled
            super().step(d, y)
            d.vals[:] = 0.0  # would zero the next arm's input if shared

    rows = sweep(
        [_Vandal(), ColumnDeltaCsc()],
        make_cells(),
        reference=reference(),
        steps=4,
        repeats=1,
        rotate=False,  # pin the vandal first, or the test proves nothing
    )
    # If inputs were shared, column_delta_csc would have computed zeros and the
    # reference assertion would have raised before we got here.
    assert len(rows) == 2
    assert len({id(v) for v in seen}) == len(seen)


def test_each_arms_delta_is_a_private_copy_of_the_stream():
    """The same check as a unit, so it does not depend on a lucky arm order."""
    from spdelta.harness import _as_delta

    cols = np.array([0, 1, 2], dtype=np.int32)
    vals = np.ones((3, 2))
    compact = _as_delta("compact", cols, vals, 10)
    assert compact.vals is not vals
    assert compact.cols is not cols
    glob = _as_delta("global", cols, vals, 10)
    assert glob.buf.base is not vals


def test_as_delta_rejects_an_unknown_encoding():
    from spdelta.harness import _as_delta

    with pytest.raises(ValueError, match="unknown delta kind"):
        _as_delta("dense", np.array([0], dtype=np.int32), np.ones((1, 1)), 4)


def test_sweep_rejects_zero_steps_or_repeats():
    with pytest.raises(ValueError, match=">= 1"):
        sweep(ladder(), make_cells(), reference=reference(), steps=0, repeats=1)


def test_sweep_rejects_an_empty_arm_list():
    with pytest.raises(ValueError, match="no arms"):
        sweep([], make_cells(), reference=reference(), steps=4, repeats=1)


def test_sweep_honours_the_active_profile(tiny_profile):
    import spdelta

    spdelta.use(tiny_profile)
    rows = sweep(ladder(), make_cells(), reference=reference())
    assert {r["steps"] for r in rows} == {tiny_profile.steps}
    assert {r["repeat"] for r in rows} == set(range(tiny_profile.repeats))
    assert {r["profile"] for r in rows} == {tiny_profile.name}


def test_sweep_is_reproducible():
    a = make_cells()
    first = sweep(ladder(), a, reference=reference(), steps=4, repeats=1)
    second = sweep(ladder(), a, reference=reference(), steps=4, repeats=1)
    assert [r["rel_err"] for r in first] == [r["rel_err"] for r in second]
    assert [r["order_pos"] for r in first] == [r["order_pos"] for r in second]


# --------------------------------------------------------------------------
# pairing
# --------------------------------------------------------------------------


def test_ratio_rows_pairs_within_a_cell_and_reports_the_ratio():
    rows = sweep(ladder(), make_cells(seeds=(1, 2)), reference=reference(), steps=4, repeats=2)
    paired = ratio_rows(rows, arm="column_delta_csc", baseline="full_matvec")
    assert len(paired) == 2 * 2  # two seeds x two repeats, one motion, one rate
    for r in paired:
        assert r["ratio"] == pytest.approx(
            r["baseline_seconds_per_step"] / r["arm_seconds_per_step"]
        )
        assert r["n_unpaired"] == 0


def test_ratio_rows_counts_what_it_could_not_pair():
    rows = sweep(ladder(), make_cells(seeds=(1, 2)), reference=reference(), steps=4, repeats=1)
    rows = [r for r in rows if not (r["arm"] == "full_matvec" and r["seed"] == 2)]
    paired = ratio_rows(rows, arm="column_delta_csc", baseline="full_matvec")
    assert len(paired) == 1
    assert paired[0]["n_unpaired"] == 1


def test_ratio_rows_refuses_to_pair_an_arm_with_itself():
    with pytest.raises(ValueError, match="must differ"):
        ratio_rows([], arm="a", baseline="a")


def test_ratio_rows_carries_the_conditions_forward():
    rows = sweep(ladder(), make_cells(), reference=reference(), steps=4, repeats=1)
    paired = ratio_rows(rows, arm="column_delta_csc", baseline="masked_row_scan")
    for key in ("motion", "rho", "toolchain", "control", "operator", "is_frozen"):
        assert key in paired[0], key


def test_the_readme_private_overlay_example_actually_runs():
    """The documented customisation path crashed on this package's own guard.

    README's private-overlay example passed `rho_grid=(0.0, 0.01, 0.05, 0.25)`
    into `derive()`. PUBLIC.rho_grid correctly omits 0.0 -- frozen is a
    control, not a churn rate, and `motion` refuses rho=0 by design
    ("rho=0 is not a churn rate, it is the frozen control"). So the example
    was accepted silently at config time and blew up later, when a motion was
    finally built from the grid, part way into a sweep.

    Two things were wrong and both are fixed: the example, and the fact that a
    configuration error surfaced three layers from the configuration. rho_grid
    is now validated where it is written.
    """
    from spdelta.profiles import PUBLIC, derive

    with pytest.raises(ValueError, match="outside \\(0, 1\\]"):
        derive(PUBLIC, name="mycorp-bench-v3", rho_grid=(0.0, 0.01, 0.05, 0.25))

    # The control: the corrected example must still be accepted, or the guard
    # is just refusing overlays.
    ok = derive(PUBLIC, name="mycorp-bench-v3", rho_grid=(0.01, 0.05, 0.25))
    assert ok.rho_grid == (0.01, 0.05, 0.25)
    assert ok.name == "mycorp-bench-v3"

    # And the README must not reintroduce it.
    import pathlib
    readme = pathlib.Path(__file__).resolve().parents[1] / "README.md"
    text = readme.read_text(encoding="utf-8")
    assert "rho_grid=(0.0," not in text, (
        "README's overlay example passes rho=0.0 again; it is refused by "
        "derive() and by motion, and it is the frozen control rather than a "
        "churn rate."
    )
