"""The hot path: what reaches C, and what is refused before it gets there."""

from __future__ import annotations

import numpy as np
import pytest

import hstcore
from conftest import APPLY, RECOMPUTE

N, M = 16, 12


def open_ctx(batch=1):
    return hstcore.HSTContext("op.bin", "token", batch=batch)


@pytest.fixture()
def ctx(stub):
    stub.dims(N, M)
    with open_ctx() as c:
        yield c


def cols_of(n=4):
    return np.arange(n, dtype=np.int32)


def vals_of(n=4, batch=1):
    return np.ones(n if batch == 1 else (n, batch), dtype=np.float64)


# -- the no-copy guarantee -------------------------------------------------


def test_the_arrays_reach_c_without_being_copied(ctx, stub):
    cols, vals = cols_of(), vals_of()
    ctx.apply(cols, vals)
    # The stub records the pointer it was handed. If the binding had rebuilt a
    # ctypes array from the input — as its predecessor did, per call, in the
    # loop whose whole premise is a sub-millisecond win — these would differ.
    assert stub.last_cols == cols.ctypes.data
    assert stub.last_vals == vals.ctypes.data
    assert stub.last_n == 4


def test_out_buffer_is_the_callers_own_memory(ctx, stub):
    out = np.empty(N, dtype=np.float64)
    got = ctx.apply(cols_of(), vals_of(), out=out)
    assert got is out
    assert stub.last_y_out == out.ctypes.data


def test_no_out_buffer_means_no_marshalling(ctx, stub):
    assert ctx.apply(cols_of(), vals_of()) is None
    assert stub.last_y_out == 0  # NULL: the dense output never leaves the library


def test_repeated_applies_allocate_nothing_new(ctx, stub):
    cols, vals = cols_of(8), vals_of(8)
    seen = set()
    for step in range(50):
        vals[:] = step
        ctx.apply(cols, vals)
        seen.add((stub.last_cols, stub.last_vals))
    assert len(seen) == 1
    assert stub.count(APPLY) == 50


def test_empty_delta_is_allowed(ctx, stub):
    ctx.apply(np.empty(0, dtype=np.int32), np.empty(0, dtype=np.float64))
    assert stub.last_n == 0


# -- batching ---------------------------------------------------------------


def test_lane_interleaved_vals_accepted_two_dimensional(stub):
    stub.dims(N, M)
    with open_ctx(batch=4) as c:
        vals = np.ones((6, 4), dtype=np.float64)
        c.apply(cols_of(6), vals)
        assert stub.last_vals == vals.ctypes.data
        assert stub.last_n == 6


def test_lane_interleaved_vals_accepted_flat(stub):
    stub.dims(N, M)
    with open_ctx(batch=4) as c:
        c.apply(cols_of(6), np.ones(24, dtype=np.float64))
        assert stub.last_n == 6


def test_vals_length_must_match_n_times_batch(stub):
    stub.dims(N, M)
    with open_ctx(batch=4) as c:
        with pytest.raises(hstcore.HSTArgumentError) as exc:
            c.apply(cols_of(6), np.ones(6, dtype=np.float64))
        assert "24" in str(exc.value)


def test_out_must_be_output_dim_times_batch(stub):
    stub.dims(N, M)
    with open_ctx(batch=2) as c:
        with pytest.raises(hstcore.HSTArgumentError) as exc:
            c.apply(cols_of(), vals_of(4, 2), out=np.empty(N, dtype=np.float64))
        assert str(N * 2) in str(exc.value)


# -- what is refused, and why ----------------------------------------------


@pytest.mark.parametrize(
    "bad,why",
    [
        pytest.param([0, 1, 2, 3], "list", id="python-list"),
        pytest.param((0, 1, 2, 3), "tuple", id="python-tuple"),
        pytest.param(np.arange(4, dtype=np.int64), "dtype", id="int64"),
        pytest.param(np.arange(4, dtype=np.float64), "dtype", id="float64"),
        pytest.param(np.arange(8, dtype=np.int32)[::2], "contiguous", id="strided"),
    ],
)
def test_cols_that_would_need_a_copy_are_refused(ctx, bad, why):
    with pytest.raises(hstcore.HSTBufferError) as exc:
        ctx.apply(bad, vals_of())
    assert "cols" in str(exc.value)


