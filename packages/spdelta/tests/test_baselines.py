"""The rung ladder: every arm computes the same thing, differently."""

from __future__ import annotations

import numpy as np
import pytest
import scipy.sparse as sp

from spdelta import (
    ColumnDeltaCsc,
    CompactDelta,
    FullMatvec,
    MaskedRowScan,
    ScratchReference,
    banded,
    fanout,
    ladder,
    reference,
    rel_l2,
)


def stream(n_cols, n_dirty, batch, steps, seed=0, churn=0):
    """A deterministic update stream; ``churn`` columns replaced per step."""
    rng = np.random.default_rng(seed)
    cols = np.sort(
        rng.choice(n_cols, size=n_dirty, replace=False).astype(np.int32)
    )
    out = []
    for _ in range(steps):
        out.append((cols.copy(), rng.standard_normal((n_dirty, batch))))
        if churn:
            free = np.setdiff1d(np.arange(n_cols, dtype=np.int32), cols)
            positions = rng.choice(n_dirty, size=churn, replace=False)
            cols = cols.copy()
            cols[positions] = rng.choice(free, size=churn, replace=False)
            cols = np.sort(cols)
    return out


def as_delta(arm, cols, vals, m):
    d = CompactDelta(cols.copy(), vals.copy())
    return d if arm.delta_kind == "compact" else d.to_global(m)


def run(arm, a, updates):
    arm.prepare(a, updates[0][0])
    y = np.zeros((a.shape[0], updates[0][1].shape[1]), dtype=np.float64)
    for cols, vals in updates:
        arm.step(as_delta(arm, cols, vals, a.shape[1]), y)
    return y


# --------------------------------------------------------------------------
# they agree
# --------------------------------------------------------------------------


@pytest.mark.parametrize("build_operator", [lambda: banded(120, 5, 0), lambda: fanout(120, 4, 1)])
@pytest.mark.parametrize("churn", [0, 3])
def test_every_rung_agrees_with_the_oracle(build_operator, churn):
    a = build_operator()
    updates = stream(120, 16, 3, steps=12, seed=2, churn=churn)
    want = run(reference(), a, updates)
    for arm in ladder():
        got = run(arm, a, updates)
        assert rel_l2(got, want) < 1e-12, arm.name


def test_the_answer_is_the_product_of_the_operator_and_the_accumulated_state():
    """Not just self-consistent -- right, against an independent dense matmul."""
    a = banded(80, 3, 4)
    updates = stream(80, 10, 2, steps=7, seed=3, churn=2)
    x = np.zeros((80, 2))
    for cols, vals in updates:
        x[cols] += vals
    want = a.toarray() @ x
    for arm in ladder() + [reference()]:
        assert rel_l2(run(arm, a, updates), want) < 1e-12, arm.name


# --------------------------------------------------------------------------
# the encodings are enforced at the boundary
# --------------------------------------------------------------------------


def test_masked_row_scan_refuses_a_compact_delta():
    a = banded(40, 3, 0)
    arm = MaskedRowScan()
    arm.prepare(a, np.array([0, 1], dtype=np.int32))
    d = CompactDelta(np.array([0, 1], dtype=np.int32), np.ones((2, 1)))
    with pytest.raises(TypeError, match="indexed by column"):
        arm.step(d, np.zeros((40, 1)))


@pytest.mark.parametrize("arm_type", [FullMatvec, ColumnDeltaCsc, ScratchReference])
def test_compact_consumers_refuse_a_global_delta(arm_type):
    a = banded(40, 3, 0)
    arm = arm_type()
    arm.prepare(a, np.array([0, 1], dtype=np.int32))
    g = CompactDelta(np.array([0, 1], dtype=np.int32), np.ones((2, 1))).to_global(40)
    with pytest.raises(TypeError, match="position within the dirty set"):
        arm.step(g, np.zeros((40, 1)))


# --------------------------------------------------------------------------
# what the arms report about themselves
# --------------------------------------------------------------------------


def test_column_delta_recompiles_only_when_the_dirty_set_changes():
    a = banded(200, 5, 0)
    arm = ColumnDeltaCsc()

    run(arm, a, stream(200, 20, 2, steps=10, seed=1, churn=0))
    assert arm.recompiles == 0, "a frozen dirty set must not trigger a recompile"

    arm = ColumnDeltaCsc()
    run(arm, a, stream(200, 20, 2, steps=10, seed=1, churn=4))
    assert arm.recompiles == 9  # every step after the first


