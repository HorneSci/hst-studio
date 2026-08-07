"""The worked example must actually work, and the ladder must keep its shape."""

from __future__ import annotations

import numpy as np
import pytest

from spdelta import (
    ColumnDeltaCsc,
    FullMatvec,
    MaskedRowScan,
    ratio_rows,
    reduce_median_then_geomean,
    reference,
    standard_cells,
    suite,
    sweep,
)
from spdelta.example import motion_factories, run


def test_the_example_runs_end_to_end(tiny_profile, capsys):
    run(profile=tiny_profile, seeds=(17,))
    out = capsys.readouterr().out
    assert "vs masked_row_scan" in out
    assert "reduction   reduce_median_then_geomean" in out
    assert "measured ceiling" in out


def test_the_example_builds_four_named_motion_models(tiny_profile):
    operators = suite(tiny_profile)
    cells = standard_cells(
        operators, motion_factories(tiny_profile.drift_radius),
        seeds=(17,), profile=tiny_profile,
    )
    names = {c.motion.name for c in cells}
    assert "frozen" in names
    assert "jump_plain" in names
    assert "jump_nnz_matched" in names
    assert any(n.startswith("drift") for n in names)


def test_only_the_arm_that_compiles_something_reacts_to_churn(tiny_profile):
    """The shape the whole ladder exists to show.

    ``full_matvec`` and ``masked_row_scan`` cost O(nnz) whatever the dirty set
    does -- the set's *motion* is invisible to them. ``column_delta_csc``
    compiles a slice for the current set, so churn makes it rebuild. Asserted as
    a shape, never as a level: the levels here are laptop numbers on a toy
    operator and are not a result about anything.
    """
    from spdelta.profiles import ToySpec, derive

    profile = derive(
        tiny_profile,
        name="test-churn-shape",
        steps=20,
        repeats=2,
        n_dirty=64,
        rho_grid=(0.25,),
        operators=(
            ToySpec(name="band_3k_w7", kind="banded", n_cols=3000, param=7, seed=4),
        ),
    )
    cells = standard_cells(
        suite(profile),
        [motion_factories(profile.drift_radius)[0], motion_factories(0)[2]],
        seeds=(17, 18),
        profile=profile,
    )
    rows = sweep(
        [FullMatvec(), MaskedRowScan(), ColumnDeltaCsc()],
        cells,
        reference=reference(),
        profile=profile,
    )

    def cost(arm: str, is_frozen: bool) -> float:
        values = [
            r["seconds_per_step"]
            for r in rows
            if r["arm"] == arm and r["is_frozen"] is is_frozen
        ]
        return float(np.median(values))

    churn_penalty = {
        arm: cost(arm, False) / cost(arm, True)
        for arm in ("full_matvec", "masked_row_scan", "column_delta_csc")
    }
    # Stated as a contrast between arms rather than as an absolute band on each
    # one: this is the only timing-dependent assertion in the suite, and a busy
    # machine inflates every arm together, which a contrast survives and a band
    # does not.
    assert churn_penalty["column_delta_csc"] > 1.5
    assert churn_penalty["column_delta_csc"] > 1.5 * max(
        churn_penalty["full_matvec"], churn_penalty["masked_row_scan"]
    )


def test_every_arm_still_agrees_with_the_oracle_over_the_whole_grid(tiny_profile):
    """The sweep would have raised; this asserts the recorded errors too."""
    operators = suite(tiny_profile)
    cells = standard_cells(
        operators, motion_factories(tiny_profile.drift_radius),
        seeds=(17,), profile=tiny_profile,
    )
    rows = sweep(
        [FullMatvec(), MaskedRowScan(), ColumnDeltaCsc()],
        cells,
        reference=reference(),
        profile=tiny_profile,
    )
    assert rows
    assert max(r["rel_err"] for r in rows) < tiny_profile.tolerance
    assert all(np.isfinite(r["seconds_per_step"]) for r in rows)
