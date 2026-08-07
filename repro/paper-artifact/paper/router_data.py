#!/usr/bin/env python3
"""One reader for the router sweep, shared by every consumer.

`router_v3.csv` is retired. It was recorded before the session-scratch defect
in CONTRIBUTION.md §8 was removed -- `hst_open_session` zero-filled an M*B f64
scratch (up to 10.4 MB) outside its build timer, and every harness here times a
rebuild around the whole `op.session(...)` call, so the fill was charged to
every HST lane and to no baseline. The replacement vintage is the pooled-scratch
sweep:

    seeds_drift_pooled.csv   21 operators x 5 rho x 5 seeds, local drift
    seeds_jump_pooled.csv    21 operators x 5 rho x 5 seeds, uniform jump

Both are supersets of `router_v3.csv`'s configuration: same operators, same
B=8, tile=8, 400 steps, and seed 17 with rho in {0, 0.01, 0.05, 0.25} reproduces
its 84 cells exactly. They add rho=0.002 (where the flip is largest), four more
seeds, and the second motion model.

## Rules this module enforces, so no consumer has to remember them

  * **`cyclic` is refused, not skipped.** Its HST arm caches 8 tile sets against
    the baseline arm's one, so every `cyclic` ratio is a cache-capacity
    comparison (CONTRIBUTION.md §4c). `load("cyclic")` raises.
  * **drift and jump are never pooled.** `load()` takes exactly one model and
    the rows carry `model` so a caller cannot lose track of which it holds.
  * **Frozen and churning are never pooled silently.** `split()` returns them
    separately and names the mixture explicitly when a caller wants both.
  * **The exclusion rule.** A row with `rho > 0` and `router_probes == 0` never
    moved its dirty set -- rho is a rate and it quantizes. Those are frozen
    cells wearing a churn label; they are dropped from the churning population
    and the count is exposed as `DROPPED` so it can be checked, never hidden.
"""
import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))         # paper/
ROOT = os.path.dirname(HERE)                               # paper-artifact/, where agg.py/vintage.py/columns.py live
DATA = os.path.join(ROOT, "data")                           # the released CSVs
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)                                # so `import agg` resolves when run standalone

SOURCES = {
    "drift": "seeds_drift_pooled.csv",   # local: dirty set migrates through A's adjacency
    "jump": "seeds_jump_pooled.csv",     # uniform: dirty set redrawn from all live columns
}
MODELS = ("drift", "jump")
MODEL_LABEL = {"drift": "local drift", "jump": "uniform jump"}

#: filled by load(); {model: [(matrix, seed, rho), ...]} dropped by the exclusion rule
DROPPED = {}


from agg import geomean  # noqa: E402
import columns  # noqa: E402