def test_column_delta_touches_only_the_dirty_columns_entries():
    """The rung's defining property, counted rather than inferred from a clock.

    An arm that got faster by touching fewer entries and an arm that got faster
    because the machine was quieter look identical in a timing column.
    """
    a = fanout(200, 5, seed=0)
    arm = ColumnDeltaCsc()
    updates = stream(200, 20, 1, steps=6, seed=0, churn=0)
    run(arm, a, updates)
    assert arm._slice.shape == (200, 20)
    assert arm._slice.nnz == 20 * 5
    assert arm.stats()["entries_touched"] == 6 * 20 * 5
    assert arm.stats()["entries_touched"] < a.nnz * 6


def test_masked_row_scan_marks_exactly_the_dirty_columns():
    """Its mask must not accumulate.

    Stale marks stay *correct* here, because the global buffer is zero outside
    the dirty set -- so this failure is invisible to the reference assertion and
    shows up only as an arm that gets slower every step.
    """
    a = banded(300, 5, 0)
    arm = MaskedRowScan()
    run(arm, a, stream(300, 24, 1, steps=8, seed=1, churn=6))
    assert int(arm._mask.sum()) == 24


def test_prepare_resets_all_state():
    a = banded(100, 3, 0)
    arm = ColumnDeltaCsc()
    run(arm, a, stream(100, 8, 1, steps=5, seed=0, churn=2))
    before = arm.steps
    run(arm, a, stream(100, 8, 1, steps=3, seed=0, churn=2))
    assert before == 5 and arm.steps == 3


def test_arms_reject_a_batch_change_mid_run():
    a = banded(60, 3, 0)
    arm = FullMatvec()
    arm.prepare(a, np.array([0], dtype=np.int32))
    arm.step(CompactDelta(np.array([0], dtype=np.int32), np.ones((1, 2))), np.zeros((60, 2)))
    with pytest.raises(ValueError, match="batch changed mid-run"):
        arm.step(
            CompactDelta(np.array([0], dtype=np.int32), np.ones((1, 3))),
            np.zeros((60, 3)),
        )


def test_arms_reject_a_wrongly_shaped_output():
    a = banded(60, 3, 0)
    arm = FullMatvec()
    arm.prepare(a, np.array([0], dtype=np.int32))
    with pytest.raises(ValueError, match="expected"):
        arm.step(
            CompactDelta(np.array([0], dtype=np.int32), np.ones((1, 2))),
            np.zeros((59, 2)),
        )


def test_arms_reject_a_non_float64_output():
    a = banded(60, 3, 0)
    arm = FullMatvec()
    arm.prepare(a, np.array([0], dtype=np.int32))
    with pytest.raises(TypeError, match="float64"):
        arm.step(
            CompactDelta(np.array([0], dtype=np.int32), np.ones((1, 2))),
            np.zeros((60, 2), dtype=np.float32),
        )


def test_the_ladder_is_in_rung_order_and_excludes_the_oracle():
    names = [arm.name for arm in ladder()]
    assert names == ["full_matvec", "masked_row_scan", "column_delta_csc"]
    assert "scratch_reference" not in names


def test_the_oracle_does_not_share_the_library_matmul_with_full_matvec():
    """An oracle that shares a code path can cancel that path's bug with itself."""
    import inspect

    from spdelta import baselines

    oracle = inspect.getsource(baselines.ScratchReference)
    assert "bincount" in oracle
    assert "@ self._x" not in oracle


# --------------------------------------------------------------------------
# rel_l2
# --------------------------------------------------------------------------


def test_rel_l2_of_a_zero_reference_is_infinite_unless_the_result_is_zero_too():
    zero = np.zeros((3, 1))
    assert rel_l2(zero, zero) == 0.0
    assert rel_l2(np.ones((3, 1)), zero) == float("inf")


def test_rel_l2_rejects_a_shape_mismatch():
    with pytest.raises(ValueError, match="shape mismatch"):
        rel_l2(np.zeros((3, 1)), np.zeros((4, 1)))
