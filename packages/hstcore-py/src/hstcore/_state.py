"""A version-stamped, read-only, zero-copy view of the held dense state.

``hst_state`` returns a pointer into the library's own buffer, valid *only*
until the next apply, ``set_state`` or ``close``. A plain ``numpy`` array over
that pointer is a loaded gun: it keeps working, silently, after the memory it
describes has been reused, and the wrong numbers it then reports look exactly
like right ones.

:class:`StateView` is an ``ndarray`` subclass carrying the epoch of the context
it was taken from. Every read it can intercept re-checks that epoch first and
raises :class:`~hstcore.HSTStateExpiredError` if the context has moved on.

**What is guarded** (each has a test): indexing and slicing, iteration,
``numpy`` ufuncs (``view + 1``, ``np.sqrt(view)``, comparisons), functions that
dispatch through ``__array_function__`` (``np.sum``, ``np.concatenate``, ...),
``copy()``, ``tolist()``, ``astype()``, and ``float()`` of a scalar view.

**What is not, and cannot be**: anything that takes the raw pointer or the
buffer without going through Python — ``memoryview(view)``, ``view.ctypes.data``,
``view.__array_interface__``, or a C extension handed the object. Those are
outside interception by construction. If you need the numbers to outlive the
next apply, call ``.copy()`` — while the view is live — and keep the copy.
"""

from __future__ import annotations

import weakref
from typing import Any

import numpy as np

from ._errors import HSTStateExpiredError

__all__ = ["StateView"]


def _scrub(obj: Any) -> Any:
    """Check any state views in ``obj`` and demote them to plain arrays.

    Recurses into lists and tuples so that ``np.concatenate([view, other])``
    checks the view and then dispatches to the ordinary ``ndarray`` path
    instead of re-entering this class.
    """
    if isinstance(obj, StateView):
        obj._check()
        return obj.view(np.ndarray)
    if isinstance(obj, (list, tuple)):
        return type(obj)(_scrub(x) for x in obj)
    return obj


class StateView(np.ndarray):
    """Read-only zero-copy view of a context's dense output state.

    Never constructed directly — obtain one from
    :attr:`hstcore.HSTContext.state`.
    """

    _owner: Any = None
    _epoch: Any = None

    def __new__(cls, base: np.ndarray, owner: Any, epoch: int) -> "StateView":
        obj = base.view(cls)
        obj._owner = weakref.ref(owner)
        obj._epoch = epoch
        return obj

    def __array_finalize__(self, obj: Any) -> None:
        if obj is None:
            return
        # Views and slices inherit the stamp, so a slice of a state view is
        # guarded exactly as tightly as the view it came from.
        self._owner = getattr(obj, "_owner", None)
        self._epoch = getattr(obj, "_epoch", None)

    # -- the guard ---------------------------------------------------------

    @property
    def expired(self) -> bool:
        """True once the context has applied, set state, or closed."""
        owner = self._owner() if self._owner is not None else None
        return owner is None or owner._epoch != self._epoch

    def _check(self) -> None:
        owner = self._owner() if self._owner is not None else None
        if owner is None:
            raise HSTStateExpiredError(
                "state view outlived its context; the buffer it pointed into is "
                "no longer owned by anything. Take a fresh view, or .copy() next time."
            )
        if owner._epoch != self._epoch:
            raise HSTStateExpiredError(
                f"state view is stale (taken at epoch {self._epoch}, context is at "
                f"epoch {owner._epoch}). hst_state is valid only until the next "
                f"apply / set_state / close. Re-read .state, or .copy() the view "
                f"if you need the numbers to survive the next call."
            )

    # -- intercepted reads --------------------------------------------------

    def __getitem__(self, key: Any) -> Any:
        self._check()
        return super().__getitem__(key)

    def __iter__(self) -> Any:
        self._check()
        return iter(self.view(np.ndarray))

    def __array_ufunc__(self, ufunc: Any, method: str, *inputs: Any, **kwargs: Any) -> Any:
        self._check()
        scrubbed = tuple(_scrub(x) for x in inputs)
        if "out" in kwargs and kwargs["out"] is not None:
            kwargs = dict(kwargs)
            kwargs["out"] = _scrub(kwargs["out"])
        return getattr(ufunc, method)(*scrubbed, **kwargs)

    def __array_function__(self, func: Any, types: Any, args: Any, kwargs: Any) -> Any:
        self._check()
        return func(*_scrub(tuple(args)), **{k: _scrub(v) for k, v in kwargs.items()})

    def __float__(self) -> float:
        self._check()
        return float(self.view(np.ndarray))

    def __int__(self) -> int:
        self._check()
        return int(self.view(np.ndarray))

    def copy(self, order: str = "C") -> np.ndarray:
        """Detach a plain, writeable ``ndarray`` that survives the next apply."""
        self._check()
        return self.view(np.ndarray).copy(order=order)

    def astype(self, *args: Any, **kwargs: Any) -> np.ndarray:
        self._check()
        return self.view(np.ndarray).astype(*args, **kwargs)

    def tolist(self) -> Any:
        self._check()
        return self.view(np.ndarray).tolist()

    # -- diagnostics, which must never raise --------------------------------

    def __repr__(self) -> str:
        if self.expired:
            return f"<StateView shape={self.shape} EXPIRED>"
        return "StateView(" + np.array2string(self.view(np.ndarray), threshold=8) + ")"

    __str__ = __repr__
