"""The controls. Everything here exists because its absence produced a wrong number.

This module is deliberately boring. None of it is clever, and every function in
it replaced a thing that had been re-derived per file and had quietly drifted.

* **Arm order is rotated, not shuffled, and not fixed.** Whichever arm runs last
  inherits the cache and TLB state the others left. Fixed order was measured at
  1.324x on one harness and 1.06x on another. Rotation equalises position while
  keeping each arm's *neighbours* fixed, so "which arm warmed the cache for
  which" does not become a second uncontrolled variable the way a shuffle makes
  it. ``rotate=False`` is kept so the bias can be measured rather than asserted:
  a paired rotated/fixed run on the same cells is the only way to say what it
  was worth.
* **The order offset is a blake2b digest, not ``hash()``.** Python salts
  ``hash()`` per process for strings, so an order derived from it differs on a
  rerun -- which makes a rerun not a rerun, and makes a recorded order a
  fiction.
* **Every result row carries ``order_pos``.** Order bias that is not recorded
  cannot be tested for afterwards, and both times it was found, it was found
  afterwards.
* **:func:`summarize` raises on empty input.** Returning 0.0 reads downstream as
  an arm of infinite speed, and a geometric mean will happily consume it.
* **The reference arm is mandatory and is asserted every repeat.** Three
  defects in one probe produced clean, well-formed, entirely plausible timings
  because each arm did the right *amount* of work on the wrong values. No
  keyword here disables the assertion.
* **The bootstrap resamples operators, not rows.** Five seeds of one operator
  are not five observations.
* **Nothing here picks a reduction.** Two defensible shapes are in use,
  :func:`reduce_flat` and :func:`reduce_median_then_geomean`, and choosing
  between them moves published numbers. Both have names; the caller says which.
"""

from __future__ import annotations

import hashlib
import math
import platform
import random
import statistics
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Hashable, Iterable, Sequence

import numpy as np
import scipy
import scipy.sparse as sp
from numpy.typing import NDArray

from .baselines import Arm, rel_l2
from .delta import CompactDelta, Delta
from .motion import Motion, slice_drift, slice_weight
from .profiles import Profile, active

__all__ = [
    "NAN",
    "CELL_KEYS",
    "geomean",
    "geomean_counted",
    "median_by",
    "reduce_flat",
    "reduce_median_then_geomean",
    "reduce_by_operator",
    "REDUCTIONS",
    "bootstrap_ci",
    "rotate",
    "offset_for",
    "order",
    "summarize",
    "Cell",
    "local_sample",
    "standard_cells",
    "sweep",
    "ratio_rows",
    "ReferenceMismatch",
    "toolchain",
]

NAN = float("nan")

Row = dict[str, Any]
ValueFn = Callable[[Row], float]

#: The cell a seed is reduced within: one operator at one churn rate. Pooling
#: across churn rate would average away the decay the whole claim is stated in
#: terms of; pooling across operators averages away the thing seeds are meant to
#: cancel *within*.
CELL_KEYS: tuple[str, ...] = ("operator", "rho")


class ReferenceMismatch(AssertionError):
    """An arm disagreed with the from-scratch reference."""


# ---------------------------------------------------------------------------
# the mean
# ---------------------------------------------------------------------------


def _positive(values: Iterable[Any]) -> tuple[list[float], int]:
    """Coerce to float, keep strictly positive, count what was dropped.

    A blank (``''`` or ``None``) means "this arm did not run in this cell" and
    is dropped. Non-positive values are dropped because the log is undefined.
    Anything else raises -- silently dropping a value that is neither a number
    nor a blank is how a truncated or wrong-schema table turns into a
    plausible-looking ratio.
    """
    kept: list[float] = []
    dropped = 0
    for x in values:
        if x is None or x == "":
            dropped += 1
            continue
        try:
            v = float(x)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{x!r} is not a number and not a blank") from exc
        if v > 0 and math.isfinite(v):
            kept.append(v)
        else:
            dropped += 1
    return kept, dropped


