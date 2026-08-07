"""Motion models: the frozen control, the swap count, and the jump confound."""

from __future__ import annotations

import numpy as np
import pytest
import scipy.sparse as sp

from spdelta import (
    Topology,
    drift,
    fanout,
    frozen,
    jump_nnz_matched,
    jump_plain,
    mix,
    slice_drift,
    slice_weight,
)


def dirty(n=40, start=100) -> np.ndarray:
    return np.arange(start, start + n, dtype=np.int32)


def spread_dirty(n=40, n_cols=400, seed=0) -> np.ndarray:
    """Local but not solid, so a drift model has somewhere to move to."""
    rng = np.random.default_rng(seed)
    return np.sort(rng.choice(120, size=n, replace=False).astype(np.int32) + 100)


# --------------------------------------------------------------------------
# frozen is a distinct object, not rho=0
# --------------------------------------------------------------------------


def test_frozen_never_moves():
    motion = frozen()
    rng = np.random.default_rng(0)
    d = dirty()
    for _ in range(50):
        d = motion.advance(d, rng)
    assert np.array_equal(d, dirty())


def test_frozen_declares_itself():
    assert frozen().is_frozen is True
    assert frozen().rho == 0.0
    assert frozen().name == "frozen"


def test_churning_models_refuse_rho_zero():
    """rho=0 must not be expressible as drift or jump. It is the control."""
    topology = Topology.line(400, radius=4)
    for build in (
        lambda: drift(topology, 0.0),
        lambda: jump_plain(400, 0.0),
        lambda: jump_nnz_matched(fanout(64, 4, 0), 0.0),
    ):
        with pytest.raises(ValueError, match="frozen control"):
            build()


def test_churning_models_refuse_negative_and_over_one():
    with pytest.raises(ValueError):
        jump_plain(400, -0.1)
    with pytest.raises(ValueError):
        jump_plain(400, 1.5)


# --------------------------------------------------------------------------
# the swap count: no clamp to one
# --------------------------------------------------------------------------


def test_swap_count_that_rounds_to_zero_raises_rather_than_clamping():
    """The clamp that made a 'frozen' control swap one column every step."""
    motion = jump_plain(1000, 0.01)
    with pytest.raises(ValueError, match="rounds to zero swaps"):
        motion.n_swap(10)


def test_swap_count_is_exactly_the_rounded_product():
    motion = jump_plain(1000, 0.25)
    assert motion.n_swap(40) == 10
    assert motion.n_swap(100) == 25


def test_swap_count_moves_exactly_that_many_columns():
    motion = jump_plain(4000, 0.25)
    rng = np.random.default_rng(0)
    before = dirty(40)
    after = motion.advance(before, rng)
    assert np.intersect1d(before, after).size == 30


# --------------------------------------------------------------------------
# invariants every model must hold
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "build",
    [
        lambda: drift(Topology.line(400, radius=6), 0.25),
        lambda: jump_plain(400, 0.25),
        lambda: jump_nnz_matched(fanout(400, 5, 0), 0.25),
    ],
)
def test_advance_preserves_size_sortedness_and_uniqueness(build):
    motion = build()
    rng = np.random.default_rng(1)
    d = spread_dirty()
    for _ in range(20):
        d = motion.advance(d, rng)
        assert d.size == 40
        assert np.unique(d).size == d.size
        assert np.array_equal(d, np.sort(d))


@pytest.mark.parametrize(
    "build",
    [
        lambda: drift(Topology.line(400, radius=6), 0.25),
        lambda: jump_plain(400, 0.25),
    ],
)
def test_advance_does_not_mutate_its_input(build):
    motion = build()
    rng = np.random.default_rng(2)
    d = spread_dirty()
    keep = d.copy()
    motion.advance(d, rng)
    assert np.array_equal(d, keep)


# --------------------------------------------------------------------------
# drift is local; jump is not
# --------------------------------------------------------------------------


def test_drift_replacements_come_from_the_topology():
    """Every arrival is within one hop of a column that was dirty last step.

    Measured against the whole previous set rather than against the columns
    that departed: within a single advance, a retired column can itself be
    drawn as another retiree's replacement, so a new arrival's parent is not
    always still missing at the end of the step.
    """
    radius = 3
    topology = Topology.line(400, radius=radius)
    motion = drift(topology, 0.25)
    rng = np.random.default_rng(3)
    d = spread_dirty()
    for _ in range(10):
        nxt = motion.advance(d, rng)
        for col in np.setdiff1d(nxt, d):
            assert (np.abs(d.astype(np.int64) - int(col)) <= radius).any()
        d = nxt


def test_jump_plain_leaves_the_neighbourhood():
    motion = jump_plain(4000, 0.25)
    rng = np.random.default_rng(4)
    d = dirty(40, start=100)
    nxt = motion.advance(d, rng)
    arrived = np.setdiff1d(nxt, d)
    assert (arrived > 500).any()


# --------------------------------------------------------------------------
# the confound: nnz-matched jump holds the slice weight, plain jump does not
# --------------------------------------------------------------------------


