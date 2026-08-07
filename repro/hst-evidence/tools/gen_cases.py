"""Generate the golden-vector cases named by a manifest.

    python3 tools/gen_cases.py --manifest cases.public.json --matrices DIR

The manifest decides everything: which cases exist, which operators they use,
which grade they carry, which are adversarial. A private superset is a second
manifest against this same generator. There is no case list in this file.

Two things here are load-bearing and deliberate:

  * ALLOWED_KEYS below is an ALLOWLIST. A field can only reach a shipped
    manifest if it is named here. Denylisting fields does not work: the subtle
    disclosure is data, not identifiers -- a triple of per-arm work counts has
    no forbidden word in it and still pins an internal layout by its ratios.

  * The GRADE-B bound is calibrated, not chosen. It is the disagreement between
    two legitimate summation orders on that case, times a margin.

Public domain (CC0 1.0).
"""

import argparse
import hashlib
import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "reference"))
sys.path.insert(0, HERE)

import reference_spmv as ref                                   # noqa: E402
from altorder import spmv_row_order, spmv_delta_row_order, rel_l2, bit_diffs  # noqa: E402
from fetch_matrices import MATRICES, BASE, sha256_file         # noqa: E402

TWO_53 = 1 << 53
BOUND_MARGIN = 10.0
BOUND_FLOOR = 1e-12

# --------------------------------------------------------------------------
# THE COLUMN ALLOWLIST. Nothing else may appear in a shipped case manifest.
# --------------------------------------------------------------------------
ALLOWED_KEYS = {
    "schema", "case_id", "grade", "precision", "batch", "adversarial", "why",
    "operator", "source", "group", "name", "url", "mtx_sha256",
    "matrix_market_field", "matrix_market_symmetry", "rows", "cols",
    "nnz_after_preprocessing",
    "preprocessing", "value_rule", "description", "duplicate_coordinates",
    "x0_generator", "x0_seed", "x0_description",
    "dx", "file", "generator", "seed", "steps", "motion", "drift_rho",
    "dirty_fraction", "dirty_columns_per_step", "value_domain", "format",
    "reference", "summation_order", "implementations",
    "verification", "rel_l2_bound", "order_independent", "exactness_argument",
    "max_abs_accumulator", "exactly_representable_below",
    "observed_rel_l2_between_orders", "observed_bit_differences_between_orders",
    "outputs", "shape", "dtype", "sha256",
}


# The keys under "outputs" are filenames, not fields -- allowlisted separately.
ALLOWED_OUTPUT_FILES = {"dx.bin", "y0.f64.bin", "y.f64.bin"}


def check_allowlist(obj, path="$", in_outputs=False):
    if isinstance(obj, dict):
        for k, v in obj.items():
            allowed = ALLOWED_OUTPUT_FILES if in_outputs else ALLOWED_KEYS
            if k not in allowed:
                raise SystemExit(f"FIELD NOT ON ALLOWLIST: {path}.{k}")
            check_allowlist(v, f"{path}.{k}", in_outputs=(k == "outputs"))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            check_allowlist(v, f"{path}[{i}]", in_outputs)


# --------------------------------------------------------------------------
# dx_v1 -- the published delta-schedule generator.
# --------------------------------------------------------------------------
DX_SPEC = (
    "dx_v1: rng = SplitMix64(seed). k = max(1, round(dirty_fraction * cols)). "
    "A column set is drawn by repeatedly taking rng.next() mod cols and "
    "rejecting repeats, then sorting ascending. Step 0 draws such a set. "
    "motion=frozen keeps it; motion=scattered draws a fresh set every step; "
    "motion=drift replaces the r = max(1, round(drift_rho * k)) lowest-indexed "
    "members with freshly drawn columns not already retained, then re-sorts. "
    "Values are emitted per (position in the dirty set, batch lane), position "
    "major."
)


def draw_set(rng, cols, k, exclude=()):
    seen, out = set(exclude), []
    while len(out) < k:
        c = rng.next() % cols
        if c not in seen:
            seen.add(c)
            out.append(c)
    return sorted(out)


def gen_dx(seed, cols, batch, steps, motion, dirty_fraction, drift_rho, integer):
    rng = ref.SplitMix64(seed)
    k = max(1, round(dirty_fraction * cols))
    dirty = draw_set(rng, cols, k)
    sched = []
    for s in range(steps):
        if s > 0:
            if motion == "scattered":
                dirty = draw_set(rng, cols, k)
            elif motion == "drift":
                r = max(1, round(drift_rho * k))
                keep = dirty[r:]
                dirty = sorted(keep + draw_set(rng, cols, r, exclude=keep))
            # motion == "frozen": unchanged
        vals = [float((rng.next() % 9) - 4) if integer else rng.signed()
                for _ in range(k * batch)]
        sched.append((list(dirty), vals))
    return k, sched