def geomean(values: Iterable[Any], *, empty: float = NAN) -> float:
    """The geometric mean.

    The right mean for ratios, because it is the one where
    ``geomean(1/x) == 1/geomean(x)`` -- so a speedup and the slowdown it implies
    agree with each other, which an arithmetic mean does not.
    """
    kept, _ = _positive(values)
    if not kept:
        return empty
    return math.exp(statistics.fmean(math.log(x) for x in kept))


def geomean_counted(values: Iterable[Any], *, empty: float = NAN) -> tuple[float, int]:
    """:func:`geomean`, plus how many values it dropped.

    Use it wherever a surprising drop count would change your reading: a ratio
    over three of twenty cells is not the same claim as a ratio over twenty, and
    the two are indistinguishable from the number alone.
    """
    kept, dropped = _positive(values)
    value = empty if not kept else math.exp(statistics.fmean(math.log(x) for x in kept))
    return value, dropped


# ---------------------------------------------------------------------------
# the reductions -- three shapes, no default
# ---------------------------------------------------------------------------


def _cell_of(row: Row, keys: Sequence[str]) -> tuple:
    return tuple(row[k] for k in keys)


def median_by(
    rows: Iterable[Row], value: ValueFn, keys: Sequence[str] = CELL_KEYS
) -> dict[tuple, float]:
    """``{cell: median over the seeds in that cell}``.

    The unit fix: one seed's ratio is not an operator's ratio.
    """
    buckets: dict[tuple, list[float]] = defaultdict(list)
    for r in rows:
        buckets[_cell_of(r, keys)].append(value(r))
    return {c: statistics.median(v) for c, v in buckets.items() if v}


def reduce_flat(rows: Iterable[Row], value: ValueFn, *, empty: float = NAN) -> float:
    """Geometric mean over every row, seeds pooled.

    Gives an operator measured at five seeds five times the weight of one
    measured once. Sometimes that is what you want. It is never what you want by
    accident, which is why it has a name.
    """
    return geomean([value(r) for r in rows], empty=empty)


def reduce_median_then_geomean(
    rows: Iterable[Row],
    value: ValueFn,
    keys: Sequence[str] = CELL_KEYS,
    *,
    empty: float = NAN,
) -> float:
    """Median over seeds within a cell, then geometric mean over cells."""
    return geomean(list(median_by(rows, value, keys).values()), empty=empty)


def reduce_by_operator(
    rows: Iterable[Row],
    value: ValueFn,
    operator_key: str = "operator",
    keys: Sequence[str] = CELL_KEYS,
    *,
    empty: float = NAN,
) -> float:
    """Three-level: median over seeds, geomean within operator, geomean across.

    Weights each operator equally however many churn rates it was measured at.
    Differs from the two-level shape exactly when those counts are unequal --
    which is the normal state of a sweep that lost cells.
    """
    cells = median_by(rows, value, keys)
    index = list(keys).index(operator_key)
    per_op: dict[Hashable, list[float]] = defaultdict(list)
    for cell, v in cells.items():
        per_op[cell[index]].append(v)
    return geomean([geomean(v) for v in per_op.values()], empty=empty)


#: The named reductions. A caller passes a name; nothing here has a default,
#: because the choice moves published numbers and is therefore the caller's.
REDUCTIONS: dict[str, Callable[..., float]] = {
    "reduce_flat": reduce_flat,
    "reduce_median_then_geomean": reduce_median_then_geomean,
    "reduce_by_operator": reduce_by_operator,
}


