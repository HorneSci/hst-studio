"""The worked example: a toy operator, the ladder, and a claim.

Run it::

    python -m spdelta.example

Everything it touches is generated from a seed in this repository. The operator
is synthetic and small, the profile is the public one, and the resulting claim
says so on its face -- it is a demonstration of the *method*, and the numbers it
prints are numbers about a laptop.
"""

from __future__ import annotations

import argparse

import numpy as np
import scipy.sparse as sp

from .baselines import ColumnDeltaCsc, FullMatvec, MaskedRowScan, reference
from .claim import Claim
from .harness import (
    bootstrap_ci,
    ratio_rows,
    reduce_median_then_geomean,
    standard_cells,
    sweep,
)
from .motion import Motion, drift, frozen, jump_nnz_matched, jump_plain
from .operators import Topology, suite
from .profiles import Profile, active


def motion_factories(
    radius: int,
) -> list:
    """Four named motion models, built per operator.

    The frozen control is first because it is the one that decides whether the
    rest of the table is worth reading.
    """

    def make_frozen(name: str, a: sp.spmatrix, rho: float) -> Motion:
        return frozen()

    def make_drift(name: str, a: sp.spmatrix, rho: float) -> Motion:
        return drift(Topology.line(int(a.shape[1]), radius=radius), rho)

    def make_jump_plain(name: str, a: sp.spmatrix, rho: float) -> Motion:
        return jump_plain(int(a.shape[1]), rho)

    def make_jump_matched(name: str, a: sp.spmatrix, rho: float) -> Motion:
        return jump_nnz_matched(a, rho)

    return [make_frozen, make_drift, make_jump_plain, make_jump_matched]


def run(profile: Profile | None = None, seeds: tuple[int, ...] = (17, 18)) -> None:
    profile = profile or active()
    operators = suite(profile)
    cells = standard_cells(
        operators,
        motion_factories(profile.drift_radius),
        seeds=seeds,
        profile=profile,
    )
    arms = [FullMatvec(), MaskedRowScan(), ColumnDeltaCsc()]
    rows = sweep(arms, cells, reference=reference(), profile=profile)

    print(f"profile: {profile.name}   cells: {len(cells)}   rows: {len(rows)}")
    print()
    print("per-step seconds, median over steps then over repeats")
    print(f"{'motion':<34}{'rho':>6}  " + "".join(f"{a.name:>20}" for a in arms))
    seen: set[tuple[str, float]] = set()
    for row in rows:
        key = (row["motion"], row["rho"])
        if key in seen:
            continue
        seen.add(key)
        cells_here = [
            r for r in rows if r["motion"] == key[0] and r["rho"] == key[1]
        ]
        line = f"{key[0]:<34}{key[1]:>6.2f}  "
        for arm in arms:
            values = [
                r["seconds_per_step"] for r in cells_here if r["arm"] == arm.name
            ]
            line += f"{float(np.median(values)):>20.3e}"
        print(line)

    print()
    print("the rung question: is the incumbent skipping the work, or the scan?")
    for rung in ("full_matvec", "masked_row_scan"):
        paired = ratio_rows(rows, arm="column_delta_csc", baseline=rung)
        churning = [r for r in paired if not r["is_frozen"]]
        value = reduce_median_then_geomean(churning, lambda r: float(r["ratio"]))
        print(f"  column_delta_csc vs {rung:<16} {value:6.2f}x over churning cells")

    print()
    target_rho = profile.rho_grid[0]
    paired = ratio_rows(rows, arm="column_delta_csc", baseline="masked_row_scan")
    subset = [
        r
        for r in paired
        if r["motion"].startswith("drift") and r["rho"] == target_rho
    ]
    claim = Claim.from_rows(
        subset, baseline="masked_row_scan", reduction="reduce_median_then_geomean"
    ).with_ceiling(max(profile.rho_grid))
    lo, hi = bootstrap_ci(subset, lambda r: float(r["ratio"]))
    print(claim)
    print(f"  bootstrap   [{lo:.3f}, {hi:.3f}] over operators")
    print()
    print("float(claim) raises TypeError on purpose: the number does not travel")
    print("without the block above it.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--seeds", type=int, nargs="+", default=[17, 18], help="operator seeds"
    )
    args = parser.parse_args()
    run(seeds=tuple(args.seeds))


if __name__ == "__main__":
    main()
