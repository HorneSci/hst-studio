"""State: shape, zero-copy, and the invalidation rule from hstcore.h."""

from __future__ import annotations

import numpy as np
import pytest

import hstcore
from conftest import SET_STATE, STATE

N, M = 16, 12


@pytest.fixture()
def ctx(stub):
    stub.dims(N, M)
    with hstcore.HSTContext("op.bin", "token") as c:
        yield c


def cols():
    return np.arange(4, dtype=np.int32)


def vals():
    return np.ones(4, dtype=np.float64)


def test_state_is_a_view_over_the_librarys_own_buffer(ctx, stub):
    y = ctx.state
    assert isinstance(y, hstcore.StateView)
    assert y.shape == (N,)
    assert y.dtype == np.float64
    assert not y.flags.writeable
    assert stub.count(STATE) == 1


def test_state_is_lane_shaped_under_batching(stub):
    stub.dims(N, M)
    with hstcore.HSTContext("op.bin", "token", batch=4) as c:
        assert c.state.shape == (N, 4)
        assert c.state_size == N * 4


def test_set_state_round_trips_through_the_library(ctx, stub):
    y0 = np.arange(N, dtype=np.float64) * 0.5
    ctx.set_state(y0)
    assert stub.last_set_len == N
    assert np.array_equal(ctx.state.copy(), y0)


def test_set_state_length_is_checked_here_not_there(ctx, stub):
    with pytest.raises(hstcore.HSTArgumentError) as exc:
        ctx.set_state(np.zeros(N - 1, dtype=np.float64))
    assert str(N) in str(exc.value)
    assert stub.count(SET_STATE) == 0


def test_set_state_dtype_is_checked(ctx):
    with pytest.raises(hstcore.HSTBufferError):
        ctx.set_state(np.zeros(N, dtype=np.float32))


def test_set_state_errors_map(ctx, stub):
    stub.force(SET_STATE, -1)
    with pytest.raises(hstcore.HSTArgumentError):
        ctx.set_state(np.zeros(N, dtype=np.float64))


def test_apply_expires_an_outstanding_view(ctx):
    y = ctx.state
    y[0]  # fine
    ctx.apply(cols(), vals())
    with pytest.raises(hstcore.HSTStateExpiredError):
        y[0]


def test_shadow_apply_expires_an_outstanding_view(ctx):
    y = ctx.state
    ctx.apply_shadow(cols(), vals())
    with pytest.raises(hstcore.HSTStateExpiredError):
        y[0]


def test_set_state_expires_an_outstanding_view(ctx):
    y = ctx.state
    ctx.set_state(np.zeros(N, dtype=np.float64))
    with pytest.raises(hstcore.HSTStateExpiredError):
        y[0]


def test_close_expires_an_outstanding_view(ctx):
    y = ctx.state
    ctx.close()
    with pytest.raises(hstcore.HSTStateExpiredError):
        y[0]


def test_a_failed_apply_still_expires_the_view(ctx, stub):
    from conftest import APPLY

    y = ctx.state
    stub.force(APPLY, -2)
    with pytest.raises(hstcore.HSTInternalError):
        ctx.apply(cols(), vals())
    # The library may have written part of the state before it failed; a view
    # that survived would be reporting a half-updated buffer as if it were fine.
    with pytest.raises(hstcore.HSTStateExpiredError):
        y[0]


def test_recompute_full_does_not_expire_the_view(ctx):
    # It writes into the caller's buffer and does not disturb the held state,
    # so hstcore.h's validity rule does not fire for it.
    y = ctx.state
    ctx.recompute_full()
    assert y[0] == 0.0


def test_a_fresh_view_is_valid_after_an_apply(ctx):
    ctx.apply(cols(), vals())
    assert ctx.state[0] == 0.0


def test_state_survives_as_a_copy(ctx):
    ctx.set_state(np.arange(N, dtype=np.float64))
    kept = ctx.state.copy()
    ctx.apply(cols(), vals())
    assert kept[3] == 3.0