def bootstrap_ci(
    rows: Sequence[Row],
    value: ValueFn,
    *,
    reps: int | None = None,
    seed: int = 0,
    alpha: float | None = None,
    operator_key: str = "operator",
    keys: Sequence[str] = CELL_KEYS,
) -> tuple[float, float]:
    """Percentile interval for :func:`reduce_median_then_geomean`.

    Resamples **operators**, not rows. Resampling rows treats five seeds of one
    operator as five independent observations and understates the interval by
    roughly the amount that matters; the operator is the unit that varies.
    """
    profile = active()
    reps = profile.bootstrap_reps if reps is None else reps
    alpha = profile.bootstrap_alpha if alpha is None else alpha
    by_op: dict[Hashable, list[Row]] = defaultdict(list)
    for r in rows:
        by_op[r[operator_key]].append(r)
    ops = sorted(by_op, key=str)
    if len(ops) < 2:
        # A bootstrap over operators needs operators to resample. With one,
        # every draw is that same operator, every replicate is the same
        # number, and the percentile interval collapses to a point -- which
        # this function used to RETURN, as though [2.779, 2.779] were a
        # legitimate confidence interval rather than the absence of one. A
        # reader sees extreme precision.
        #
        # Zero operators returned (nan, nan) silently, which is the same
        # failure wearing a quieter face: nothing distinguishes it from a
        # computation that ran.
        #
        # This refuses for the same reason the module resamples operators
        # rather than rows in the first place: the operator is the unit that
        # varies, so with fewer than two there is no variation to measure.
        raise ValueError(
            f"bootstrap_ci needs at least two operators to resample; got "
            f"{len(ops)} ({sorted(map(str, ops)) or 'none'}). With one operator "
            f"every replicate draws the same operator, so the interval "
            f"collapses to a point and reports it as precision. Widen the "
            f"sweep, or report the single value with summarize() and say it "
            f"is one operator."
        )
    rng = random.Random(seed)
    stats: list[float] = []
    for _ in range(reps):
        draw: list[Row] = []
        for _ in ops:
            draw.extend(by_op[ops[rng.randrange(len(ops))]])
        s = reduce_median_then_geomean(draw, value, keys)
        if not math.isnan(s):
            stats.append(s)
    if not stats:
        return (NAN, NAN)
    stats.sort()
    lo = stats[max(0, int(round((alpha / 2) * (len(stats) - 1))))]
    hi = stats[min(len(stats) - 1, int(round((1 - alpha / 2) * (len(stats) - 1))))]
    return (lo, hi)


# ---------------------------------------------------------------------------
# order and statistic
# ---------------------------------------------------------------------------


def _rotate(arms: Sequence[str], offset: int) -> list[str]:
    """Cyclic rotation by ``offset``.

    A rotation, not a shuffle. Both equalise position; only a rotation keeps
    each arm's neighbours fixed.
    """
    if not arms:
        return []
    off = offset % len(arms)
    return list(arms[off:]) + list(arms[:off])


#: Public alias, so :func:`order`'s ``rotate`` keyword cannot shadow it.
rotate = _rotate


def offset_for(cell: Hashable, n: int) -> int:
    """A deterministic offset derived from a cell's identity.

    blake2b, deliberately not Python's ``hash()``: ``hash()`` is salted per
    process for strings, so a hash-derived order differs on a rerun of the same
    cell, and the order recorded on the row stops describing the run that would
    be reproduced.
    """
    if n <= 0:
        return 0
    digest = hashlib.blake2b(repr(tuple(cell)).encode(), digest_size=8).digest()
    return int.from_bytes(digest, "big") % n


def order(arms: Sequence[str], cell: Hashable, *, rotate: bool = True) -> list[str]:
    """The order to run ``arms`` in for this cell.

    ``rotate=False`` keeps the declared order and exists so the bias can be
    measured rather than merely asserted.
    """
    return _rotate(arms, offset_for(cell, len(arms))) if rotate else list(arms)


_STATS: dict[str, Callable[[Sequence[float]], float]] = {
    "median": statistics.median,
    "mean": statistics.fmean,
    "min": min,
}


