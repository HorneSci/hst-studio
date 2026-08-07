"""Round-trip every golden-vector case: regenerate y from (A, x0, dx) and check.

    python3 tools/fetch_matrices.py --out matrices     # do this FIRST
    python3 tools/verify_cases.py --matrices matrices

A case whose operator `.mtx` is not on disk cannot be verified, only SKIPped.
With no matrices fetched every case skips, and a verifier that exits 0 having
verified nothing is worse than no verifier: it is an artifact whose whole job
is proving a correctness claim to a skeptic, handing that skeptic a green tick
for zero evidence. So the run also gates on HOW MANY cases were verified --
see `--require-verified` in main() for why the default is "all of them".

For each case this checks four things, in order of how much they would tell you
if they failed:

  1. SHA256SUMS matches the shipped files, and the operator's .mtx matches the
     sha256 the manifest pins. Without this the rest is checking the wrong bytes.
  2. The Python reference, driven only by what the manifest states, reproduces
     the shipped y0 and every step's y at the case's stated grade.
  3. A DIFFERENT legitimate summation order is run over the same case. On the
     integer cases it must still be bit-identical; on the f64 GRADE-A cases it
     must not be. That contrast is what makes the grades mean what they claim.
  4. The dx file round-trips through its own documented format.

Public domain (CC0 1.0).
"""

import argparse
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "reference"))
sys.path.insert(0, HERE)

import reference_spmv as ref                                    # noqa: E402
from altorder import spmv_row_order, spmv_delta_row_order, rel_l2, bit_diffs  # noqa: E402


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def verify(case_dir, mdir):
    man = json.load(open(os.path.join(case_dir, "manifest.json")))
    cid, grade, B = man["case_id"], man["grade"], man["batch"]
    op, rule = man["operator"], man["preprocessing"]["value_rule"]
    problems = []

    # ---- 1. bytes are what they claim to be -----------------------------
    for line in open(os.path.join(case_dir, "SHA256SUMS")):
        want, fn = line.split()
        if sha256_file(os.path.join(case_dir, fn)) != want:
            problems.append(f"SHA256SUMS mismatch on {fn}")
    mtx = os.path.join(mdir, f"{op['name']}.mtx")
    if not os.path.exists(mtx):
        # A missing operator means the round trip cannot run -- but the shipped
        # bytes were already checked above, and a SHA256SUMS mismatch is a real
        # failure whether or not the matrix is here. Dropping it on the way out
        # of the SKIP branch is the same vacuous-pass shape this file guards.
        if problems:
            return cid, "FAIL", "; ".join(problems), {}
        return cid, "SKIP", f"operator {op['name']}.mtx not present", {}
    if sha256_file(mtx) != op["mtx_sha256"]:
        problems.append("operator .mtx sha256 does not match the manifest")

    # ---- 2. the round trip ----------------------------------------------
    indptr, indices, values, N, M = ref.build_csc(mtx, rule)
    if (N, M, len(indices)) != (op["rows"], op["cols"], op["nnz_after_preprocessing"]):
        problems.append("operator shape/nnz disagrees with the manifest")
    y0, ysteps = ref.replay((indptr, indices, values, N, M), rule,
                            man["x0_generator"], man["x0_seed"],
                            os.path.join(case_dir, "dx.bin"), B)
    y0_ship = ref.read_f64(os.path.join(case_dir, "y0.f64.bin"))
    y_ship = ref.read_f64(os.path.join(case_dir, "y.f64.bin"))
    bd0, bd = bit_diffs(y0, y0_ship), bit_diffs(ysteps, y_ship)
    rel = rel_l2(ysteps, y_ship)
    bound = man["verification"]["rel_l2_bound"]
    if grade == "GRADE-A":
        if bd0 or bd:
            problems.append(f"GRADE-A but {bd0}+{bd} f64s differ from the shipped y")
    elif not (rel <= bound):
        problems.append(f"GRADE-B rel_l2 {rel:.3e} exceeds bound {bound:.3e}")

    # ---- 3. the strictness contrast --------------------------------------
    x0 = ref.gen_x0(man["x0_generator"], man["x0_seed"], M, B)
    ya = spmv_row_order(indptr, indices, values, x0, N, B)
    _s, _c, _b, sched = ref.read_dx(os.path.join(case_dir, "dx.bin"))
    alt = []
    for (dirty, dvals) in sched:
        spmv_delta_row_order(indptr, indices, values, dirty, dvals, ya, B)
        alt.extend(ya)
    alt_bits = bit_diffs(alt, y_ship)
    if man["verification"]["order_independent"] and alt_bits:
        problems.append(f"claims order-independent but {alt_bits} f64s moved")
    if not man["verification"]["order_independent"] and grade == "GRADE-A" and not alt_bits:
        problems.append("f64 GRADE-A case is not actually order-sensitive")

    # ---- 4. dx format round trip ------------------------------------------
    if _c != M or _b != B or _s != man["dx"]["steps"]:
        problems.append("dx.bin header disagrees with the manifest")
    if any(len(d) != man["dx"]["dirty_columns_per_step"] for d, _v in sched):
        problems.append("dx.bin dirty-column count disagrees with the manifest")
    if any(list(d) != sorted(d) or len(set(d)) != len(d) for d, _v in sched):
        problems.append("dx.bin dirty columns are not sorted+unique")

    detail = {"bitdiff_y0": bd0, "bitdiff_y": bd, "rel_l2": rel,
              "alt_order_bitdiff": alt_bits, "bound": bound}
    return cid, ("PASS" if not problems else "FAIL"), "; ".join(problems), detail