def load(model, keep_phantom=False):
    """Rows for one motion model, exclusion rule applied.

    `keep_phantom=True` keeps the rho>0 rows whose dirty set never moved. Only
    a diagnostic wants those.
    """
    if model == "cyclic":
        raise ValueError(
            "cyclic is not reportable: its HST arm caches 8 tile sets and the "
            "baseline arm one, so the ratio measures cache capacity, not "
            "structure (CONTRIBUTION.md 4c). No cyclic number may appear in any "
            "figure, table or caption.")
    if model not in SOURCES:
        raise ValueError(f"unknown motion model {model!r}; have {MODELS}")

    csv_name = SOURCES[model]
    path = os.path.join(DATA, csv_name)
    with open(path, newline="") as fh:
        reader = csv.DictReader(fh)
        # Both `dens` and `router_probes` are required for every row this
        # function builds (`dens` unconditionally, `router_probes` for the
        # frozen-mislabelled exclusion rule below) -- so this is checked once,
        # up front, rather than failing deep inside the row loop. Both are
        # withheld by the public release (CONFLICTS.md #1, #2): `dens` because
        # it carries the routing gate's ratio directly, `router_probes`
        # because releasing it would let a reader recover which cells the
        # exclusion rule drops. That makes every router number in this file
        # non-recomputable from the released artifact alone -- disclosed, not
        # silently patched over.
        columns.require_header(csv_name, reader.fieldnames or [],
                                "dens", "router_probes")
        raw = list(reader)
    seen = {r["churn_model"] for r in raw}
    assert seen == {model}, f"{path} carries {seen}, expected {{{model!r}}}"

    rows, dropped = [], []
    for r in raw:
        rho = float(r["rho"])
        probes = int(r["router_probes"])
        if rho > 0 and probes == 0 and not keep_phantom:
            dropped.append((r["matrix"], r["seed"], r["rho"]))
            continue
        rows.append(dict(
            model=model, matrix=r["matrix"], seed=r["seed"],
            N=int(r["N"]), nnz=int(r["nnz"]), rho=rho,
            dens=float(r["dens"]), dirty_cols=int(r["dirty_cols"]),
            csr=float(r["always_delta_baseline_ms"]), hst=float(r["always_hst_ms"]),
            oracle=float(r["oracle_ms"]), arm=r["oracle_arm"],
            oracle_vs_csr=float(r["oracle_vs_csr"]),
            router_steady=float(r["router_steady_ms"]),
            router_full=float(r["router_ms"]),
            router_arm=r["router_arm"], probes=probes,
            relerr=float(r["maxrelerr"]),
            pen_csr=float(r["misroute_cost_if_delta_baseline"]),
            pen_hst=float(r["misroute_cost_if_hst"]),
            # third arm, measured but never routed to
            p4=float(r["always_hst_patchable_ms"]),
            p4_vs_p3=float(r["patchable_vs_per_block"]),
            p4_vs_csr=float(r["patchable_vs_delta_baseline"]),
            oracle3_vs_oracle2=float(r["oracle3_vs_oracle2"]),
        ))
    DROPPED[model] = dropped
    return rows


def split(rows):
    """(frozen, churning). Callers that want both must say so and name it."""
    return ([r for r in rows if r["rho"] == 0.0],
            [r for r in rows if r["rho"] > 0.0])


def agrees(r):
    """Did the router commit to the arm hindsight says was faster?

    The two columns name their arms differently -- `router_arm` carries the
    arm's own name (`hst_p3` / `csr_delta`), `oracle_arm` the short form
    (`hst` / `csr`) -- so a raw string comparison scores every row a mis-route.
    """
    return r["router_arm"].split("_")[0] == r["arm"]


def rhos(rows):
    return sorted({r["rho"] for r in rows})


def per_operator(rows, f):
    """{matrix: [f(r) for its rows]} -- the grouping every CV and bootstrap uses."""
    d = {}
    for r in rows:
        d.setdefault(r["matrix"], []).append(f(r))
    return d


def provenance(model):
    return f"{SOURCES[model]} ({MODEL_LABEL[model]})"


if __name__ == "__main__":
    for m in MODELS:
        try:
            rows = load(m)
        except columns.ColumnUnavailable as e:
            print(f"{m:6s} {SOURCES[m]:26s} skipped: {e}")
            continue
        fr, ch = split(rows)
        print(f"{m:6s} {SOURCES[m]:26s} {len(rows):4d} rows "
              f"({len(fr)} frozen, {len(ch)} churning), "
              f"{len(DROPPED[m])} dropped as frozen-wearing-a-churn-label "
              f"{sorted(set(DROPPED[m]))}")
        print(f"       hindsight arm = block-scheduled: "
              f"{sum(1 for r in fr if r['arm'] == 'hst')}/{len(fr)} frozen, "
              f"{sum(1 for r in ch if r['arm'] == 'hst')}/{len(ch)} churning")
    try:
        load("cyclic")
    except ValueError as e:
        print(f"\ncyclic refused, as designed: {str(e)[:60]}...")
