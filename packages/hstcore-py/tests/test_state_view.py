"""The state-view guard, tested without any library.

A StateView needs only something with an ``_epoch`` attribute to stamp against,
so the whole invalidation contract can be exercised over ordinary numpy memory.
"""

from __future__ import annotations

import numpy as np
import pytest

from hstcore import HSTStateExpiredError, StateView


class FakeOwner:
    """Stands in for a context: all the view needs is an epoch to compare."""

    def __init__(self) -> None:
        self._epoch = 0


@pytest.fixture()
def pair():
    owner = FakeOwner()
    base = np.arange(6, dtype=np.float64)
    base.flags.writeable = False
    return owner, StateView(base, owner, owner._epoch)


def test_reads_work_while_fresh(pair):
    _, view = pair
    assert view[0] == 0.0
    assert float(np.sum(view)) == 15.0
    assert (view + 1)[0] == 1.0


def test_is_not_writeable(pair):
    _, view = pair
    assert not view.flags.writeable
    with pytest.raises(ValueError):
        view[0] = 1.0


def test_indexing_raises_after_the_epoch_moves(pair):
    owner, view = pair
    owner._epoch += 1
    with pytest.raises(HSTStateExpiredError):
        view[0]


@pytest.mark.parametrize(
    "read",
    [
        pytest.param(lambda v: v[0], id="index"),
        pytest.param(lambda v: v[1:3], id="slice"),
        pytest.param(lambda v: list(v), id="iterate"),
        pytest.param(lambda v: v + 1, id="ufunc-add"),
        pytest.param(lambda v: np.sqrt(v), id="ufunc-call"),
        pytest.param(lambda v: v > 0, id="ufunc-compare"),
        pytest.param(lambda v: np.sum(v), id="array-function"),
        pytest.param(lambda v: np.concatenate([v, v]), id="array-function-nested"),
        pytest.param(lambda v: v.copy(), id="copy"),
        pytest.param(lambda v: v.tolist(), id="tolist"),
        pytest.param(lambda v: v.astype(np.float32), id="astype"),
        pytest.param(lambda v: float(v.reshape(3, 2)[0, 0:1].reshape(())), id="float"),
    ],
)
def test_every_guarded_read_raises_when_stale(pair, read):
    owner, view = pair
    assert read(view) is not None  # the same read works while fresh
    owner._epoch += 1
    with pytest.raises(HSTStateExpiredError):
        read(view)


def test_slices_of_a_view_stay_guarded(pair):
    owner, view = pair
    part = view[2:4]
    assert isinstance(part, StateView)
    owner._epoch += 1
    with pytest.raises(HSTStateExpiredError):
        part[0]


def test_copy_survives_the_next_epoch(pair):
    owner, view = pair
    kept = view.copy()
    owner._epoch += 1
    assert kept[0] == 0.0  # a detached copy is the documented escape hatch
    assert kept.flags.writeable


def test_expired_property_flips(pair):
    owner, view = pair
    assert view.expired is False
    owner._epoch += 1
    assert view.expired is True


def test_repr_never_raises(pair):
    owner, view = pair
    assert "StateView" in repr(view)
    owner._epoch += 1
    assert "EXPIRED" in repr(view)  # a debugger must not blow up on a stale view


def test_view_outliving_its_owner_is_expired_not_a_use_after_free():
    owner = FakeOwner()
    base = np.zeros(4, dtype=np.float64)
    view = StateView(base, owner, 0)
    del owner
    import gc

    gc.collect()
    assert view.expired
    with pytest.raises(HSTStateExpiredError):
        view[0]


def test_message_points_at_the_fix(pair):
    owner, view = pair
    owner._epoch += 1
    with pytest.raises(HSTStateExpiredError) as exc:
        view[0]
    assert ".copy()" in str(exc.value)