EXIT_OK = 0
EXIT_FAILING_CASES = 1
EXIT_NOT_ENOUGH_VERIFIED = 2

FETCH_HINT = ("run `python3 tools/fetch_matrices.py --out matrices` first, then "
              "re-run with `--matrices matrices`")


def _require_verified(value):
    """Parse --require-verified: a positive integer, or the literal `all`.

    The default is `all`, not 1. One verified case out of twelve is still a
    green tick over eleven unproven ones, and the whole point of this artifact
    is that the twelve cases cover DIFFERENT things -- integer vs f64, order-
    independent vs order-sensitive. A partial fetch proves a partial claim, so
    it has to be asked for explicitly (`--require-verified 3`), never inherited
    from a default. `--require-verified 0` is rejected rather than treated as
    "off": an opt-out that turns the guard into the exact behaviour the guard
    exists to prevent is not a knob worth having.
    """
    if str(value).strip().lower() == "all":
        return "all"
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError(
            f"--require-verified takes a positive integer or 'all', got {value!r}")
    if n < 1:
        raise argparse.ArgumentTypeError(
            f"--require-verified must be >= 1, got {n}: a run that verified nothing "
            "is what this flag exists to fail")
    return n


def main():
    ap = argparse.ArgumentParser(
        description="Round-trip every golden-vector case and gate the exit code on it.")
    ap.add_argument("--matrices", required=True,
                    help="directory of fetched .mtx operators (tools/fetch_matrices.py --out)")
    ap.add_argument("--cases", default=os.path.join(HERE, "..", "cases"))
    ap.add_argument("--require-verified", type=_require_verified, default="all",
                    metavar="N|all",
                    help="how many cases must actually be verified, not skipped "
                         "(default: all)")
    a = ap.parse_args()

    if not os.path.isdir(a.matrices):
        print(f"verify_cases: --matrices {a.matrices!r} is not a directory, so no "
              f"operator can be loaded and no case can be verified.\n"
              f"  Fix: {FETCH_HINT}.", file=sys.stderr)
        return EXIT_NOT_ENOUGH_VERIFIED

    ids = sorted(d for d in os.listdir(a.cases)
                 if os.path.isdir(os.path.join(a.cases, d)))
    if not ids:
        print(f"verify_cases: no case directories under {a.cases!r}. A verifier with "
              f"an empty case list reports success without checking anything.",
              file=sys.stderr)
        return EXIT_NOT_ENOUGH_VERIFIED

    nfail = nskip = 0
    skipped = []
    print(f"{'case':8} {'result':7} {'y0 bitdiff':>11} {'y bitdiff':>10} "
          f"{'rel_l2':>10} {'bound':>10} {'alt-order bitdiff':>18}  notes")
    for cid in ids:
        c, res, note, d = verify(os.path.join(a.cases, cid), a.matrices)
        nfail += (res == "FAIL")
        if res == "SKIP":
            nskip += 1
            skipped.append(c)
        if d:
            print(f"{c:8} {res:7} {d['bitdiff_y0']:>11} {d['bitdiff_y']:>10} "
                  f"{d['rel_l2']:>10.3e} {d['bound']:>10.3e} "
                  f"{d['alt_order_bitdiff']:>18}  {note}")
        else:
            print(f"{c:8} {res:7} {'-':>11} {'-':>10} {'-':>10} {'-':>10} "
                  f"{'-':>18}  {note}")

    total = len(ids)
    nverified = total - nskip
    # The summary NEVER reads "0 failing" on its own. Verified and skipped are
    # different words in it, because a skip and a pass were indistinguishable
    # in the old line and that is precisely how a run of twelve skips read as
    # a clean bill of health.
    print(f"\n{nverified} of {total} verified, {nskip} skipped, {nfail} failing")

    want = total if a.require_verified == "all" else a.require_verified
    if nfail:
        return EXIT_FAILING_CASES
    if nverified < want:
        how = "all cases" if a.require_verified == "all" else f"{want} case(s)"
        # Only offer the partial-evidence escape when there IS partial evidence.
        # `--require-verified 0` is rejected, so pointing at it when nothing
        # verified would be pointing at a flag that does not exist.
        partial = (f"\n  To accept partial evidence on purpose, say so: "
                   f"--require-verified {nverified}." if nverified else "")
        print(f"\nNOT ENOUGH VERIFIED: {nverified} case(s) verified, but "
              f"--require-verified asks for {how}.\n"
              f"  Skipped: {', '.join(skipped)}\n"
              f"  A case is skipped when its operator .mtx is not on disk, so this is "
              f"almost always a missing fetch.\n"
              f"  Fix: {FETCH_HINT}." + partial, file=sys.stderr)
        return EXIT_NOT_ENOUGH_VERIFIED
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
