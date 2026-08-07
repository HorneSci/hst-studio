"""One aggregation rule for benchmark result rows.

Before this module the estate carried **seventeen** independent geometric
means, in three behavioural variants, and re-derived the frozen-cell exclusion
rule six times in files that already imported the module owning it.

They agreed numerically on well-formed positive input. They disagreed on:

* **empty input** -- fifteen returned nan, `paper/figures.py:71` and
  `paper/tables.py:32` raised `ZeroDivisionError`, both in the paper build path;
* **blank cells** -- thirteen dropped `''`/`None`, two raised `TypeError`;
* **strings** -- `csv.DictReader` yields strings, and only two coerced;
* **accumulation** -- fourteen used `sum(log)/len`, two `statistics.fmean`,
  one numpy.

None of that was visible at a call site reading `geo(xs)`.

The open question this module does NOT decide
---------------------------------------------
There are two defensible reduction shapes in use, and this estate documents
**both** as "the paper's aggregation rule":

* `reduce_flat` -- geometric mean over every row, seeds pooled.
  Documented as the rule at `analyze_p4.py:47-50`.
* `reduce_median_then_geomean` -- median over seeds within an (operator, churn
  rate) cell first, then geometric mean over cells. Documented as the rule at
  `paper_numbers.py:55`, `analyze_family.py:62`, `control_bootstrap.py:95`,
  `merge_structural.py:121`.

`paper_numbers.py` uses the first at line 920 and the second at line 221 -- for
the same `csr/hst` ratio, 700 lines apart. Its own `med_by_op` docstring says
why the flat one is wrong: one seed's ratio is not an operator's ratio, and the
harness floor reaches +-12% per operator on cells where the answer cannot have
changed.

Choosing between them moves published numbers, so this module does not choose.
It gives both a name, so that a call site now says which one it meant and a
reader can tell without reconstructing it. Resolving the question is a separate
decision, taken once, with the movement measured.

`reduce_by_operator` is a third shape, three-level, used by
`compare_prep_gap.py:34-36` for the preparation-gap table. It weights operators
equally regardless of how many churn rates each was measured at.

--- vendored into oss/paper-artifact 2026-08-05 ---
Verbatim copy of `learn/pytorch_fit/agg.py`. This module is a generic,
stdlib-only aggregation seam with no kernel content; it is imported by
`paper/paper_numbers.py`, `paper/figures.py`, `paper/tables.py` and
`paper/router_data.py`, which all `sys.path.insert(0, DATA)` to the artifact
root expecting to find it here. Edit the source of truth in
`learn/pytorch_fit/agg.py`, not this copy.
"""

from __future__ import annotations

import math
import random
import statistics
from collections import defaultdict
from typing import Any, Callable, Hashable, Iterable, Sequence

NAN = float("nan")

Row = dict
ValueFn = Callable[[Row], float]

#: The cell a seed is reduced within. An (operator, churn rate) pair -- pooling
#: across churn rate would average away the decay the envelope is stated in
#: terms of, and pooling across operators is the thing seeds are meant to
#: cancel within.
CELL_KEYS = ("matrix", "rho")


# ---------------------------------------------------------------------------
# the mean
# ---------------------------------------------------------------------------