def write_dx(path, cols, batch, sched):
    with open(path, "wb") as f:
        f.write(ref.DX_MAGIC)
        f.write(struct.pack("<6I", 1, len(sched), cols, batch, 0, 0))
        for (dirty, vals) in sched:
            f.write(struct.pack("<I", len(dirty)))
            f.write(struct.pack(f"<{len(dirty)}I", *dirty))
            f.write(struct.pack(f"<{len(vals)}d", *vals))


# --------------------------------------------------------------------------

def build_case(spec, defaults, mdir, outroot):
    cid = spec["id"]
    op = spec["operator"]
    group, fname, _why = MATRICES[op]
    mtx = os.path.join(mdir, f"{fname}.mtx")
    steps = spec.get("steps", defaults["steps"])
    rho = spec.get("drift_rho", defaults["drift_rho"])
    B = spec["batch"]
    rule = spec["value_rule"]
    integer = rule == "pattern_int_v1"

    n_rows, n_cols, _e, sym = ref.read_mm(mtx)
    with open(mtx) as f:
        field = f.readline().split()[3].lower()
    indptr, indices, values, N, M = ref.build_csc(mtx, rule)
    csc = (indptr, indices, values, N, M)

    k, sched = gen_dx(spec["dx_seed"], M, B, steps, spec["motion"],
                      spec["dirty_fraction"], rho, integer)

    d = os.path.join(outroot, cid)
    os.makedirs(d, exist_ok=True)
    write_dx(os.path.join(d, "dx.bin"), M, B, sched)

    # ---- the shipped answer, in the stated CSC order --------------------
    y0, ysteps = ref.replay(csc, rule, spec["x0_generator"], spec["x0_seed"],
                            os.path.join(d, "dx.bin"), B)
    ref.write_f64(os.path.join(d, "y0.f64.bin"), y0)
    ref.write_f64(os.path.join(d, "y.f64.bin"), ysteps)

    # ---- the same answer in a DIFFERENT legitimate order ----------------
    x0 = ref.gen_x0(spec["x0_generator"], spec["x0_seed"], M, B)
    ya = spmv_row_order(indptr, indices, values, x0, N, B)
    alt = []
    for (dirty, dvals) in sched:
        spmv_delta_row_order(indptr, indices, values, dirty, dvals, ya, B)
        alt.extend(ya)
    obs_rel = rel_l2(alt, ysteps)
    obs_bits = bit_diffs(alt, ysteps)

    # ---- grade and bound ------------------------------------------------
    if integer:
        rowsum = [0.0] * N
        for kk in range(len(values)):
            rowsum[indices[kk]] += abs(values[kk])
        max_row = max(rowsum) if rowsum else 0.0
        acc_bound = max_row * (9 + steps * 4)
        if acc_bound >= TWO_53:
            raise SystemExit(f"{cid}: integer accumulator bound {acc_bound} >= 2^53")
        if obs_bits != 0:
            raise SystemExit(f"{cid}: integer case differed between orders "
                             f"({obs_bits} f64s) -- exactness argument is broken")
        bound, exact_arg = 0.0, (
            "Every A[i,j] is an integer in 1..5 and every x0/dx entry is an "
            "integer, so every partial sum is an integer. The largest "
            "accumulator any order can reach is max_i sum_j |A[i,j]| * "
            "(max|x0| + steps * max|dx|), reported below; it is under 2^53, so "
            "every partial sum is exactly representable in f64 and no addition "
            "rounds. Bit-equality therefore holds regardless of summation "
            "order, compiler, or vectorization. This is the one grade in the "
            "set that a correct implementation cannot fail for a benign reason.")
    else:
        acc_bound = None
        if spec["grade"] == "GRADE-A":
            bound, exact_arg = 0.0, (
                "Byte-identical, and achievable ONLY because the summation "
                "order is specified. A correct implementation that sums in a "
                "different order will fail this case -- see the measured "
                "disagreement with a row-major order recorded below. GRADE-A "
                "on an f64 case is a strictness test, not a correctness test.")
        else:
            bound = max(BOUND_FLOOR, obs_rel * BOUND_MARGIN)
            exact_arg = (
                "Tolerance grade. The bound is calibrated, not chosen: it is "
                f"{BOUND_MARGIN:g}x the measured rel_l2 between two legitimate "
                "summation orders (CSC and row-major) on this exact case, "
                f"floored at {BOUND_FLOOR:g}. Any implementation whose result "
                "lands inside it agrees with the reference to within the "
                "spread that reordering alone produces.")

    man = {
        "schema": "hst-evidence/case-v1",
        "case_id": cid,
        "grade": spec["grade"],
        "precision": "f64",
        "batch": B,
        "adversarial": bool(spec.get("adversarial", False)),
        "why": spec["why"],
        "operator": {
            "source": "suitesparse",
            "group": group,
            "name": fname,
            "url": f"{BASE}/{group}/{fname}.tar.gz",
            "mtx_sha256": sha256_file(mtx),
            "matrix_market_field": field,
            "matrix_market_symmetry": "symmetric" if sym else "general",
            "rows": N,
            "cols": M,
            "nnz_after_preprocessing": len(indices),
        },
        "preprocessing": {
            "value_rule": rule,
            "description": (
                "A `symmetric` Matrix Market file stores one triangle: each "
                "off-diagonal (i,j) contributes both (i,j) and (j,i); a "
                "diagonal entry contributes once. " + (
                    "Stored values are then DISCARDED and replaced by "
                    "A[i,j] = 1 + ((i + 3j) mod 5) with i,j zero-based, giving "
                    "exact small integers in 1..5."
                    if integer else
                    "Stored values are used as-is; a `pattern` file gives 1.0.")),
            "duplicate_coordinates": "none present; asserted at generation time",
        },
        "x0_generator": spec["x0_generator"],
        "x0_seed": spec["x0_seed"],
        "x0_description": (
            "x0[j][b] = 1 + ((j + 7b) mod 9), zero-based -- integers 1..9"
            if spec["x0_generator"] == "x0_int_v1" else
            "x0[j][b] = 2u-1 where u = (SplitMix64(x0_seed).next() >> 11) * 2^-53, "
            "drawn in j-major then b order"),
        "dx": {
            "file": "dx.bin",
            "generator": defaults["dx_generator"],
            "seed": spec["dx_seed"],
            "steps": steps,
            "motion": spec["motion"],
            "drift_rho": rho if spec["motion"] == "drift" else None,
            "dirty_fraction": spec["dirty_fraction"],
            "dirty_columns_per_step": k,
            "value_domain": ("integers in [-4,4]" if integer else "f64 in [-1,1)"),
            "format": "GVDX0001, little-endian; layout documented in README.md",
            "description": DX_SPEC,
        },
        "reference": {
            "summation_order": (
                "CSC. Columns ascending; within a column, row indices "
                "ascending; y[i*B+b] += A[i,j] * x[j*B+b] applied in exactly "
                "that sequence, with b ascending innermost. The delta apply "
                "uses the same order restricted to the dirty columns, taken "
                "ascending, and accumulates into the running y."),
            "implementations": ["reference/reference_spmv.py",
                                "reference/reference_spmv.c"],
        },
        "verification": {
            "rel_l2_bound": bound,
            "order_independent": bool(integer),
            "exactness_argument": exact_arg,
            "max_abs_accumulator": acc_bound,
            "exactly_representable_below": TWO_53 if integer else None,
            "observed_rel_l2_between_orders": obs_rel,
            "observed_bit_differences_between_orders": obs_bits,
        },
        "outputs": {
            "dx.bin": {"sha256": None},
            "y0.f64.bin": {"shape": [N, B], "dtype": "<f8", "sha256": None},
            "y.f64.bin": {"shape": [steps, N, B], "dtype": "<f8", "sha256": None},
        },
    }
    for fn in man["outputs"]:
        man["outputs"][fn]["sha256"] = sha256_file(os.path.join(d, fn))

    check_allowlist(man)
    with open(os.path.join(d, "manifest.json"), "w") as f:
        json.dump(man, f, indent=2)
        f.write("\n")

    with open(os.path.join(d, "SHA256SUMS"), "w") as f:
        for fn in ("dx.bin", "y0.f64.bin", "y.f64.bin", "manifest.json"):
            f.write(f"{sha256_file(os.path.join(d, fn))}  {fn}\n")

    return {"case_id": cid, "grade": spec["grade"], "name": fname, "rows": N,
            "cols": M, "nnz_after_preprocessing": len(indices), "batch": B,
            "motion": spec["motion"], "dirty_fraction": spec["dirty_fraction"],
            "steps": steps, "rel_l2_bound": bound,
            "observed_rel_l2_between_orders": obs_rel,
            "observed_bit_differences_between_orders": obs_bits,
            "adversarial": bool(spec.get("adversarial", False))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default=os.path.join(HERE, "..", "cases.public.json"))
    ap.add_argument("--matrices", required=True)
    ap.add_argument("--out", default=os.path.join(HERE, "..", "cases"))
    ap.add_argument("--only", nargs="*")
    a = ap.parse_args()
    m = json.load(open(a.manifest))
    print(f"# manifest variant: {m['variant']}   cases: {len(m['cases'])}")
    rows = []
    for spec in m["cases"]:
        if a.only and spec["id"] not in a.only:
            continue
        r = build_case(spec, m["defaults"], a.matrices, a.out)
        rows.append(r)
        print(f"  {r['case_id']:7} {r['grade']:8} {r['name']:10} "
              f"nnz={r['nnz_after_preprocessing']:<8} B={r['batch']} {r['motion']:10} "
              f"dirty={r['dirty_fraction']:<5} bound={r['rel_l2_bound']:.3e} "
              f"alt_order_rel={r['observed_rel_l2_between_orders']:.3e} "
              f"alt_order_bitdiff={r['observed_bit_differences_between_orders']}")
    check_allowlist(rows)
    json.dump(rows, open(os.path.join(a.out, "INDEX.json"), "w"), indent=2)
    print(f"# wrote {len(rows)} cases to {a.out}")


if __name__ == "__main__":
    main()
