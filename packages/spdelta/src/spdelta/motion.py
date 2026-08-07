"""How the dirty column set moves between steps.

A delta-updated matvec is not one workload, it is a family indexed by *how the
dirty set moves*. The same operator and the same ``|D|`` give completely
different answers under a set that never changes, one that walks along the
operator's connectivity, and one that teleports. So the motion model is a
first-class object here, it carries a mandatory :attr:`name`, and that name is
recorded on every result row.

Two lessons from the project this was extracted from are built into the API
rather than written in a comment.

**Frozen is a distinct object, not a churn rate of zero.**
A generator that computed its swap count as ``max(1, round(rho * |D|))`` swapped
one column per step at ``rho = 0``. The "frozen control" was therefore not
frozen: it recompiled on 19% of steps, and the control cell reported the fast
arm 1.69x ahead in the one regime where that arm is documented to lose. A
control that is not the control is worse than no control. Here, :func:`frozen`
returns a :class:`FrozenMotion`, which has no swap code path to reach, and the
churning motions refuse ``rho <= 0`` outright -- so ``rho = 0`` cannot be
expressed as drift or jump even by accident.

**"Jump" does not identify a generator.**
The obvious teleport -- retire a column, draw its replacement uniformly -- does
two things at once. It destroys locality, which is intended, and it also drags
the dirty set toward the operator's *average* column density, which is not. On
one measured pair of sweeps the initial dirty set's nonzero count fell 13.7%
over a run under uniform jump and 0.0% under an nnz-matched draw, and the
measured ratios differed by 1.41x to 1.82x on identical operators, seeds and
rates -- with the gap widening as the churn rate rose. Most of the apparent
"locality decays with churn rate" effect was the slice shrinking. So
:func:`jump_plain` and :func:`jump_nnz_matched` are separate names, neither is
called just "jump", and :func:`slice_weight` / :func:`slice_drift` exist so any
sweep can show which of the two effects it is looking at.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import numpy as np
import scipy.sparse as sp
from numpy.typing import NDArray

from .operators import Topology
from .profiles import active

__all__ = [
    "Motion",
    "FrozenMotion",
    "SwapMotion",
    "frozen",
    "drift",
    "jump_plain",
    "jump_nnz_matched",
    "mix",
    "slice_weight",
    "slice_drift",
]


@runtime_checkable
class Motion(Protocol):
    """What a motion model must provide.

    :attr:`name` is mandatory and part of the protocol. An unnamed motion model
    produces result rows that cannot be told apart later, and two generators
    that differ by 1.8x have already shared a label once.
    """

    #: Identifies the generator, not just its family. Recorded on every row.
    name: str
    #: True only for the model that provably cannot move the dirty set.
    is_frozen: bool
    #: Churn rate. Zero if and only if :attr:`is_frozen`.
    rho: float

    def advance(
        self, dirty: NDArray[np.int32], rng: np.random.Generator
    ) -> NDArray[np.int32]:
        """Return the next step's dirty set. Must not mutate ``dirty``."""
        ...


class FrozenMotion:
    """The control: the dirty set never changes.

    Deliberately not ``drift(rho=0)``. There is no swap count to round, no
    replacement to draw, and no branch that could make it move -- it returns its
    argument. The only way this reports motion is if a caller mutates the array
    it was handed, which is why every arm here treats the dirty set as
    immutable.
    """

    name = "frozen"
    is_frozen = True
    rho = 0.0
    stalls = 0

    def advance(
        self, dirty: NDArray[np.int32], rng: np.random.Generator
    ) -> NDArray[np.int32]:
        return dirty

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return "FrozenMotion()"


def frozen() -> FrozenMotion:
    """The frozen control."""
    return FrozenMotion()


