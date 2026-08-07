"""spdelta -- honest measurement for delta-updated sparse matvecs.

The workload: a sparse operator ``A`` is fixed, a state ``x`` changes by a
sparse update ``dx`` each step, and you want ``A @ (x + dx)``. There are several
ways to compute that, they differ by orders of magnitude, and which one wins
depends on conditions that are easy to leave out of the write-up.

This package provides the parts that make such a comparison mean something:

* :mod:`spdelta.delta` -- two update encodings as distinct types, so handing a
  kernel the wrong one is a ``TypeError`` instead of a plausible wrong answer.
* :mod:`spdelta.baselines` -- the rung ladder, from full recompute to a
  competent column delta, plus a from-scratch oracle.
* :mod:`spdelta.motion` -- how the dirty set moves, with the frozen control as
  a separate object and the two teleport generators under separate names.
* :mod:`spdelta.harness` -- arm-order rotation, deterministic offsets, the
  reductions, an operator-level bootstrap, and a sweep whose reference
  assertion cannot be switched off.
* :mod:`spdelta.claim` -- a ratio welded to its conditions, with no way to
  extract the float by accident.
* :mod:`spdelta.profiles` -- every tunable constant in one object, so the split
  between a public default and an internal one is configuration, not a fork.

Fifteen-minute path: see the README, or run ``python -m spdelta.example``.
"""

from __future__ import annotations

from .baselines import (
    Arm,
    ColumnDeltaCsc,
    FullMatvec,
    MaskedRowScan,
    ScratchReference,
    ladder,
    reference,
    rel_l2,
)
from .claim import Claim
from .delta import (
    CompactDelta,
    Delta,
    GlobalDelta,
    GlobalScatter,
    require_compact,
    require_global,
)
from .harness import (
    REDUCTIONS,
    Cell,
    ReferenceMismatch,
    bootstrap_ci,
    geomean,
    geomean_counted,
    local_sample,
    offset_for,
    order,
    ratio_rows,
    reduce_by_operator,
    reduce_flat,
    reduce_median_then_geomean,
    standard_cells,
    summarize,
    sweep,
    toolchain,
)
from .motion import (
    Motion,
    drift,
    frozen,
    jump_nnz_matched,
    jump_plain,
    mix,
    slice_drift,
    slice_weight,
)
from .operators import Topology, banded, build, fanout, grid2d, suite
from .profiles import PUBLIC, Profile, ToySpec, active, derive, load, use

__version__ = "0.1.0"

__all__ = [
    "__version__",
    # delta
    "CompactDelta",
    "GlobalDelta",
    "GlobalScatter",
    "Delta",
    "require_compact",
    "require_global",
    # baselines
    "Arm",
    "FullMatvec",
    "MaskedRowScan",
    "ColumnDeltaCsc",
    "ScratchReference",
    "ladder",
    "reference",
    "rel_l2",
    # motion
    "Motion",
    "frozen",
    "drift",
    "jump_plain",
    "jump_nnz_matched",
    "mix",
    "slice_weight",
    "slice_drift",
    # operators
    "banded",
    "grid2d",
    "fanout",
    "build",
    "suite",
    "Topology",
    # harness
    "Cell",
    "local_sample",
    "standard_cells",
    "sweep",
    "ratio_rows",
    "ReferenceMismatch",
    "order",
    "offset_for",
    "summarize",
    "geomean",
    "geomean_counted",
    "reduce_flat",
    "reduce_median_then_geomean",
    "reduce_by_operator",
    "REDUCTIONS",
    "bootstrap_ci",
    "toolchain",
    # claim
    "Claim",
    # profiles
    "Profile",
    "ToySpec",
    "PUBLIC",
    "active",
    "derive",
    "load",
    "use",
]

# `dir(spdelta)` should match the table above (and this __all__), not leak
# implementation detail. Two things land in this module's namespace as a
# side effect of the statements above and are not part of the documented
# surface: `annotations`, bound by `from __future__ import annotations` at
# the top of this file (safe to remove -- postponed evaluation is a compile-
# time effect, not a runtime dependency on that name), and the eight
# submodules (`baselines`, `claim`, ...), bound automatically the moment
# Python imports names out of them. Neither is wrong to import explicitly
# (`import spdelta.baselines` still works fine -- that re-adds the
# attribute), but neither belongs in a fresh `dir(spdelta)` either.
del annotations, baselines, claim, delta, harness, motion, operators, profiles
