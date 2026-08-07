"""The context object: one open session over one compiled operator."""

from __future__ import annotations

import ctypes
import os
from typing import Any, Optional

import numpy as np

from ._errors import (
    HSTArgumentError,
    HSTBufferError,
    HSTClosedError,
    HSTInternalError,
    HSTLicenseError,
    HSTModeError,
    HSTQuotaError,
    HSTShadowNotGrantedError,
    HSTError,
)
from ._ffi import load_library
from ._state import StateView

__all__ = ["HSTContext"]

_ERRBUF = 256
_MAX_BATCH = 32
_I32 = np.dtype(np.int32)
_F64 = np.dtype(np.float64)
_INT32_MAX = 2**31 - 1

_PRODUCTION = "production"
_SHADOW = "shadow"

#: Return code -> (exception class, what the code means).
#: ``hstcore.h`` documents these on ``hst_apply_shadow``; the other entry points
#: say only "negative on error" and use the same codes.
_CODES: dict[int, tuple[type, str]] = {
    -1: (HSTArgumentError, "bad arguments"),
    -2: (HSTInternalError, "internal exception inside the library"),
    -3: (HSTQuotaError, "quota exhausted"),
    -4: (HSTShadowNotGrantedError, "license carries no shadow-apply grant"),
}

_DETAIL: dict[tuple[str, int], str] = {
    ("hst_apply_delta", -3): (
        "the license's production apply budget is spent. The shadow budget is "
        "metered separately and is not affected."
    ),
    ("hst_apply_shadow", -3): (
        "the license's shadow-apply budget is spent. The production budget is "
        "metered separately and is not affected."
    ),
    ("hst_apply_shadow", -4): (
        "shadow rights come only from the signed token, and this one grants "
        "none. Nothing in this binding, or any flag or environment variable, "
        "can turn shadow mode on; the token has to be reissued."
    ),
}


def _raise_for(rc: int, entry: str) -> None:
    if rc == 0:
        return
    cls, meaning = _CODES.get(rc, (HSTError, "undocumented return code"))
    detail = _DETAIL.get((entry, rc))
    msg = f"{entry} returned {rc}: {meaning}"
    if detail:
        msg += f" — {detail}"
    raise cls(msg)


def _describe(a: Any) -> str:
    if isinstance(a, np.ndarray):
        order = "C" if a.flags.c_contiguous else ("F" if a.flags.f_contiguous else "non-contiguous")
        return f"ndarray(dtype={a.dtype}, shape={a.shape}, {order})"
    return type(a).__name__


def _check_array(a: Any, dtype: np.dtype, name: str, *, writeable: bool = False) -> np.ndarray:
    """Reject anything that would have to be copied to be passed."""
    if isinstance(a, StateView):
        if writeable:
            raise HSTBufferError(
                f"{name} must not be the context's own state view: the library "
                f"would be writing into the buffer it is reading from. Pass a "
                f"separate array, or omit the argument."
            )
        a._check()
    if not isinstance(a, np.ndarray):
        raise HSTBufferError(
            f"{name} must be a numpy.ndarray with dtype {dtype}, got {_describe(a)}. "
            f"This binding does not convert: the conversion is an O(n) copy, and it "
            f"would land inside a call whose entire premise is a sub-millisecond "
            f"win. Allocate the array once outside your loop "
            f"(np.empty(n, dtype=np.{dtype})) and fill it in place."
        )
    if a.dtype != dtype:
        raise HSTBufferError(
            f"{name} must have dtype {dtype}, got {a.dtype}. Converting here would "
            f"copy the whole array on every call; do it once, outside the loop."
        )
    if not a.flags.c_contiguous:
        raise HSTBufferError(
            f"{name} must be C-contiguous, got {_describe(a)}. A strided slice or a "
            f"transpose cannot be handed to C as a flat buffer; np.ascontiguousarray "
            f"would copy it on every call. Fix the layout outside the loop."
        )
    if writeable and not a.flags.writeable:
        raise HSTBufferError(f"{name} must be writeable; the library writes its output there.")
    return a


def _flat_len(a: np.ndarray, expected: int, name: str, shape_hint: str) -> None:
    if a.ndim not in (1, 2):
        raise HSTArgumentError(f"{name} must be 1-D or 2-D ({shape_hint}), got {a.ndim} dimensions.")
    if a.size != expected:
        raise HSTArgumentError(
            f"{name} must hold {expected} values ({shape_hint}), got {a.size} "
            f"with shape {a.shape}."
        )


