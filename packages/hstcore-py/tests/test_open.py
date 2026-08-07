"""Opening, dimensions, batching, and lifetime — against the recording stub."""

from __future__ import annotations

import gc

import numpy as np
import pytest

import hstcore
from conftest import BATCH, CLOSE, OPEN, OPEN_BATCHED


def open_ctx(stub, **kw):
    return hstcore.HSTContext("op.bin", "token", **kw)


def test_batch_one_goes_through_the_plain_open(stub):
    with open_ctx(stub) as ctx:
        assert ctx.batch == 1
    assert stub.count(OPEN) == 1
    assert stub.count(OPEN_BATCHED) == 0


def test_batch_above_one_goes_through_the_batched_open(stub):
    with open_ctx(stub, batch=8) as ctx:
        assert ctx.batch == 8
        assert ctx.state_size == ctx.output_dim * 8
    assert stub.count(OPEN) == 0
    assert stub.count(OPEN_BATCHED) == 1


def test_dimensions_come_from_the_library(stub):
    stub.dims(64, 40)
    with open_ctx(stub) as ctx:
        assert ctx.output_dim == 64
        assert ctx.input_dim == 40


def test_lane_count_is_read_back_not_assumed(stub):
    # If the library disagrees with the request, every buffer length this
    # binding computes would be wrong. It refuses instead.
    stub.report_batch(3)
    with pytest.raises(hstcore.HSTInternalError) as exc:
        open_ctx(stub, batch=8)
    assert "3" in str(exc.value)
    assert stub.count(CLOSE) == 1  # and does not leak the handle
    assert stub.count(BATCH) == 1


def test_degenerate_operator_is_refused(stub):
    stub.dims(0, 5)
    with pytest.raises(hstcore.HSTInternalError):
        open_ctx(stub)
    assert stub.count(CLOSE) == 1


def test_open_failure_carries_the_libraries_reason(stub):
    stub.fail_open(b"license expired 2026-01-01")
    with pytest.raises(hstcore.HSTLicenseError) as exc:
        open_ctx(stub)
    assert "license expired 2026-01-01" in str(exc.value)


def test_open_failure_with_no_reason_still_explains(stub):
    stub.fail_open(b"")
    with pytest.raises(hstcore.HSTLicenseError) as exc:
        open_ctx(stub)
    assert "license" in str(exc.value)


@pytest.mark.parametrize("batch", [0, -1, 33, 100])
def test_batch_out_of_range_is_refused_before_the_library_is_touched(batch):
    # No stub fixture: this must fail without a library at all.
    with pytest.raises(hstcore.HSTArgumentError):
        hstcore.HSTContext("op.bin", "token", batch=batch)


@pytest.mark.parametrize("batch", [1.0, "8", None, True])
def test_batch_must_be_an_int(batch):
    with pytest.raises(hstcore.HSTArgumentError):
        hstcore.HSTContext("op.bin", "token", batch=batch)


def test_token_must_be_text():
    with pytest.raises(hstcore.HSTArgumentError):
        hstcore.HSTContext("op.bin", 12345)


def test_close_is_idempotent(stub):
    ctx = open_ctx(stub)
    ctx.close()
    ctx.close()
    ctx.close()
    assert stub.count(CLOSE) == 1
    assert ctx.closed


def test_use_after_close_raises(stub):
    ctx = open_ctx(stub)
    ctx.close()
    cols = np.zeros(1, dtype=np.int32)
    vals = np.zeros(1, dtype=np.float64)
    with pytest.raises(hstcore.HSTClosedError):
        ctx.apply(cols, vals)
    with pytest.raises(hstcore.HSTClosedError):
        ctx.state
    with pytest.raises(hstcore.HSTClosedError):
        ctx.recompute_full()
    with pytest.raises(hstcore.HSTClosedError):
        ctx.set_state(np.zeros(ctx.output_dim))


def test_context_manager_closes_on_exception(stub):
    with pytest.raises(RuntimeError):
        with open_ctx(stub):
            raise RuntimeError("boom")
    assert stub.count(CLOSE) == 1


def test_dropping_the_context_closes_the_handle(stub):
    open_ctx(stub)
    gc.collect()
    assert stub.count(CLOSE) == 1


def test_repr_says_closed(stub):
    ctx = open_ctx(stub)
    assert "batch=1" in repr(ctx)
    ctx.close()
    assert repr(ctx) == "<HSTContext closed>"