class SwapMotion:
    """Base for every model that retires columns and draws replacements.

    Subclasses supply :meth:`_replacement`. The swap count is
    ``round(rho * |D|)`` with **no** lower clamp, and a rate that rounds to zero
    raises instead of quietly behaving like the frozen control -- see the module
    docstring for what that clamp cost.

    The returned dirty set is sorted. That is not cosmetic: an arm that caches a
    compiled column slice detects churn by comparing this array to the one it
    compiled for, and an unsorted set would report churn on a step where the set
    did not actually change.
    """

    is_frozen = False

    def __init__(self, name: str, rho: float, n_cols: int) -> None:
        if not 0.0 < rho <= 1.0:
            raise ValueError(
                f"rho must be in (0, 1], got {rho}. rho=0 is not a churn rate, "
                "it is the frozen control: use spdelta.motion.frozen()"
            )
        self.name = name
        self.rho = float(rho)
        self.n_cols = int(n_cols)
        #: Diagnostic only: replacements that could not be drawn, so the column
        #: stayed. A large count means the model is running out of candidates
        #: and its effective churn rate is below its nominal one.
        self.stalls = 0

    def n_swap(self, n_dirty: int) -> int:
        """How many columns this step retires.

        Raises when the rate rounds to zero rather than clamping to one. Both
        wrong answers are available here and this is the one that is loud: a
        clamp silently converts a low churn rate into a different, higher one,
        and a floor silently converts it into the frozen control while keeping
        the churn label.
        """
        k = int(round(self.rho * n_dirty))
        if k == 0:
            raise ValueError(
                f"rho={self.rho} with |D|={n_dirty} rounds to zero swaps per "
                "step. That is neither this churn rate nor the frozen control. "
                f"Raise |D| above {int(np.ceil(0.5 / self.rho))} or use "
                "spdelta.motion.frozen() if a frozen control is what you meant"
            )
        return min(k, n_dirty)

    def _replacement(
        self, col: int, live: NDArray[np.bool_], rng: np.random.Generator
    ) -> int | None:
        """A replacement for ``col``, or ``None`` if none is available.

        ``live`` is a membership mask over columns with ``col`` already cleared,
        so an implementation must simply avoid returning a column that is
        currently ``True``.
        """
        raise NotImplementedError

    def advance(
        self, dirty: NDArray[np.int32], rng: np.random.Generator
    ) -> NDArray[np.int32]:
        out = np.array(dirty, dtype=np.int32, copy=True)
        k = out.size
        live = np.zeros(self.n_cols, dtype=bool)
        live[out] = True
        positions = rng.choice(k, size=self.n_swap(k), replace=False)
        for pos in positions:
            col = int(out[pos])
            live[col] = False
            replacement = self._replacement(col, live, rng)
            if replacement is None:
                live[col] = True
                self.stalls += 1
                continue
            out[pos] = replacement
            live[replacement] = True
        out.sort()
        return out

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"{type(self).__name__}(name={self.name!r}, rho={self.rho})"


class _Drift(SwapMotion):
    """Replacement drawn from the retiree's neighbours in a topology."""

    def __init__(self, topology: Topology, rho: float) -> None:
        super().__init__(f"drift[{topology.name}]", rho, topology.n_cols)
        self.topology = topology

    def _replacement(
        self, col: int, live: NDArray[np.bool_], rng: np.random.Generator
    ) -> int | None:
        near = self.topology.neighbors(col)
        if near.size == 0:
            return None
        free = near[~live[near]]
        if free.size == 0:
            return None
        return int(free[rng.integers(free.size)])


class _JumpPlain(SwapMotion):
    """Replacement drawn uniformly from all columns.

    Non-local by construction -- and, on any operator whose column densities are
    not uniform, also biased toward the average column. Report it as
    ``jump_plain`` and pair it with :func:`jump_nnz_matched` before attributing
    anything it shows to locality.
    """

    def __init__(self, n_cols: int, rho: float) -> None:
        super().__init__("jump_plain", rho, n_cols)

    def _replacement(
        self, col: int, live: NDArray[np.bool_], rng: np.random.Generator
    ) -> int | None:
        for _ in range(64):
            candidate = int(rng.integers(self.n_cols))
            if not live[candidate]:
                return candidate
        free = np.flatnonzero(~live)
        if free.size == 0:
            return None
        return int(free[rng.integers(free.size)])


