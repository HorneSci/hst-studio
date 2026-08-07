"""Shadow mode, and the separation the header asks for in a comment.

hstcore.h: "Never interleave shadow and production applies on one hst_ctx --
open a separate handle for shadow-mode validation." A comment cannot stop
anyone. Here it is an exception, raised before the call is made.
"""

from __future__ import annotations

import numpy as np
import pytest

import hstcore
from conftest import APPLY, SHADOW

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


def test_shadow_calls_the_shadow_entry_point(ctx, stub):
    ctx.apply_shadow(cols(), vals())
    assert stub.count(SHADOW) == 1
    assert stub.count(APPLY) == 0


def test_production_then_shadow_is_refused(ctx, stub):
    ctx.apply(cols(), vals())
    with pytest.raises(hstcore.HSTModeError) as exc:
        ctx.apply_shadow(cols(), vals())
    assert "interleave" in str(exc.value)
    assert "separate context" in str(exc.value) or "second context" in str(exc.value)
    assert stub.count(SHADOW) == 0  # refused before the library was called


def test_shadow_then_production_is_refused(ctx, stub):
    ctx.apply_shadow(cols(), vals())
    with pytest.raises(hstcore.HSTModeError):
        ctx.apply(cols(), vals())
    assert stub.count(APPLY) == 0


def test_the_mode_is_visible(ctx):
    assert ctx.mode is None
    ctx.apply(cols(), vals())
    assert ctx.mode == "production"


def test_a_failed_apply_still_claims_the_mode(ctx, stub):
    # The library may have touched the shared buffers before returning the code,
    # so the handle is committed either way.
    stub.force(SHADOW, -3)
    with pytest.raises(hstcore.HSTQuotaError):
        ctx.apply_shadow(cols(), vals())
    assert ctx.mode == "shadow"
    with pytest.raises(hstcore.HSTModeError):
        ctx.apply(cols(), vals())


def test_two_contexts_can_run_the_two_modes(stub):
    stub.dims(N, M)
    with hstcore.HSTContext("op.bin", "token") as prod:
        with hstcore.HSTContext("op.bin", "token") as shadow:
            prod.apply(cols(), vals())
            shadow.apply_shadow(cols(), vals())
    assert stub.count(APPLY) == 1
    assert stub.count(SHADOW) == 1


def test_missing_shadow_grant_is_its_own_error(ctx, stub):
    stub.force(SHADOW, -4)
    with pytest.raises(hstcore.HSTShadowNotGrantedError):
        ctx.apply_shadow(cols(), vals())


def test_shadow_quota_is_not_production_quota(ctx, stub):
    stub.force(SHADOW, -3)
    with pytest.raises(hstcore.HSTQuotaError) as exc:
        ctx.apply_shadow(cols(), vals())
    assert "shadow" in str(exc.value)


def test_shadow_takes_the_same_buffers_with_no_copy(ctx, stub):
    c, v = cols(), vals()
    out = np.empty(N, dtype=np.float64)
    ctx.apply_shadow(c, v, out=out)
    assert stub.last_cols == c.ctypes.data
    assert stub.last_vals == v.ctypes.data
    assert stub.last_y_out == out.ctypes.data
