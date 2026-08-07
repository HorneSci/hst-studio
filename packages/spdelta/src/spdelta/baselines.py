"""The rung ladder: four ways to answer the same question, in cost order.

Why a ladder rather than a baseline
-----------------------------------
"We got 25x" and "we got 3x" are routinely the *same measurement* reported
against different comparands, and the two cannot be chained. The only way to
stop that is to run every rung in one harness, in one window, on one operator,
and print the whole column. Measured that way on one operator, the four rungs
here spanned roughly two orders of magnitude between the top and the bottom, and
the interesting part was in the middle.

The rungs, and who in the wild is standing on each:

``full_matvec``
    Recompute ``Y = A @ X`` from scratch every step. This is what almost
    everybody does, including every stock sparse matvec call.

``masked_row_scan``
    Walk every row; multiply only the entries whose column is dirty. This is the
    engineer who knew about deltas and had row-major storage. It is the rung
    that matters commercially, because it *looks* like a delta method and is
    not: it skips the work but not the scan, so its cost stays O(nnz) and its
    advantage stays flat at roughly 2.3x across an entire churn range. When
    somebody says "we already do a delta", the follow-up question is not whether
    they skip work. It is whether they skip the **scan**.

``column_delta_csc``
    Touch only the dirty columns' entries, via a column-major slice compiled for
    the current dirty set. This is a competent implementation and it is the
    baseline any real claim should be stated against. Its weakness is visible
    here too: when the dirty set changes it has to recompile, and this class
    counts how often that happened.

``scratch_reference``
    Recompute from scratch by an independent code path. Not a rung -- an oracle.
    It exists so a harness can assert every other arm against it, every repeat.

Why the reference is not in :func:`ladder`
------------------------------------------
Three real defects in one probe were invisible to timings because every arm did
the right *amount* of work with the wrong values -- a stale buffer, a
wrong-encoding read, and a control that was not frozen. All three surfaced only
because something recomputed from scratch and disagreed. An oracle that is also
a timed arm can end up asserted against itself and pass vacuously, so
:class:`ScratchReference` shares no code with :class:`FullMatvec` (it uses
explicit triplet accumulation, not the library matmul) and is kept out of the
list of things being compared.

Preparation is a real cost and is not hidden
--------------------------------------------
Every arm's ``prepare`` does its own setup and nothing else's.
:func:`spdelta.harness.sweep` times it separately and reports it, because
preparation charged to one arm and not another has been the actual explanation
for a "kernel" difference more than once.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import numpy as np
import scipy.sparse as sp
from numpy.typing import NDArray

from .delta import Delta, require_compact, require_global

__all__ = [
    "Arm",
    "FullMatvec",
    "MaskedRowScan",
    "ColumnDeltaCsc",
    "ScratchReference",
    "ladder",
    "reference",
    "rel_l2",
]


def rel_l2(got: NDArray[np.float64], want: NDArray[np.float64]) -> float:
    """Relative L2 distance, with a zero-reference case that does not lie.

    When the reference is exactly zero any non-zero result is infinitely wrong,
    and returning 0.0 there -- which a naive guard does -- turns the one case
    where an arm produced pure garbage into a clean pass.
    """
    got = np.asarray(got, dtype=np.float64)
    want = np.asarray(want, dtype=np.float64)
    if got.shape != want.shape:
        raise ValueError(f"shape mismatch: {got.shape} vs {want.shape}")
    denominator = float(np.linalg.norm(want))
    numerator = float(np.linalg.norm(got - want))
    if denominator == 0.0:
        return 0.0 if numerator == 0.0 else float("inf")
    return numerator / denominator


@runtime_checkable
class Arm(Protocol):
    """One way of computing the updated product.

    ``delta_kind`` is part of the protocol because the two delta encodings are
    not interchangeable and the caller has to know which to build. See
    :mod:`spdelta.delta`.
    """

    #: Stable identifier, recorded on every result row.
    name: str
    #: ``"compact"`` or ``"global"``.
    delta_kind: str

    def prepare(self, a: sp.spmatrix, dirty: NDArray[np.int32]) -> None:
        """Set up for this operator and initial dirty set. Fully resets state."""
        ...

    def step(self, d: Delta, y: NDArray[np.float64]) -> None:
        """Update ``y`` in place to the product after applying ``d``."""
        ...


class _ArmBase:
    """Shared plumbing: shapes, lazily sized state, and per-run counters.

    ``batch`` is discovered from the first delta rather than declared in
    ``prepare``, so the workload's width is a property of the data and cannot
    disagree with it.
    """

    name = "arm"
    delta_kind = "compact"
    #: True if this arm must carry the state vector to do its job.
    carries_state = False

    def __init__(self) -> None:
        self.n_rows = 0
        self.n_cols = 0
        self.steps = 0
        self.recompiles = 0
        self._batch: int | None = None

    def prepare(self, a: sp.spmatrix, dirty: NDArray[np.int32]) -> None:
        raise NotImplementedError

    def _begin(self, a: sp.spmatrix) -> None:
        self.n_rows, self.n_cols = int(a.shape[0]), int(a.shape[1])
        self.steps = 0
        self.recompiles = 0
        self._batch = None

    def _check_y(self, y: NDArray[np.float64], batch: int) -> None:
        if y.dtype != np.float64:
            raise TypeError(f"y must be float64, got {y.dtype}")
        if y.shape != (self.n_rows, batch):
            raise ValueError(
                f"y has shape {y.shape}, expected {(self.n_rows, batch)}"
            )

    def _first_step(self, d: Delta, y: NDArray[np.float64]) -> int:
        batch = d.batch
        if self._batch is None:
            self._batch = batch
        elif batch != self._batch:
            raise ValueError(
                f"batch changed mid-run: {self._batch} -> {batch}. That makes "
                "the timings of the two halves incomparable"
            )
        self._check_y(y, batch)
        self.steps += 1
        return batch

    def stats(self) -> dict[str, object]:
        """Per-run counters for the result row."""
        return {"steps": self.steps, "recompiles": self.recompiles}


class FullMatvec(_ArmBase):
    """Rung 0: recompute ``Y = A @ X`` from scratch, every step.

    Carries the state vector, because recomputing needs it. That is an inherent
    O(|D| * batch) scatter this arm pays and the delta arms do not -- it is
    named here rather than equalised away, since padding the other arms with
    work they do not need would be a different kind of dishonesty.
    """

    name = "full_matvec"
    delta_kind = "compact"
    carries_state = True

    def prepare(self, a: sp.spmatrix, dirty: NDArray[np.int32]) -> None:
        self._begin(a)
        self._a = sp.csr_matrix(a)
        self._x: NDArray[np.float64] | None = None

    def step(self, d: Delta, y: NDArray[np.float64]) -> None:
        delta = require_compact(d)
        batch = self._first_step(delta, y)
        if self._x is None:
            self._x = np.zeros((self.n_cols, batch), dtype=np.float64)
        self._x[delta.cols] += delta.vals
        y[:] = self._a @ self._x


class MaskedRowScan(_ArmBase):
    """Rung 1: scan every nonzero, multiply only the dirty ones.

    Consumes a :class:`~spdelta.delta.GlobalDelta` because that is structurally
    what this shape of code can consume: it discovers a column id by reading the
    operator's own index array and has no position within the dirty set to look
    anything up by. The encoding is not an implementation detail here, it
    follows from the traversal order.

    Note where the cost is. ``mask[indices]`` is a gather over **every**
    nonzero -- that is the scan, and it is what keeps this arm at O(nnz) no
    matter how small the dirty set gets.
    """

    name = "masked_row_scan"
    delta_kind = "global"

    def prepare(self, a: sp.spmatrix, dirty: NDArray[np.int32]) -> None:
        self._begin(a)
        csr = sp.csr_matrix(a)
        self._data = csr.data
        self._indices = csr.indices
        # Row id of every nonzero, precomputed once: this is structure, not a
        # per-step cost, and building it inside the loop would charge this arm
        # for something a real row-major implementation gets from its layout.
        self._row_of_nnz = np.repeat(
            np.arange(self.n_rows, dtype=np.int32), np.diff(csr.indptr)
        )
        self._mask = np.zeros(self.n_cols, dtype=bool)
        self._marked: NDArray[np.int32] = np.empty(0, dtype=np.int32)

    def step(self, d: Delta, y: NDArray[np.float64]) -> None:
        delta = require_global(d)
        batch = self._first_step(delta, y)
        # Clear only what was marked last step. Clearing the whole mask would be
        # an O(M) cost this arm does not actually have.
        self._mask[self._marked] = False
        self._mask[delta.cols] = True
        self._marked = delta.cols
        hit = np.flatnonzero(self._mask[self._indices])  # the scan
        rows = self._row_of_nnz[hit]
        coefficients = self._data[hit]
        columns = self._indices[hit]
        for b in range(batch):
            y[:, b] += np.bincount(
                rows,
                weights=coefficients * delta.buf[columns, b],
                minlength=self.n_rows,
            )


class ColumnDeltaCsc(_ArmBase):
    """Rung 2: touch only the dirty columns' entries.

    Column-major storage plus a slice compiled for the current dirty set, so the
    per-step cost is O(nnz over D), not O(nnz). Consumes a
    :class:`~spdelta.delta.CompactDelta`: the compiled slice has shape
    ``(rows, |D|)``, so its operand is indexed by position within ``D`` and a
    global buffer would be read as the wrong ``|D| * batch`` values with no
    shape error to catch it whenever ``M`` happens to be large enough.

    When the dirty set changes, the slice is rebuilt. :attr:`recompiles` counts
    that. This is the arm's real weakness and the reason its measured advantage
    falls away as churn rises -- reporting the count is what turns "it got
    slower" into "it recompiled on 19% of steps".
    """

    name = "column_delta_csc"
    delta_kind = "compact"

    def prepare(self, a: sp.spmatrix, dirty: NDArray[np.int32]) -> None:
        self._begin(a)
        self._csc = sp.csc_matrix(a)
        self._per_col = np.diff(self._csc.indptr).astype(np.int64)
        self._cols: NDArray[np.int32] | None = None
        self._slice: sp.csc_matrix | None = None
        self.n_entries_touched = 0
        self._recompile(np.asarray(dirty, dtype=np.int32))
        # The compile done inside prepare belongs to preparation, not to the
        # timed loop, so it is not counted as a churn-driven recompile.
        self.recompiles = 0

    def _recompile(self, cols: NDArray[np.int32]) -> None:
        self._cols = np.array(cols, dtype=np.int32, copy=True)
        self._slice = self._csc[:, self._cols]
        self.recompiles += 1

    def step(self, d: Delta, y: NDArray[np.float64]) -> None:
        delta = require_compact(d)
        self._first_step(delta, y)
        assert self._cols is not None
        if self._cols.size != delta.cols.size or not np.array_equal(
            self._cols, delta.cols
        ):
            self._recompile(delta.cols)
        assert self._slice is not None
        self.n_entries_touched += int(self._per_col[delta.cols.astype(np.int64)].sum())
        y += self._slice @ delta.vals

    def stats(self) -> dict[str, object]:
        base = super().stats()
        base["entries_touched"] = self.n_entries_touched
        return base


class ScratchReference(_ArmBase):
    """The oracle: recompute from scratch by a path no timed arm shares.

    Triplet accumulation rather than the library's matmul. Sharing the matmul
    with :class:`FullMatvec` would mean a bug in that path cancels itself
    between arm and oracle, which is exactly the class of failure an oracle is
    for. Slow on purpose; it runs once per repeat, untimed.
    """

    name = "scratch_reference"
    delta_kind = "compact"
    carries_state = True

    def prepare(self, a: sp.spmatrix, dirty: NDArray[np.int32]) -> None:
        self._begin(a)
        coo = sp.coo_matrix(a)
        self._rows = coo.row.astype(np.int64)
        self._colidx = coo.col.astype(np.int64)
        self._values = coo.data.astype(np.float64)
        self._x: NDArray[np.float64] | None = None

    def step(self, d: Delta, y: NDArray[np.float64]) -> None:
        delta = require_compact(d)
        batch = self._first_step(delta, y)
        if self._x is None:
            self._x = np.zeros((self.n_cols, batch), dtype=np.float64)
        self._x[delta.cols] += delta.vals
        for b in range(batch):
            y[:, b] = np.bincount(
                self._rows,
                weights=self._values * self._x[self._colidx, b],
                minlength=self.n_rows,
            )


def ladder() -> list[Arm]:
    """The timed rungs, cheapest implementation effort first.

    :class:`ScratchReference` is deliberately absent -- see the module
    docstring. Get it from :func:`reference`.
    """
    return [FullMatvec(), MaskedRowScan(), ColumnDeltaCsc()]


def reference() -> ScratchReference:
    """A fresh oracle arm."""
    return ScratchReference()