class _JumpNnzMatched(SwapMotion):
    """Replacement drawn from the retiree's own column-density band.

    Just as non-local as :class:`_JumpPlain` -- the draw ignores adjacency
    entirely -- while holding the dirty set's total nonzero count roughly fixed.
    That is the control that separates "locality was lost" from "the slice got
    lighter", and on one measured pair those two were worth 1.41x to 1.82x.
    """

    def __init__(self, a: sp.spmatrix, rho: float, bands: int | None = None) -> None:
        csc = sp.csc_matrix(a)
        n_cols = csc.shape[1]
        super().__init__("jump_nnz_matched", rho, n_cols)
        bands = int(bands if bands is not None else active().nnz_bands)
        if bands < 1:
            raise ValueError(f"bands must be >= 1, got {bands}")
        self.bands = bands
        per_col = np.diff(csc.indptr).astype(np.int64)
        self.per_col = per_col
        top = max(int(per_col.max()), 1)
        edges = np.geomspace(1.0, top + 1.0, num=bands + 1)[1:-1]
        band_of = np.searchsorted(edges, np.maximum(per_col, 1), side="right")
        self.band_of = band_of.astype(np.int32)
        self._members = [
            np.flatnonzero(self.band_of == b).astype(np.int32) for b in range(bands)
        ]

    def _replacement(
        self, col: int, live: NDArray[np.bool_], rng: np.random.Generator
    ) -> int | None:
        members = self._members[int(self.band_of[col])]
        if members.size == 0:
            return None
        for _ in range(64):
            candidate = int(members[rng.integers(members.size)])
            if not live[candidate]:
                return candidate
        free = members[~live[members]]
        if free.size == 0:
            return None
        return int(free[rng.integers(free.size)])


class _Mix(SwapMotion):
    """Each swap is drawn from ``far`` with probability ``alpha``, else ``local``.

    Read the resulting curve as a function of the mixing parameter, not of
    locality -- unless ``far`` is :func:`jump_nnz_matched`. With
    :func:`jump_plain` as the far component, raising alpha lowers locality *and*
    lightens the slice together, in proportion, so a concavity in the curve
    cannot be attributed to either one. That confound was read as a locality
    threshold once.
    """

    def __init__(self, local: SwapMotion, far: SwapMotion, alpha: float) -> None:
        if not 0.0 <= alpha <= 1.0:
            raise ValueError(f"alpha must be in [0, 1], got {alpha}")
        if local.rho != far.rho:
            raise ValueError(
                f"components must share a churn rate; got local rho={local.rho} "
                f"and far rho={far.rho}. Mixing two rates gives a model with "
                "neither"
            )
        if local.n_cols != far.n_cols:
            raise ValueError(
                f"components disagree on column count: {local.n_cols} vs {far.n_cols}"
            )
        super().__init__(
            f"mix[{local.name}+{far.name}@alpha={alpha:g}]", local.rho, local.n_cols
        )
        self.local = local
        self.far = far
        self.alpha = float(alpha)

    def _replacement(
        self, col: int, live: NDArray[np.bool_], rng: np.random.Generator
    ) -> int | None:
        source = self.far if rng.random() < self.alpha else self.local
        return source._replacement(col, live, rng)


def drift(topology: Topology, rho: float) -> SwapMotion:
    """Local drift: replacements come from the retiree's neighbours."""
    return _Drift(topology, rho)


def jump_plain(n_cols: int, rho: float) -> SwapMotion:
    """Uniform teleport. Report it under this name, never as "jump"."""
    return _JumpPlain(n_cols, rho)


def jump_nnz_matched(
    a: sp.spmatrix, rho: float, bands: int | None = None
) -> SwapMotion:
    """Teleport within a column-density band. The control for :func:`jump_plain`."""
    return _JumpNnzMatched(a, rho, bands)


def mix(local: SwapMotion, far: SwapMotion, alpha: float) -> SwapMotion:
    """Interpolate between two swap models by per-swap coin flip."""
    return _Mix(local, far, alpha)


def slice_weight(a: sp.spmatrix, dirty: NDArray[np.int32]) -> int:
    """Total nonzeros in the dirty columns.

    The quantity a jump generator moves without meaning to. Record it at the
    first and last step of every run: if it drifted, the run measured two things
    and reported one.
    """
    csc = sp.csc_matrix(a)
    per_col = np.diff(csc.indptr)
    return int(per_col[np.asarray(dirty, dtype=np.int64)].sum())


def slice_drift(first: int, last: int) -> float:
    """``|last - first| / first`` -- how much the slice's weight moved.

    Around 0.14 for uniform jump and 0.00 for the nnz-matched control on one
    measured pair. A sweep reporting a churn effect without this number cannot
    say which of the two effects it saw.
    """
    if first <= 0:
        raise ValueError(
            f"first slice weight is {first}; a relative drift against an empty "
            "slice is not defined"
        )
    return abs(last - first) / first