def _skewed_operator(n_cols=600, seed=0) -> sp.csc_matrix:
    """Column densities spanning an order of magnitude.

    A uniform-density operator cannot show the confound at all, which is why a
    sweep on one would report "jump is jump" and be wrong about every other
    operator.
    """
    rng = np.random.default_rng(seed)
    cols, rows = [], []
    for j in range(n_cols):
        k = 40 if j < n_cols // 10 else 2
        rows.extend(rng.choice(n_cols, size=k, replace=False).tolist())
        cols.extend([j] * k)
    data = np.ones(len(rows))
    return sp.csc_matrix(
        sp.coo_matrix((data, (rows, cols)), shape=(n_cols, n_cols))
    )


def _weight_drift(motion, a, start, steps=60, seed=0) -> float:
    rng = np.random.default_rng(seed)
    d = start
    first = slice_weight(a, d)
    for _ in range(steps):
        d = motion.advance(d, rng)
    return slice_drift(first, slice_weight(a, d))


def test_nnz_matched_jump_holds_the_slice_weight_and_plain_jump_does_not():
    a = _skewed_operator()
    start = np.arange(0, 40, dtype=np.int32)  # the dense tenth of the operator
    plain = _weight_drift(jump_plain(600, 0.25), a, start)
    matched = _weight_drift(jump_nnz_matched(a, 0.25, bands=8), a, start)
    assert matched < 0.02
    assert plain > 0.5
    assert plain > matched


def test_nnz_matched_jump_is_still_non_local():
    a = _skewed_operator()
    motion = jump_nnz_matched(a, 0.25, bands=8)
    rng = np.random.default_rng(5)
    d = np.arange(0, 40, dtype=np.int32)
    nxt = motion.advance(d, rng)
    arrived = np.setdiff1d(nxt, d)
    assert arrived.size > 0
    assert (np.abs(arrived[:, None] - d[None, :]).min(axis=1) > 1).any()


def test_nnz_matched_jump_rejects_a_band_count_below_one():
    with pytest.raises(ValueError, match="bands must be >= 1"):
        jump_nnz_matched(fanout(64, 4, 0), 0.25, bands=0)


def test_jump_finds_a_replacement_even_when_almost_every_column_is_dirty():
    """The exhaustive fallback, not the 64 random tries.

    With one free column in thirty, a bounded random search fails often enough
    to matter. A model that gave up there would silently run below its nominal
    churn rate -- which is the mislabelled-control failure again, arriving as a
    quiet shortfall rather than as a wrong label.
    """
    motion = jump_plain(30, 1.0)
    rng = np.random.default_rng(7)
    d = np.arange(29, dtype=np.int32)
    for _ in range(5):
        nxt = motion.advance(d, rng)
        assert nxt.size == 29
        assert np.unique(nxt).size == 29
        d = nxt
    assert motion.stalls == 0


def test_slice_drift_refuses_an_empty_first_slice():
    with pytest.raises(ValueError, match="not defined"):
        slice_drift(0, 5)


def test_slice_weight_counts_column_nonzeros():
    a = fanout(50, 4, seed=0)
    assert slice_weight(a, np.array([0, 1, 2], dtype=np.int32)) == 12


# --------------------------------------------------------------------------
# mix
# --------------------------------------------------------------------------


def test_mix_rejects_components_with_different_rates():
    local = drift(Topology.line(400, radius=4), 0.25)
    far = jump_plain(400, 0.05)
    with pytest.raises(ValueError, match="share a churn rate"):
        mix(local, far, 0.5)


def test_mix_rejects_alpha_outside_the_unit_interval():
    local = drift(Topology.line(400, radius=4), 0.25)
    far = jump_plain(400, 0.25)
    with pytest.raises(ValueError, match="alpha"):
        mix(local, far, 1.5)


def test_mix_at_alpha_zero_stays_local_and_at_one_does_not():
    topology = Topology.line(4000, radius=3)
    local = drift(topology, 0.25)
    far = jump_plain(4000, 0.25)

    def far_arrivals(alpha: float) -> int:
        motion = mix(local, far, alpha)
        rng = np.random.default_rng(6)
        d = spread_dirty(40, 4000)
        count = 0
        for _ in range(20):
            nxt = motion.advance(d, rng)
            arrived = np.setdiff1d(nxt, d)
            count += int((arrived > 1000).sum())
            d = nxt
        return count

    assert far_arrivals(0.0) == 0
    assert far_arrivals(1.0) > 0


def test_mix_name_records_both_components_and_alpha():
    local = drift(Topology.line(400, radius=4), 0.25)
    far = jump_plain(400, 0.25)
    name = mix(local, far, 0.25).name
    assert "drift" in name and "jump_plain" in name and "0.25" in name


def test_every_model_carries_a_name():
    a = fanout(100, 4, 0)
    for motion in (
        frozen(),
        drift(Topology.line(100, radius=2), 0.25),
        jump_plain(100, 0.25),
        jump_nnz_matched(a, 0.25),
    ):
        assert isinstance(motion.name, str) and motion.name