def summarize(samples: Sequence[float], stat: str = "median") -> float:
    """Reduce per-step timings to the cell's number.

    Median by default: a page fault inside a microsecond-scale kernel moves a
    mean by tens of percent.

    Raises on empty input rather than returning 0.0 -- which downstream reads as
    an infinitely fast arm -- and on an unknown statistic rather than falling
    back to one the caller did not choose.
    """
    if stat not in _STATS:
        raise ValueError(
            f"unknown statistic {stat!r}; expected one of {sorted(_STATS)}"
        )
    if len(samples) == 0:
        raise ValueError("no samples to summarize")
    return float(_STATS[stat](samples))


def toolchain() -> str:
    """What this ran on, in one string, for the row and for the claim."""
    return (
        f"CPython {platform.python_version()} / numpy {np.__version__} / "
        f"scipy {scipy.__version__} / {platform.machine()} {platform.system()}"
    )


# ---------------------------------------------------------------------------
# cells
# ---------------------------------------------------------------------------


@dataclass(frozen=True, eq=False)
class Cell:
    """One measurable configuration: operator, motion, dirty set, width, seed.

    ``eq=False`` because it holds arrays and a sparse matrix; identity is the
    :attr:`key`, which is what gets recorded and what the order offset is
    derived from.
    """

    operator: str
    a: sp.spmatrix
    motion: Motion
    dirty0: NDArray[np.int32]
    batch: int
    seed: int

    def __post_init__(self) -> None:
        dirty = np.asarray(self.dirty0, dtype=np.int32)
        if dirty.ndim != 1 or dirty.size == 0:
            raise ValueError("dirty0 must be a non-empty 1-D array")
        if np.unique(dirty).size != dirty.size:
            raise ValueError("dirty0 contains duplicates")
        if int(dirty.max()) >= self.a.shape[1]:
            raise ValueError(
                f"dirty0 references column {int(dirty.max())} but the operator "
                f"has {self.a.shape[1]} columns"
            )
        object.__setattr__(self, "dirty0", np.sort(dirty))

    @property
    def rho(self) -> float:
        return float(self.motion.rho)

    @property
    def n_dirty(self) -> int:
        return int(self.dirty0.size)

    @property
    def key(self) -> tuple:
        """What identifies this cell in a row, and what seeds the arm order."""
        return (
            self.operator,
            self.motion.name,
            self.rho,
            self.n_dirty,
            self.batch,
            self.seed,
        )


def local_sample(
    n_cols: int, n_dirty: int, seed: int, *, spread: int = 3
) -> NDArray[np.int32]:
    """``n_dirty`` columns sampled from a local window of width ``spread * n_dirty``.

    Local, but **not** a solid interval, and the difference is not cosmetic. A
    solid interval has no free neighbours anywhere except at its two ends, so a
    local drift model applied to one stalls on nearly every swap and the cell
    quietly becomes the frozen control while still carrying a churn label. That
    is the same mislabel a clamped swap count produced, arriving from the other
    direction, and it is just as invisible in the timings.

    ``spread`` is how much room the dirty set has to move within. A real dirty
    set -- a mesh neighbourhood, a fault-affected region, the support of a
    trial step -- is a locally dense but not solid subset, so this is also the
    more faithful shape.
    """
    if n_dirty > n_cols:
        raise ValueError(f"n_dirty {n_dirty} exceeds n_cols {n_cols}")
    if spread < 1:
        raise ValueError(f"spread must be >= 1, got {spread}")
    rng = np.random.default_rng(seed)
    width = min(n_cols, spread * n_dirty)
    start = int(rng.integers(0, n_cols - width + 1))
    picked = rng.choice(width, size=n_dirty, replace=False) + start
    return np.sort(picked.astype(np.int32))