@pytest.mark.parametrize(
    "bad",
    [
        [1.0, 2.0, 3.0, 4.0],
        np.ones(4, dtype=np.float32),
        np.ones(4, dtype=np.int32),
        np.ones(8, dtype=np.float64)[::2],
    ],
)
def test_vals_that_would_need_a_copy_are_refused(ctx, bad):
    with pytest.raises(hstcore.HSTBufferError) as exc:
        ctx.apply(cols_of(), bad)
    assert "vals" in str(exc.value)


def test_the_refusal_explains_itself(ctx):
    with pytest.raises(hstcore.HSTBufferError) as exc:
        ctx.apply([0, 1, 2, 3], vals_of())
    msg = str(exc.value)
    assert "copy" in msg  # says what it is protecting
    assert "outside" in msg  # and what to do instead


def test_fortran_ordered_vals_are_refused(stub):
    stub.dims(N, M)
    with open_ctx(batch=4) as c:
        vals = np.asfortranarray(np.ones((6, 4), dtype=np.float64))
        with pytest.raises(hstcore.HSTBufferError) as exc:
            c.apply(cols_of(6), vals)
        assert "contiguous" in str(exc.value)


def test_cols_must_be_one_dimensional(ctx):
    with pytest.raises(hstcore.HSTArgumentError):
        ctx.apply(np.zeros((2, 2), dtype=np.int32), np.ones(4, dtype=np.float64))


def test_read_only_out_is_refused(ctx):
    out = np.empty(N, dtype=np.float64)
    out.flags.writeable = False
    with pytest.raises(hstcore.HSTBufferError) as exc:
        ctx.apply(cols_of(), vals_of(), out=out)
    assert "writeable" in str(exc.value)


def test_the_state_view_is_refused_as_an_output_buffer(ctx):
    # Would have the library writing into the buffer it reads from.
    with pytest.raises(hstcore.HSTBufferError) as exc:
        ctx.apply(cols_of(), vals_of(), out=ctx.state)
    assert "reading from" in str(exc.value)
    with pytest.raises(hstcore.HSTBufferError):
        ctx.recompute_full(out=ctx.state)


def test_a_refused_argument_never_reaches_the_library(ctx, stub):
    with pytest.raises(hstcore.HSTBufferError):
        ctx.apply([0, 1], [1.0, 2.0])
    assert stub.count(APPLY) == 0


# -- return codes on the real entry point ----------------------------------


@pytest.mark.parametrize(
    "rc,cls",
    [
        (-1, hstcore.HSTArgumentError),
        (-2, hstcore.HSTInternalError),
        (-3, hstcore.HSTQuotaError),
    ],
)
def test_apply_codes_surface_as_their_own_exceptions(ctx, stub, rc, cls):
    stub.force(APPLY, rc)
    with pytest.raises(cls):
        ctx.apply(cols_of(), vals_of())


# -- the reference arm ------------------------------------------------------


def test_recompute_full_allocates_when_no_buffer_is_given(ctx, stub):
    y = ctx.recompute_full()
    assert y.shape == (N,)
    assert y.dtype == np.float64
    assert stub.count(RECOMPUTE) == 1


def test_recompute_full_writes_into_a_caller_buffer(ctx, stub):
    out = np.zeros(N, dtype=np.float64)
    got = ctx.recompute_full(out)
    assert got is out
    assert stub.last_y_out == out.ctypes.data


def test_recompute_full_is_batch_shaped(stub):
    stub.dims(N, M)
    with open_ctx(batch=4) as c:
        assert c.recompute_full().shape == (N, 4)


def test_recompute_full_does_not_claim_a_mode(ctx):
    # It is not metered and it is not an apply, so it must not decide whether
    # this handle is a production or a shadow handle.
    ctx.recompute_full()
    assert ctx.mode is None
    ctx.apply_shadow(cols_of(), vals_of())
    assert ctx.mode == "shadow"


def test_recompute_full_errors_map(ctx, stub):
    stub.force(RECOMPUTE, -2)
    with pytest.raises(hstcore.HSTInternalError):
        ctx.recompute_full()