def _positive(values: Iterable[Any]) -> tuple[list[float], int]:
    """Coerce to float, keep strictly positive, count what was dropped.

    Blank (`''`/`None`) means "this arm did not run in this cell" and is
    dropped, matching what thirteen of the seventeen definitions did.
    Non-positive values are dropped because log is undefined there.

    Anything else raises. That is the one deliberate departure: silently
    dropping a value that is neither a number nor a blank is how a truncated
    or wrong-schema CSV turns into a plausible-looking ratio, and this project
    has already published from a partial CSV once.
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
            raise ValueError(f"agg: {x!r} is not a number and not a blank") from exc
        if v > 0:
            kept.append(v)
        else:
            dropped += 1
    return kept, dropped


def geomean(values: Iterable[Any], *, empty: float = NAN) -> float:
    """The geometric mean -- the right mean for ratios, because it is the one
    where geomean(1/x) == 1/geomean(x), so a speedup and its inverse agree.

    Returns `empty` (nan by default) rather than raising on no input.
    """
    kept, _ = _positive(values)
    if not kept:
        return empty
    return math.exp(statistics.fmean(math.log(x) for x in kept))


def geomean_counted(values: Iterable[Any], *, empty: float = NAN) -> tuple[float, int]:
    """`geomean`, plus how many values it dropped.

    Worth using wherever a surprising drop count would change your reading of
    the result -- a ratio over three of twenty cells is not the same claim as
    a ratio over twenty.
    """
    kept, dropped = _positive(values)
    return (empty if not kept else
            math.exp(statistics.fmean(math.log(x) for x in kept))), dropped


# ---------------------------------------------------------------------------
# the reductions -- see the module docstring on why there are three
# ---------------------------------------------------------------------------

def _cell(row: Row, keys: Sequence[str]) -> tuple:
    return tuple(row[k] for k in keys)


def median_by(rows: Iterable[Row], value: ValueFn,
              keys: Sequence[str] = CELL_KEYS) -> dict[tuple, float]:
    """{cell: median over the seeds in that cell}.

    The unit `CONTRIBUTION.md` 4c fixes: one seed's ratio is not an operator's
    ratio.
    """
    buckets: dict[tuple, list[float]] = defaultdict(list)
    for r in rows:
        buckets[_cell(r, keys)].append(value(r))
    return {c: statistics.median(v) for c, v in buckets.items() if v}


def reduce_flat(rows: Iterable[Row], value: ValueFn, *, empty: float = NAN) -> float:
    """Geometric mean over every row, seeds pooled.

    Gives an operator measured at five seeds five times the weight of one
    measured at one. Use deliberately, not by default.
    """
    return geomean([value(r) for r in rows], empty=empty)


def reduce_median_then_geomean(rows: Iterable[Row], value: ValueFn,
                               keys: Sequence[str] = CELL_KEYS,
                               *, empty: float = NAN) -> float:
    """Median over seeds within each cell, then geometric mean over cells."""
    return geomean(list(median_by(rows, value, keys).values()), empty=empty)


def reduce_by_operator(rows: Iterable[Row], value: ValueFn,
                       operator_key: str = "matrix",
                       keys: Sequence[str] = CELL_KEYS,
                       *, empty: float = NAN) -> float:
    """Three-level: median over seeds, geomean within operator, geomean across.

    Weights each operator equally however many churn rates it was measured at.
    Differs from the two-level shape exactly when those counts are unequal.
    """
    cells = median_by(rows, value, keys)
    op_index = list(keys).index(operator_key)
    per_op: dict[Hashable, list[float]] = defaultdict(list)
    for cell, v in cells.items():
        per_op[cell[op_index]].append(v)
    return geomean([geomean(v) for v in per_op.values()], empty=empty)


# ---------------------------------------------------------------------------
# the exclusion rule
# ---------------------------------------------------------------------------

def is_frozen_mislabelled(row: Row) -> bool:
    """A cell claiming a churn rate whose dirty set never actually moved.

    `rho > 0` with zero router probes means no re-decision ever happened, so
    the cell is frozen wearing a churn label. Including it drags a churn
    aggregate toward the frozen answer.

    A row with no probe column cannot be judged and is kept -- absence must not
    read as zero, or every row of the CSV families that lack the column would
    be dropped.
    """
    if "router_probes" not in row:
        return False
    try:
        rho = float(row.get("rho") or 0.0)
        probes = float(row["router_probes"] or 0.0)
    except (TypeError, ValueError):
        return False
    return rho > 0.0 and probes == 0.0


def drop_frozen_mislabelled(rows: Iterable[Row]) -> tuple[list[Row], int]:
    """Filter by `is_frozen_mislabelled`, reporting the count dropped."""
    rows = list(rows)
    kept = [r for r in rows if not is_frozen_mislabelled(r)]
    return kept, len(rows) - len(kept)


def moved(row: Row) -> bool:
    """Did this cell's dirty set actually move? (`router_probes > 0`)

    The positive form. Distinct from `not is_frozen_mislabelled` because a
    frozen cell (rho == 0) has not moved either, but is correctly labelled --
    so the two are not complements. Keep them apart: use `moved` when you need
    motion, `is_frozen_mislabelled` when you need to exclude a mislabel.
    """
    try:
        return float(row.get("router_probes") or 0.0) > 0.0
    except (TypeError, ValueError):
        return False


def both_moved(a: Row, b: Row) -> bool:
    """Both sides of a paired comparison moved.

    A paired contrast (native vs relabelled, g++ vs clang) is only meaningful
    where both arms actually churned; one frozen side makes the pair a
    comparison of a churning arm against a frozen one.
    """
    return moved(a) and moved(b)


# ---------------------------------------------------------------------------
# uncertainty
# ---------------------------------------------------------------------------

def bootstrap_ci(rows: Sequence[Row], value: ValueFn,
                 *, reps: int = 2000, seed: int = 0, alpha: float = 0.05,
                 operator_key: str = "matrix",
                 keys: Sequence[str] = CELL_KEYS) -> tuple[float, float]:
    """Percentile CI for `reduce_median_then_geomean`, resampling OPERATORS.

    Resampling rows would treat five seeds of one operator as five independent
    observations and understate the interval; the operator is the unit that
    varies. Replaces three separate implementations
    (`predictor_study.py:253`, `selection_reexam.py:114`,
    `control_bootstrap.py:177`), which agreed on 95% percentile-over-operators
    and shared no code.
    """
    by_op: dict[Hashable, list[Row]] = defaultdict(list)
    for r in rows:
        by_op[r[operator_key]].append(r)
    ops = sorted(by_op, key=str)
    if not ops:
        return (NAN, NAN)

    rng = random.Random(seed)
    stats = []
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