def standard_cells(
    operators: Sequence[tuple[str, sp.spmatrix]],
    motion_factories: Sequence[Callable[[str, sp.spmatrix, float], Motion]],
    *,
    rhos: Sequence[float] | None = None,
    seeds: Sequence[int] = (17, 18, 19),
    n_dirty: int | None = None,
    batch: int | None = None,
    spread: int = 3,
    profile: Profile | None = None,
) -> list[Cell]:
    """Cross operators x motions x churn rates x seeds into cells.

    A motion factory takes ``(operator_name, matrix, rho)`` because the motion
    models genuinely need the operator: local drift needs its topology and the
    nnz-matched control needs its column densities. A factory that ignores rho
    -- the frozen control -- is called once per operator and seed, not once per
    rho, so the frozen control appears exactly once and cannot be double-counted
    into a churn aggregate.
    """
    profile = profile or active()
    rhos = tuple(profile.rho_grid) if rhos is None else tuple(rhos)
    n_dirty = profile.n_dirty if n_dirty is None else n_dirty
    batch = profile.batch if batch is None else batch
    cells: list[Cell] = []
    for name, a in operators:
        for seed in seeds:
            dirty0 = local_sample(int(a.shape[1]), n_dirty, seed, spread=spread)
            seen: set[str] = set()
            for factory in motion_factories:
                for rho in rhos:
                    motion = factory(name, a, rho)
                    if motion.is_frozen:
                        if motion.name in seen:
                            continue
                        seen.add(motion.name)
                    cells.append(
                        Cell(
                            operator=name,
                            a=a,
                            motion=motion,
                            dirty0=dirty0,
                            batch=batch,
                            seed=seed,
                        )
                    )
    return cells


# ---------------------------------------------------------------------------
# the sweep
# ---------------------------------------------------------------------------


@dataclass
class _Stream:
    """The exact input sequence every arm in a repeat will see."""

    updates: list[tuple[NDArray[np.int32], NDArray[np.float64]]] = field(
        default_factory=list
    )
    weight_first: int = 0
    weight_last: int = 0
    #: Steps on which the dirty set actually differed from the previous one.
    #: Zero on a cell labelled with a churn rate means the cell is the frozen
    #: control wearing somebody else's label.
    changes: int = 0


def _build_stream(cell: Cell, repeat: int, steps: int) -> _Stream:
    """Generate one repeat's updates, deterministically.

    Built once and handed to every arm as private copies. Two reasons it is not
    regenerated per arm: identical inputs are then a fact rather than a property
    of the generator being pure, and generation stays outside every timer where
    it belongs.
    """
    # blake2b over the cell identity, for the same reason `offset_for` uses it:
    # a seed derived from `hash()` is salted per process, so the "same" repeat
    # would replay a different update stream tomorrow.
    seed = (
        int.from_bytes(
            hashlib.blake2b(
                repr((cell.key, repeat)).encode(), digest_size=8
            ).digest(),
            "big",
        )
        % (2**32)
    )
    rng = np.random.default_rng(seed)
    stream = _Stream()
    dirty = cell.dirty0
    stream.weight_first = slice_weight(cell.a, dirty)
    for _ in range(steps):
        vals = rng.standard_normal((dirty.size, cell.batch))
        stream.updates.append((dirty, vals))
        moved_to = cell.motion.advance(dirty, rng)
        if moved_to.size != dirty.size or not np.array_equal(moved_to, dirty):
            stream.changes += 1
        dirty = moved_to
    stream.weight_last = slice_weight(cell.a, dirty)
    return stream


def _as_delta(kind: str, cols: NDArray[np.int32], vals: NDArray[np.float64], m: int) -> Delta:
    """Build this arm's private delta object in the encoding it declared."""
    compact = CompactDelta(np.array(cols, dtype=np.int32, copy=True), np.array(vals, copy=True))
    if kind == "compact":
        return compact
    if kind == "global":
        return compact.to_global(m)
    raise ValueError(f"unknown delta kind {kind!r}; expected 'compact' or 'global'")