def _f64p(a: np.ndarray) -> Any:
    return a.ctypes.data_as(ctypes.POINTER(ctypes.c_double))


def _i32p(a: np.ndarray) -> Any:
    return a.ctypes.data_as(ctypes.POINTER(ctypes.c_int32))


class HSTContext:
    """One open session over one compiled operator artifact.

    ::

        import numpy as np, hstcore

        with hstcore.HSTContext("op.bin", token) as ctx:
            cols = np.empty(32, dtype=np.int32)      # allocated once
            vals = np.empty(32, dtype=np.float64)
            for step in stream:
                cols[:] = step.cols                  # filled in place
                vals[:] = step.vals
                ctx.apply(cols, vals)                # nothing is copied
                y = ctx.state                        # zero-copy, expires next apply

    The handle is **not thread-safe**: one context per thread or per stream, as
    ``hstcore.h`` requires. Nothing here adds a lock, because a lock in this
    path would cost more than the work it protects.

    :param artifact: path to the compiled operator (``op.bin``).
    :param token: the signed license token.
    :param batch: right-hand-side lanes, 1..32. ``batch=1`` opens through
        ``hst_open``; anything larger goes through ``hst_open_batched``. All
        buffers are then lane-interleaved — ``vals[i, b]``, ``state[i, b]``.
    :param lib_path: where to find ``libhstcore``. Process-wide: the first
        context to load a library decides for all of them.
    """

    __slots__ = ("_api", "_h", "_n", "_m", "_batch", "_epoch", "_mode", "__weakref__")

    def __init__(
        self,
        artifact: Any,
        token: str,
        *,
        batch: int = 1,
        lib_path: Optional[str] = None,
    ) -> None:
        self._h: Optional[ctypes.c_void_p] = None
        self._epoch = 0
        self._mode: Optional[str] = None

        if isinstance(batch, bool) or not isinstance(batch, (int, np.integer)):
            raise HSTArgumentError(f"batch must be an int, got {type(batch).__name__}.")
        batch = int(batch)
        if not 1 <= batch <= _MAX_BATCH:
            raise HSTArgumentError(f"batch must be in 1..{_MAX_BATCH}, got {batch}.")
        if not isinstance(token, (str, bytes)):
            raise HSTArgumentError(f"token must be a str, got {type(token).__name__}.")

        api = load_library(lib_path)
        self._api = api

        artifact_b = os.fsencode(artifact)
        token_b = token.encode() if isinstance(token, str) else token
        err = ctypes.create_string_buffer(_ERRBUF)

        if batch == 1:
            handle = api.hst_open(artifact_b, token_b, err, _ERRBUF)
        else:
            handle = api.hst_open_batched(artifact_b, token_b, batch, err, _ERRBUF)

        if not handle:
            reason = err.value.decode("utf-8", "replace").strip()
            raise HSTLicenseError(
                reason
                or "hst_open returned NULL and wrote no reason (invalid or expired "
                "license, operator larger than the license permits, exhausted file "
                "quota, or an unreadable artifact)."
            )

        self._h = ctypes.c_void_p(handle)
        self._batch = int(api.hst_batch(self._h))
        self._n = int(api.hst_output_dim(self._h))
        self._m = int(api.hst_input_dim(self._h))

        if self._batch != batch:
            got = self._batch
            self.close()
            raise HSTInternalError(
                f"asked for {batch} lanes, the library reports {got}. Every buffer "
                f"size in this binding is derived from that number, so it is not "
                f"safe to continue."
            )
        if self._n <= 0 or self._m <= 0:
            n, m = self._n, self._m
            self.close()
            raise HSTInternalError(f"library reports a degenerate operator: N={n}, M={m}.")

    # -- properties ---------------------------------------------------------

    @property
    def batch(self) -> int:
        """Right-hand-side lanes on this handle (1 for a plain open)."""
        return self._batch

    @property
    def output_dim(self) -> int:
        """N — rows of the operator. The state holds ``N * batch`` doubles."""
        return self._n

    @property
    def input_dim(self) -> int:
        """M — columns of the operator. Delta column indices live in 0..M-1."""
        return self._m

    @property
    def closed(self) -> bool:
        return self._h is None

    @property
    def mode(self) -> Optional[str]:
        """``'production'``, ``'shadow'``, or ``None`` before the first apply."""
        return self._mode

    @property
    def state_size(self) -> int:
        """``output_dim * batch`` — the length of every state-shaped buffer."""
        return self._n * self._batch

    @property
    def input_size(self) -> int:
        """``input_dim * batch`` — the length of an input-shaped buffer.

        Distinct from :attr:`state_size` whenever the operator is not square,
        which is why :meth:`set_input` cannot reuse the state length.
        """
        return self._m * self._batch

    # -- internals ----------------------------------------------------------

    def _live(self) -> ctypes.c_void_p:
        if self._h is None:
            raise HSTClosedError("context is closed; open a new one.")
        return self._h

    def _claim(self, mode: str) -> None:
        if self._mode is None:
            self._mode = mode
            return
        if self._mode != mode:
            raise HSTModeError(
                f"this context has already served a {self._mode} apply; refusing a "
                f"{mode} apply on the same handle. hstcore.h: shadow and production "
                f"applies share the held input and output buffers and must never be "
                f"interleaved. Open a second context for shadow-mode validation."
            )

    def _delta_args(self, cols: Any, vals: Any, out: Any) -> tuple[Any, Any, int, Any]:
        cols_a = _check_array(cols, _I32, "cols")
        if cols_a.ndim != 1:
            raise HSTArgumentError(f"cols must be 1-D, got shape {cols_a.shape}.")
        n = int(cols_a.size)
        if n > _INT32_MAX:
            raise HSTArgumentError(f"cols holds {n} entries; the ABI takes an int32 count.")

        vals_a = _check_array(vals, _F64, "vals")
        _flat_len(vals_a, n * self._batch, "vals", f"n * batch = {n} * {self._batch}")

        if out is None:
            out_p = None
        else:
            out_a = _check_array(out, _F64, "out", writeable=True)
            _flat_len(
                out_a,
                self.state_size,
                "out",
                f"output_dim * batch = {self._n} * {self._batch}",
            )
            out_p = _f64p(out_a)
        return _i32p(cols_a), _f64p(vals_a), n, out_p

    def _apply_through(self, entry: str, mode: str, cols: Any, vals: Any, out: Any) -> Any:
        handle = self._live()
        self._claim(mode)
        cols_p, vals_p, n, out_p = self._delta_args(cols, vals, out)
        fn = getattr(self._api, entry)
        rc = int(fn(handle, cols_p, vals_p, n, out_p))
        # The held state may have moved whether or not the call reported success,
        # so every outstanding view expires either way.
        self._epoch += 1
        _raise_for(rc, entry)
        return out

    # -- the hot path -------------------------------------------------------

    def apply(self, cols: Any, vals: Any, *, out: Optional[np.ndarray] = None) -> Any:
        """Apply a sparse delta to the held state. Metered.

        ``cols`` must be ``int32``, 1-D, C-contiguous. ``vals`` must be
        ``float64``, C-contiguous, holding ``len(cols) * batch`` values —
        shape ``(n,)`` when ``batch == 1``, or ``(n, batch)`` lane-interleaved.
        Both are passed straight to C as pointers; **no copy is made, and
        nothing that would need one is accepted**.

        With ``out=None`` the dense output stays inside the library and is read
        back through :attr:`state` — this is the true hot-loop cost, with no
        marshalling at all. Pass ``out`` (a ``float64`` C-contiguous array of
        ``output_dim * batch``) to have the library also write the dense output
        into a buffer you own.

        Raises :class:`~hstcore.HSTQuotaError` when the license's apply budget
        is spent, and :class:`~hstcore.HSTModeError` if this context has already
        served a shadow apply.
        """
        return self._apply_through("hst_apply_delta", _PRODUCTION, cols, vals, out)

    def apply_shadow(self, cols: Any, vals: Any, *, out: Optional[np.ndarray] = None) -> Any:
        """Apply a delta metered against the shadow budget. Same numerics.

        For validating the engine against your own reference in production
        traffic without spending production applies. The shadow budget comes
        from the signed token and nothing else; a token without one raises
        :class:`~hstcore.HSTShadowNotGrantedError` on every call.

        A context is production **or** shadow, never both: the first apply of
        either kind fixes the choice, and the other kind then raises
        :class:`~hstcore.HSTModeError`. That is ``hstcore.h``'s "never
        interleave" warning made unignorable.
        """
        return self._apply_through("hst_apply_shadow", _SHADOW, cols, vals, out)

    # -- state --------------------------------------------------------------

    @property
    def state(self) -> StateView:
        """Zero-copy read-only view of the dense output state.

        Shape ``(output_dim,)`` when ``batch == 1``, else ``(output_dim, batch)``
        lane-interleaved. Read-only (``WRITEABLE`` is cleared) and stamped with
        the context's epoch: the next :meth:`apply`, :meth:`apply_shadow`,
        :meth:`set_state` or :meth:`close` expires it, and reading through it
        afterwards raises instead of returning whatever now lives at that
        address. Call ``.copy()`` if you need the numbers to outlive the call.
        """
        handle = self._live()
        ptr = self._api.hst_state(handle)
        if not ptr:
            raise HSTInternalError("hst_state returned NULL.")
        flat = np.ctypeslib.as_array(ptr, shape=(self.state_size,))
        shaped = flat if self._batch == 1 else flat.reshape(self._n, self._batch)
        shaped.flags.writeable = False
        return StateView(shaped, self, self._epoch)

    def set_state(self, y0: Any) -> None:
        """Prime the held dense output state. Expires outstanding state views.

        ``y0`` must be ``float64``, C-contiguous, ``output_dim * batch`` values.
        """
        handle = self._live()
        y0_a = _check_array(y0, _F64, "y0")
        _flat_len(
            y0_a, self.state_size, "y0", f"output_dim * batch = {self._n} * {self._batch}"
        )
        rc = int(self._api.hst_set_state(handle, _f64p(y0_a), self.state_size))
        self._epoch += 1
        _raise_for(rc, "hst_set_state")

    def set_input(self, x0: Any) -> None:
        """Prime the held dense **input** state x.

        ``x0`` must be ``float64``, C-contiguous, ``input_dim * batch`` values.

        **Call this together with :meth:`set_state`, using the same baseline.**
        The two buffers are separate: ``set_state`` primes only the output y,
        while this primes the input x that :meth:`recompute_full` computes
        ``A*x`` from. Priming one without the other leaves them inconsistent,
        and ``recompute_full`` then refuses with -5 rather than return a vector
        that disagrees with y by exactly ``A*x0`` forever.

        Leaving both pristine is also consistent, and is the right choice if you
        have no baseline to prime with.
        """
        handle = self._live()
        x0_a = _check_array(x0, _F64, "x0")
        _flat_len(
            x0_a, self.input_size, "x0",
            f"input_dim * batch = {self._m} * {self._batch}",
        )
        rc = int(self._api.hst_set_input(handle, _f64p(x0_a), self.input_size))
        self._epoch += 1
        _raise_for(rc, "hst_set_input")

    def recompute_full(self, out: Optional[np.ndarray] = None) -> np.ndarray:
        """Recompute the whole dense output from scratch. **Not metered.**

        This is the reference arm — the "before" in a before/after comparison,
        and the thing to assert the delta path against. It does not spend
        applies and it does not disturb the held state, so an outstanding
        :attr:`state` view stays valid across it.

        Returns ``out`` if given, otherwise a freshly allocated array of
        ``output_dim * batch`` — pass ``out`` to keep the loop allocation-free.
        """
        handle = self._live()
        if out is None:
            out = np.empty(
                self._n if self._batch == 1 else (self._n, self._batch), dtype=_F64
            )
        out_a = _check_array(out, _F64, "out", writeable=True)
        _flat_len(
            out_a, self.state_size, "out", f"output_dim * batch = {self._n} * {self._batch}"
        )
        rc = int(self._api.hst_recompute_full(handle, _f64p(out_a)))
        _raise_for(rc, "hst_recompute_full")
        return out

    # -- lifetime -----------------------------------------------------------

    def close(self) -> None:
        """Release the handle. Idempotent. Expires outstanding state views."""
        handle = self._h
        self._h = None
        self._epoch += 1
        if handle is not None:
            self._api.hst_close(handle)

    def __enter__(self) -> "HSTContext":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:  # interpreter teardown; nothing useful to do here
            pass

    def __repr__(self) -> str:
        if self._h is None:
            return "<HSTContext closed>"
        return (
            f"<HSTContext N={self._n} M={self._m} batch={self._batch} "
            f"mode={self._mode or 'unused'}>"
        )
