"""Two delta representations, and a type error where a silent bug used to be.

The bug class this module deletes
---------------------------------
A sparse update to a state vector has two natural encodings, and they are the
same size, the same dtype, and equally contiguous:

* **compact** -- ``vals[i]`` is the update to column ``cols[i]``. Indexed by
  *position within the dirty set*. Size ``|D| x batch``.
* **global** -- ``buf[j]`` is the update to column ``j``, zero where ``j`` is
  not dirty. Indexed by *column*. Size ``M x batch``.

Kernels want one or the other and almost never say which. Two failures from the
project this package was extracted from, both found only because a harness had a
non-accumulating reference arm to check against:

1. A global buffer was handed to a compact-indexed kernel. It read
   ``buf[0 : |D|*batch)`` -- the wrong values, from a region *the same size and
   just as contiguous* as the correct one. Every timing looked normal. The
   answer was wrong by a relative L2 error in the 1e-2 range.
2. A global buffer was reused across steps and never re-zeroed, so columns that
   were dirty last step but not this step still carried last step's values.
   A comparable relative L2 error, and again no timing anomaly at all.

Neither is detectable from timings, because in both cases every arm did the
right *amount* of work. So the fix is not a better benchmark, it is a type:
:class:`CompactDelta` and :class:`GlobalDelta` are distinct, neither is
implicitly convertible, and a kernel declares which it consumes. Passing the
wrong one raises :class:`TypeError` before any arithmetic happens.

Failure 2 gets a second guard: the only supported way to reuse a global buffer
is :class:`GlobalScatter`, which zeroes the columns it wrote last time before
writing the new ones. That is O(|D|) per step, not O(M), so the safe path is
also the fast one and there is no incentive to hand-roll the unsafe one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Union

import numpy as np
from numpy.typing import NDArray

__all__ = [
    "CompactDelta",
    "GlobalDelta",
    "GlobalScatter",
    "Delta",
    "require_compact",
    "require_global",
]


def _check_cols(cols: NDArray[np.int32]) -> NDArray[np.int32]:
    """Validate and normalise a dirty column index array.

    Duplicates are rejected rather than summed. A duplicated column means the
    caller's motion model is producing a dirty set that is not a set, and the
    two encodings disagree about what that means: compact would apply both
    entries, global would keep only the last write. Silently picking either
    behaviour makes the encodings non-equivalent, which is the one property
    everything else here rests on.
    """
    arr = np.asarray(cols)
    if arr.ndim != 1:
        raise ValueError(f"cols must be 1-D, got shape {arr.shape}")
    if not np.issubdtype(arr.dtype, np.integer):
        raise TypeError(f"cols must be an integer array, got dtype {arr.dtype}")
    arr = arr.astype(np.int32, copy=False)
    if arr.size and arr.min() < 0:
        raise ValueError("cols must be non-negative")
    if np.unique(arr).size != arr.size:
        raise ValueError(
            "cols contains duplicates; a dirty set must be a set, or the "
            "compact and global encodings stop agreeing"
        )
    return arr


def _check_vals(vals: NDArray[np.float64], n: int, what: str) -> NDArray[np.float64]:
    """Validate a value block of shape ``(n, batch)``.

    float64 is required rather than up-cast. Silently promoting a float32 array
    hides a precision mismatch between two arms of a comparison, and a
    correctness assertion tuned for exact arithmetic then fails for a reason
    that has nothing to do with the kernel under test.
    """
    arr = np.asarray(vals)
    if arr.dtype != np.float64:
        raise TypeError(
            f"{what} must be float64, got dtype {arr.dtype}; pass "
            "np.asarray(x, dtype=np.float64) explicitly if that is what you meant"
        )
    if arr.ndim != 2:
        raise ValueError(
            f"{what} must be 2-D (rows, batch); got shape {arr.shape}. "
            "A 1-D update is batch=1 and must say so: vals[:, None]"
        )
    if arr.shape[0] != n:
        raise ValueError(f"{what} has {arr.shape[0]} rows, expected {n}")
    if arr.shape[1] < 1:
        raise ValueError(f"{what} must have batch >= 1, got {arr.shape[1]}")
    return arr


@dataclass(frozen=True)
class CompactDelta:
    """A sparse update indexed by *position in* :attr:`cols`.

    ``vals[i, b]`` is the change to column ``cols[i]`` in right-hand side ``b``.

    This is the encoding a column-sliced kernel wants: it has already gathered
    the dirty columns' entries into a dense ``(rows, |D|)`` block, so its second
    operand must be ``(|D|, batch)`` and nothing else lines up.
    """

    cols: NDArray[np.int32]
    vals: NDArray[np.float64]

    def __post_init__(self) -> None:
        cols = _check_cols(self.cols)
        vals = _check_vals(self.vals, cols.size, "vals")
        object.__setattr__(self, "cols", cols)
        object.__setattr__(self, "vals", vals)

    @property
    def n_dirty(self) -> int:
        return int(self.cols.size)

    @property
    def batch(self) -> int:
        return int(self.vals.shape[1])

    def to_global(self, m: int) -> GlobalDelta:
        """Scatter into a freshly allocated, therefore trivially clean, buffer.

        Allocating is the safe default. Reusing a buffer is faster and is what
        :class:`GlobalScatter` is for, but reuse is where failure 2 lives, so it
        has to be asked for by name.
        """
        if m <= 0:
            raise ValueError(f"m must be positive, got {m}")
        if self.n_dirty and int(self.cols.max()) >= m:
            raise ValueError(
                f"column {int(self.cols.max())} is out of range for m={m}"
            )
        buf = np.zeros((m, self.batch), dtype=np.float64)
        buf[self.cols] = self.vals
        return GlobalDelta(buf, self.cols)

    def copy(self) -> CompactDelta:
        """A deep copy, so two arms never share an input array."""
        return CompactDelta(self.cols.copy(), self.vals.copy())


@dataclass(frozen=True)
class GlobalDelta:
    """A sparse update indexed by *column*, dense over all ``M`` columns.

    ``buf[j, b]`` is the change to column ``j``; entries outside :attr:`cols`
    must be zero. This is the encoding a kernel wants when it discovers which
    columns it touched by walking the operator's own index array -- it looks up
    by global column id and has nowhere to get a position from.

    The zero-outside-``cols`` invariant is not checked on construction, because
    the check is O(M) and this object is built once per step. Use
    :meth:`check_clean` in tests and in any harness that suspects it, and build
    reused buffers through :class:`GlobalScatter`, which maintains the invariant
    by construction.
    """

    buf: NDArray[np.float64]
    cols: NDArray[np.int32]

    def __post_init__(self) -> None:
        cols = _check_cols(self.cols)
        buf = np.asarray(self.buf)
        if buf.dtype != np.float64:
            raise TypeError(f"buf must be float64, got dtype {buf.dtype}")
        if buf.ndim != 2:
            raise ValueError(f"buf must be 2-D (m, batch); got shape {buf.shape}")
        if cols.size and int(cols.max()) >= buf.shape[0]:
            raise ValueError(
                f"column {int(cols.max())} is out of range for buf of "
                f"{buf.shape[0]} rows"
            )
        object.__setattr__(self, "buf", buf)
        object.__setattr__(self, "cols", cols)

    @property
    def m(self) -> int:
        return int(self.buf.shape[0])

    @property
    def n_dirty(self) -> int:
        return int(self.cols.size)

    @property
    def batch(self) -> int:
        return int(self.buf.shape[1])

    def check_clean(self) -> None:
        """Raise unless every non-dirty column is exactly zero.

        Exactly zero, not near zero: a stale value from a previous step is a
        full-magnitude number, so there is no tolerance worth having and an
        approximate check would only hide the case where the leftover happens
        to be small.
        """
        mask = np.ones(self.m, dtype=bool)
        mask[self.cols] = False
        stale = np.flatnonzero(np.any(self.buf[mask] != 0.0, axis=1))
        if stale.size:
            live = np.flatnonzero(mask)[stale]
            raise ValueError(
                f"{live.size} non-dirty column(s) are non-zero, first is "
                f"{int(live[0])}: the buffer was not re-zeroed between steps, "
                "so this step's result carries the previous step's update"
            )

    def to_compact(self) -> CompactDelta:
        """Gather back to compact form, copying so the two do not alias."""
        return CompactDelta(self.cols.copy(), self.buf[self.cols].copy())

    def copy(self) -> GlobalDelta:
        """A deep copy, so two arms never share an input array."""
        return GlobalDelta(self.buf.copy(), self.cols.copy())


#: Either encoding. Use this only where genuinely either will do -- which, at a
#: kernel boundary, is never.
Delta = Union[CompactDelta, GlobalDelta]


class GlobalScatter:
    """A reusable global buffer that re-zeroes what it wrote last time.

    The allocation-free path, made safe. :meth:`scatter` clears exactly the
    columns written by the previous call and then writes the new ones, so the
    zero-outside-``cols`` invariant holds every step at O(|D|) cost rather than
    O(M). Reusing a raw ``np.ndarray`` instead is how the second error above
    happened, and there is no performance argument for doing so.

    ``verify=True`` adds an O(M) check after every scatter. Off by default
    because it is asymptotically the thing being avoided; on in the tests, and
    worth turning on the first time a new arm disagrees with the reference.
    """

    def __init__(self, m: int, batch: int, *, verify: bool = False) -> None:
        if m <= 0:
            raise ValueError(f"m must be positive, got {m}")
        if batch < 1:
            raise ValueError(f"batch must be >= 1, got {batch}")
        self.m = int(m)
        self.batch = int(batch)
        self.verify = bool(verify)
        self._buf: NDArray[np.float64] = np.zeros((self.m, self.batch), dtype=np.float64)
        self._written: NDArray[np.int32] = np.empty(0, dtype=np.int32)
        self.scatters = 0

    def scatter(self, delta: CompactDelta) -> GlobalDelta:
        """Re-zero, write, and return a view-backed :class:`GlobalDelta`.

        The returned object shares the buffer, so it is valid only until the
        next :meth:`scatter`. That is the point of the class -- but it means a
        caller who wants to keep one must ``.copy()`` it, and a caller who wants
        two arms to hold deltas simultaneously needs two scatters.
        """
        delta = require_compact(delta)
        if delta.batch != self.batch:
            raise ValueError(
                f"delta batch {delta.batch} does not match scatter batch {self.batch}"
            )
        if delta.n_dirty and int(delta.cols.max()) >= self.m:
            raise ValueError(
                f"column {int(delta.cols.max())} is out of range for m={self.m}"
            )
        self._buf[self._written] = 0.0
        self._buf[delta.cols] = delta.vals
        self._written = delta.cols
        self.scatters += 1
        out = GlobalDelta(self._buf, delta.cols)
        if self.verify:
            out.check_clean()
        return out


_WRONG_WAY = (
    "The two encodings are the same dtype and a similar size, so passing the "
    "wrong one produces plausible timings and a wrong answer rather than a "
    "crash. Convert explicitly: CompactDelta.to_global(m) / "
    "GlobalDelta.to_compact()."
)


def require_compact(delta: object) -> CompactDelta:
    """Assert compact encoding at a kernel boundary."""
    if not isinstance(delta, CompactDelta):
        raise TypeError(
            f"this kernel is indexed by position within the dirty set and "
            f"needs a CompactDelta, got {type(delta).__name__}. {_WRONG_WAY}"
        )
    return delta


def require_global(delta: object) -> GlobalDelta:
    """Assert global encoding at a kernel boundary."""
    if not isinstance(delta, GlobalDelta):
        raise TypeError(
            f"this kernel is indexed by column and needs a GlobalDelta, got "
            f"{type(delta).__name__}. {_WRONG_WAY}"
        )
    return delta