def sweep(
    arms: Sequence[Arm],
    cells: Sequence[Cell],
    *,
    reference: Arm,
    tol: float | None = None,
    repeats: int | None = None,
    steps: int | None = None,
    stat: str | None = None,
    rotate: bool | None = None,
    profile: Profile | None = None,
) -> list[Row]:
    """Run every arm on every cell and return one row per (cell, repeat, arm).

    ``reference`` has no default and cannot be switched off. It is prepared and
    run untimed on the identical update stream before the timed arms, and every
    arm's result is compared to it after every repeat. If that check fails, the
    sweep raises :class:`ReferenceMismatch` rather than recording the error and
    carrying on -- an error written to a column that nothing reads is not a
    check.

    Every row carries ``order_pos``, so order bias remains testable after the
    fact, and ``prepare_seconds`` separately from ``seconds_per_step``, so an
    arm cannot be credited for preparation another arm paid for.
    """
    if reference is None:  # type: ignore[comparison-overlap]
        raise TypeError(
            "sweep() requires a reference arm; there is no way to disable it. "
            "Timings alone cannot see an arm that does the right amount of "
            "work on the wrong values"
        )
    profile = profile or active()
    tol = profile.tolerance if tol is None else float(tol)
    repeats = profile.repeats if repeats is None else int(repeats)
    steps = profile.steps if steps is None else int(steps)
    stat = profile.stat if stat is None else stat
    rotate_arms = profile.rotate if rotate is None else bool(rotate)
    if not arms:
        raise ValueError("no arms to sweep")
    if repeats < 1 or steps < 1:
        raise ValueError(f"repeats and steps must be >= 1; got {repeats}, {steps}")
    names = [arm.name for arm in arms]
    if len(set(names)) != len(names):
        raise ValueError(f"arm names must be unique, got {names}")
    if reference.name in names:
        raise ValueError(
            f"the reference arm {reference.name!r} is also a timed arm; it "
            "would be asserted against itself and pass vacuously"
        )
    by_name = {arm.name: arm for arm in arms}
    chain = toolchain()
    control = (
        f"reference={reference.name}; rotate={rotate_arms}; repeats={repeats}; "
        f"steps={steps}; stat={stat}; tol={tol:g}"
    )

    rows: list[Row] = []
    for cell in cells:
        n_rows_op, n_cols_op = int(cell.a.shape[0]), int(cell.a.shape[1])
        nnz = int(cell.a.nnz)
        for repeat in range(repeats):
            stream = _build_stream(cell, repeat, steps)
            drift_of_slice = slice_drift(stream.weight_first, stream.weight_last)
            if not cell.motion.is_frozen and stream.changes == 0:
                # A cell labelled with a churn rate whose dirty set never moved
                # is the frozen control in disguise, and averaging it into a
                # churn aggregate drags that aggregate toward the frozen answer.
                # It is not a timing anomaly and nothing downstream can see it.
                raise ValueError(
                    f"cell {cell.key} is labelled motion {cell.motion.name!r} at "
                    f"rho={cell.rho} but its dirty set never changed over "
                    f"{steps} steps ({getattr(cell.motion, 'stalls', 0)} stalled "
                    "swaps). Give the dirty set room to move -- see "
                    "spdelta.harness.local_sample -- or use motion.frozen() and "
                    "label it honestly"
                )

            reference.prepare(cell.a, cell.dirty0)
            y_ref = np.zeros((n_rows_op, cell.batch), dtype=np.float64)
            for cols, vals in stream.updates:
                reference.step(
                    _as_delta(reference.delta_kind, cols, vals, n_cols_op), y_ref
                )

            run_order = order(names, cell.key + (repeat,), rotate=rotate_arms)
            for position, name in enumerate(run_order):
                arm = by_name[name]
                deltas = [
                    _as_delta(arm.delta_kind, cols, vals, n_cols_op)
                    for cols, vals in stream.updates
                ]
                t0 = time.perf_counter_ns()
                arm.prepare(cell.a, cell.dirty0)
                prepare_ns = time.perf_counter_ns() - t0
                y = np.zeros((n_rows_op, cell.batch), dtype=np.float64)
                samples: list[float] = []
                for d in deltas:
                    t = time.perf_counter_ns()
                    arm.step(d, y)
                    samples.append(float(time.perf_counter_ns() - t))
                error = rel_l2(y, y_ref)
                if not (error <= tol):
                    raise ReferenceMismatch(
                        f"{name} disagreed with {reference.name} by relative L2 "
                        f"{error:.3e} > {tol:.3e} on operator {cell.operator!r}, "
                        f"motion {cell.motion.name!r}, repeat {repeat}. Timings "
                        "cannot see this class of defect: check the delta "
                        "encoding the arm consumes, and whether any reused "
                        "buffer was re-zeroed"
                    )
                row: Row = {
                    "operator": cell.operator,
                    "n_rows": n_rows_op,
                    "n_cols": n_cols_op,
                    "nnz": nnz,
                    "motion": cell.motion.name,
                    "rho": cell.rho,
                    "is_frozen": bool(cell.motion.is_frozen),
                    "seed": cell.seed,
                    "batch": cell.batch,
                    "n_dirty": cell.n_dirty,
                    "steps": steps,
                    "repeat": repeat,
                    "arm": name,
                    "delta_kind": arm.delta_kind,
                    "order_pos": position,
                    "order_n": len(run_order),
                    "rotate": rotate_arms,
                    "stat": stat,
                    "seconds_per_step": summarize(samples, stat) * 1e-9,
                    "seconds_total": float(sum(samples)) * 1e-9,
                    "prepare_seconds": prepare_ns * 1e-9,
                    "rel_err": error,
                    "tol": tol,
                    "slice_weight_first": stream.weight_first,
                    "slice_weight_last": stream.weight_last,
                    "slice_drift": drift_of_slice,
                    "dirty_set_changes": stream.changes,
                    "motion_stalls": int(getattr(cell.motion, "stalls", 0)),
                    "profile": profile.name,
                    "toolchain": chain,
                    "control": control,
                }
                row.update(arm.stats())
                rows.append(row)
    return rows


_PAIR_KEYS = (
    "operator",
    "motion",
    "rho",
    "seed",
    "repeat",
    "batch",
    "n_dirty",
    "steps",
)


def ratio_rows(rows: Sequence[Row], *, arm: str, baseline: str) -> list[Row]:
    """Pair ``arm`` against ``baseline`` within each cell and repeat.

    ``ratio`` is ``baseline / arm``, so above 1 means the arm is faster. The
    pairing is exact -- same operator, motion, rate, seed, repeat, width -- and
    an unpaired row is dropped with the count reported in ``n_unpaired`` on
    every surviving row, because a ratio computed over a silently halved set of
    cells is the oldest way to publish the wrong number.
    """
    if arm == baseline:
        raise ValueError("arm and baseline must differ")
    index: dict[tuple, dict[str, Row]] = defaultdict(dict)
    for r in rows:
        if r["arm"] in (arm, baseline):
            index[tuple(r[k] for k in _PAIR_KEYS)][r["arm"]] = r
    paired: list[Row] = []
    unpaired = 0
    for key, pair in index.items():
        if arm not in pair or baseline not in pair:
            unpaired += 1
            continue
        fast, slow = pair[arm], pair[baseline]
        out = {k: v for k, v in zip(_PAIR_KEYS, key)}
        out.update(
            {
                "arm": arm,
                "baseline": baseline,
                "ratio": slow["seconds_per_step"] / fast["seconds_per_step"],
                "arm_seconds_per_step": fast["seconds_per_step"],
                "baseline_seconds_per_step": slow["seconds_per_step"],
                "arm_order_pos": fast["order_pos"],
                "baseline_order_pos": slow["order_pos"],
                "is_frozen": fast["is_frozen"],
                "slice_drift": fast["slice_drift"],
                "profile": fast["profile"],
                "toolchain": fast["toolchain"],
                "control": fast["control"],
            }
        )
        paired.append(out)
    for out in paired:
        out["n_unpaired"] = unpaired
    return paired
