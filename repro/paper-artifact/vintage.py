"""Which committed CSV is stale, in which columns, and why -- as data.

The vintage of a result file used to live in prose: a table in
`learn/pytorch_fit/CLAUDE.md` saying `family.csv` predates the 2026-07-31
session-path fixes. Prose does not reach a script. Four consumers read that
file as if it were current --

    analyze_family.py       --csv default
    analyze_toolchain.py    --gcc default
    paper/figures.py:913    unconditional
    paper/paper_numbers.py  `_fam()`, unconditional

-- while `compare_prep_gap.py`, the one place that is *supposed* to read it,
treats it correctly as the pre-fix arm of a before/after.

Staleness is per COLUMN, not per file
-------------------------------------
This is the whole reason a manifest earns its place over a blanket rule.
`family.csv`'s preparation timings are stale; its row-touch counts are not,
because they are integers read off a built schedule and no timing fix can
move them. Rejecting the file outright would throw away valid structural
evidence and would be wrong in the other direction.

So a read declares the columns it wants, and only a stale one is refused.

Refusing is the default, and opting in is explicit
--------------------------------------------------
`read(..., accept_stale="reason")` is how a caller says it means it. That turns
a silent stale read into a declared one that a reader can see and a reviewer can
challenge, which is the property prose could never give.

Absence from the manifest is not evidence of currency
-----------------------------------------------------
Added 2026-08-01. The first version of this module checked `MANIFEST.get(name)`
and, finding nothing, let the read through. So a file nobody had assessed was
indistinguishable from a file assessed and found current -- and the manifest
covered 4 files while the canonical claims read 8. The two CSVs behind the
*entire* canonical envelope and the whole router table, `seeds_drift_pooled.csv`
and `seeds_jump_pooled.csv`, were among the unassessed.

That is the same failure this module was written to end, one level up: prose
that does not reach a script became a manifest that does not reach a file.

So an unregistered file is now refused too, whenever the caller declares a
column that could carry a timing. `accept_unregistered="reason"` opts out, in
the same shape as `accept_stale`. The asymmetry is deliberate: structural
columns (counts, ratios of counts, seeds, rho) read from an unregistered file
without complaint, because no timing fix can move them.

--- vendored into oss/paper-artifact 2026-08-05 ---
Verbatim copy of `learn/pytorch_fit/vintage.py`. This module is a generic,
stdlib-only vintage-tracking seam with no kernel content; it is imported by
`paper/paper_numbers.py` and `paper/figures.py`, which `sys.path.insert(0,
ROOT)` to the artifact root expecting to find it here. Its `MANIFEST` names
internal CSV filenames and internal-vocabulary column names that never
shipped in this release's `data/` (e.g. `family_pysess_2026-07-31.csv`,
`bs_tile_vs_csr`) -- those are documentation of *why a working-copy file is
stale*, already disclosed by `ERRATA.md` and `CONFLICTS.md` in this same
artifact, not new disclosure. `MANIFEST.read()` is called here only with
`directory=` pointed at the released `data/`, so it is checked against the
one released file it is actually used for (`family.csv`) and its stale-column
list is a superset that simply never matches on the columns that release
already dropped. Edit the source of truth in `learn/pytorch_fit/vintage.py`,
not this copy.
"""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass, field

HERE = os.path.dirname(os.path.abspath(__file__))


@dataclass(frozen=True)
class Vintage:
    """What a result file measured, and which of its columns no longer hold."""

    file: str
    measured: str                       # ISO date/time the run produced it
    note: str                           # what changed under it, in one line
    stale_columns: frozenset[str] = field(default_factory=frozenset)
    superseded_by: tuple[str, ...] = ()

    def stale(self, columns) -> list[str]:
        return sorted(set(columns) & self.stale_columns)


#: Timing columns invalidated by the 2026-07-31 session-path fixes (ISSUES #055):
#: two PyTorch dispatcher hops per re-preparation, a std::map tile cache, and
#: Python session construction. Every ratio derived from these moves with them.
#: `merge_ratio`, `dens`, `csr_rebuilds`, `rho`, `seed` are counts or structure
#: and are unaffected -- the row-touch identity in this file still holds.
_PREP_TIMINGS = frozenset({
    "p3_ms", "p3_exec_ms", "bs_tile_ms", "bs_tile_exec_ms",
    "bs_merge_ms", "bs_merge_exec_ms", "csr_ms", "hst_ms",
    "p3_vs_csr", "bs_tile_vs_csr", "p3_vs_bs_tile", "bs_merge_vs_bs_tile",
})

#: The P4 churn/router harness names its lanes differently from the family sweep.
#: Same defect underneath: every HST lane paid an M*B scratch zero-fill no baseline
#: paid, so every ratio with an HST lane on either side moved when it was pooled.
_P4_TIMINGS = frozenset({
    "hst_mean_ms", "hst_median_ms", "hst_exec_mean_ms", "hst_pre_mean_ms",
    "p3_mean_ms", "p3_exec_mean_ms", "p3_pre_mean_ms", "p3mt_mean_ms",
    "p4_mean_ms", "p4_exec_mean_ms", "p4_splice_mean_ms",
    "csc_mean_ms", "csr_mean_ms", "sup_mean_ms",
    "hst_vs_csc", "p3_vs_csc", "p3_vs_csr", "p2_vs_csr", "p3_vs_sup",
    "p3mt_vs_p3", "p3mt_vs_sup", "p3_vs_p2",
    "p4_vs_p3", "p4_vs_p2", "p4_vs_csr", "p4_vs_csc",
    "p4_vs_p3_nokey", "p4_vs_p2_nokey",
    "p4_exec_vs_p2_exec", "p4_exec_vs_p3_exec",
    "always_csr_ms", "always_hst_ms", "always_hst_p4_ms",
    "router_ms", "router_steady_ms", "oracle_ms", "router_tax_ms",
    "router_vs_csr", "oracle_vs_csr", "router_vs_oracle",
    "router_steady_vs_csr", "router_steady_vs_oracle", "p4_vs_p3", "p4_vs_csr",
})

#: Any column that could carry a timing, across every harness in this directory.
#: Used only to decide whether an UNREGISTERED file needs assessing before it is
#: read -- structural columns (counts, seeds, rho, ratios of counts) do not.
_TIMING_SENSITIVE = _PREP_TIMINGS | _P4_TIMINGS

MANIFEST: dict[str, Vintage] = {
    "family.csv": Vintage(
        file="family.csv",
        measured="2026-07-31T04:57",
        note="pre-fix: predates the session-path fixes that landed later the "
             "same day (ISSUES #055). Preparation timings are stale; the "
             "row-touch counts are not.",
        stale_columns=_PREP_TIMINGS,
        superseded_by=("family_postfix_2026-07-31.csv",
                       "family_pysess_2026-07-31.csv"),
    ),
    "family_clang.csv": Vintage(
        file="family_clang.csv",
        measured="2026-07-31",
        note="the clang arm of the same pre-fix sweep as family.csv, on a "
             "subset of its cells. Paired against family.csv the fixes move "
             "both sides and cancel; its levels alone carry the same staleness.",
        stale_columns=_PREP_TIMINGS,
        superseded_by=(),
    ),
    "family_postfix_2026-07-31.csv": Vintage(
        file="family_postfix_2026-07-31.csv",
        measured="2026-07-31",
        note="after the dispatcher and tile-cache fixes.",
    ),
    "family_pysess_2026-07-31.csv": Vintage(
        file="family_pysess_2026-07-31.csv",
        measured="2026-07-31",
        note="after the Python wrapper guard -- the current vintage.",
    ),

    # --- added 2026-08-01: files the canonical claims read but nobody had assessed ---

    # These two back the canonical envelope (6.94x->4.75x drift, 2.93x->1.36x
    # jump) AND the whole router table. They are POST-pooling: the M*B scratch
    # pooling landed 2026-07-30 and these were committed at 10:19 that day,
    # alongside the other *_pooled files.
    #
    # ASSESSED against the 2026-07-31 session-path fixes (#055) on 2026-08-04
    # via a same-cells subset A/B on the current build (issue #15 part 1;
    # SEEDS_AB_FINDINGS_2026-08-04.md, seeds_ab_{drift,jump}_2026-08-04.csv):
    # the baseline lane is unchanged (+/-1% median) and the HST lane is
    # FASTER -- 7-18% under drift churn, more under jump, growing with rho,
    # which is the #055 signature (the removed cost was paid per rebuild).
    # These files therefore UNDERSTATE HST's churn cells on the current build
    # and stay as the quoted, conservative tables pending a full 21-operator
    # re-sweep.
    "seeds_drift_pooled.csv": Vintage(
        file="seeds_drift_pooled.csv",
        measured="2026-07-30T10:19",
        note="post-pooling. Backs the canonical drift envelope and the router "
             "table. Assessed against #055 on 2026-08-04 (subset A/B, "
             "SEEDS_AB_FINDINGS_2026-08-04.md): baseline lane unchanged, HST "
             "lane 7-18% faster under churn on the current build -- this file "
             "understates HST's churn cells and is kept as the conservative "
             "quoted table pending a full 21-operator re-sweep.",
    ),
    "seeds_jump_pooled.csv": Vintage(
        file="seeds_jump_pooled.csv",
        measured="2026-07-30T10:19",
        note="post-pooling. Backs the canonical jump envelope and the router "
             "table. Assessed against #055 on 2026-08-04, as "
             "seeds_drift_pooled.csv -- movement 1.19-1.41x in HST's favour "
             "under jump churn; understates, kept as quoted.",
    ),

    # The paired generator sweep. Committed 01:06 on 2026-07-31 -- i.e. BEFORE
    # the ~19:00 session-path fixes, same pre-fix vintage as family.csv.
    # The finding they carry is a RATIO BETWEEN the two files, and the fixes
    # move both sides, so the 1.41-1.83x nnz-matched effect survives; the
    # per-file levels do not.
    "family_jump_plain.csv": Vintage(
        file="family_jump_plain.csv",
        measured="2026-07-31T01:06",
        note="pre-fix (#055), same vintage as family.csv. Paired against "
             "family_jump_nnz.csv the fixes move both sides and cancel, so the "
             "generator effect holds; its levels alone are stale.",
        stale_columns=_PREP_TIMINGS,
    ),
    "family_jump_nnz.csv": Vintage(
        file="family_jump_nnz.csv",
        measured="2026-07-31T01:06",
        note="pre-fix (#055), the nnz-matched arm of the pair above. Same "
             "pairing argument applies.",
        stale_columns=_PREP_TIMINGS,
    ),

    # Registered 2026-08-04 (#18 item 13): every file below backs a number
    # quoted in the estate and bound by a tests/ derive module, and consumed
    # its rows unregistered until today. Registration order follows the
    # binding modules, not importance.
    "family_key_fast.csv": Vintage(
        file="family_key_fast.csv",
        measured="2026-07-31T01:10",
        note="pre-fix (#055), same vintage as family.csv. Backs the key-tax "
             "control tables (KEY_TAX_FINDINGS_2026-07-31.md, bound by "
             "tests/test_key_tax_numbers.py). Paired against "
             "family_key_python.csv the fixes move both sides and cancel; "
             "levels alone are stale.",
        stale_columns=_PREP_TIMINGS,
    ),
    "family_key_python.csv": Vintage(
        file="family_key_python.csv",
        measured="2026-07-31T01:10",
        note="pre-fix (#055), the python-key arm of the pair above. Same "
             "pairing argument.",
        stale_columns=_PREP_TIMINGS,
    ),
    "frozen_k64.csv": Vintage(
        file="frozen_k64.csv",
        measured="2026-07-31T03:06",
        note="pre-fix (#055). All cells rho=0 frozen, where the removed "
             "session cost (paid per rebuild) was paid ~once per run, so "
             "exposure is minimal -- stated, not assumed zero. Backs the "
             "frozen-gap super-linearity (FROZEN_GAP_FINDINGS_2026-07-31.md, "
             "tests/test_frozen_gap_numbers.py).",
        stale_columns=_PREP_TIMINGS,
    ),
    "frozen_k256.csv": Vintage(
        file="frozen_k256.csv",
        measured="2026-07-31T03:06",
        note="as frozen_k64.csv, |D|=256 rung.",
        stale_columns=_PREP_TIMINGS,
    ),
    "frozen_k1024.csv": Vintage(
        file="frozen_k1024.csv",
        measured="2026-07-31T03:06",
        note="as frozen_k64.csv, |D|=1024 rung. TSOPF_RS_b39_c30 saturates "
             "below nominal |D| here (dirty_cols 138-1024) -- the one "
             "saturating operator, asserted by the binding test.",
        stale_columns=_PREP_TIMINGS,
    ),
    "real_trace.csv": Vintage(
        file="real_trace.csv",
        measured="2026-07-31T00:17",
        note="structural: alpha/rho trajectories read off real solves, no "
             "timing column, so #055 does not touch it. Backs the seventh "
             "screening question's numbers (REAL_SOLVER_FINDINGS_2026-07-31."
             "md, tests/test_real_solver_numbers.py).",
    ),
    "torch_native_t8.csv": Vintage(
        file="torch_native_t8.csv",
        measured="2026-07-28T00:29",
        note="pre-fix (#055) by three days. Backs CONTRIBUTION §4a's "
             "9.5x/16.7x/25.5x native-torch figures "
             "(tests/test_native_torch_numbers.py); its timing levels carry "
             "the old session path.",
        stale_columns=frozenset({
            "hst_ms", "hst_res_ms", "csc_ms", "full_ms", "slice_ms",
            "presliced_ms", "sched_ms",
        }),
    ),
    "session_tax_pooled.csv": Vintage(
        file="session_tax_pooled.csv",
        measured="2026-07-30T10:19",
        note="pre-fix BY DESIGN: it measures the session tax #055 later "
             "removed, and is the correction input analyze_p4 applies to "
             "same-vintage P4 rows (tests/test_p4_numbers.py). Do not apply "
             "its tax to post-fix rows -- the tax it measures no longer "
             "exists there.",
        stale_columns=frozenset({
            "p2_wall_ms", "p2_build_ms", "p2_tax_ms",
            "p3_wall_ms", "p3_build_ms", "p3_tax_ms",
            "p4_wall_ms", "p4_build_ms", "p4_tax_ms", "tax_ms",
        }),
    ),
    "seeds_ab_drift_2026-08-04.csv": Vintage(
        file="seeds_ab_drift_2026-08-04.csv",
        measured="2026-08-04",
        note="CURRENT build (post-#055): the drift half of the #15 subset "
             "A/B against seeds_drift_pooled.csv "
             "(SEEDS_AB_FINDINGS_2026-08-04.md). 5 operators x 2 seeds -- "
             "an assessment instrument, not an envelope; do not quote its "
             "cells as the envelope.",
    ),
    "seeds_ab_jump_2026-08-04.csv": Vintage(
        file="seeds_ab_jump_2026-08-04.csv",
        measured="2026-08-04",
        note="CURRENT build (post-#055): the jump half of the #15 subset "
             "A/B. Same scope caveat as the drift half.",
    ),

    # ⚠️ NOT the CSV behind the canonical one-shot number, despite the name.
    # The canonical "0.30x geomean, wins 5/18" comes from a stdout log
    # (learn/results/hst_bench_profile2_results_2026-07-18.txt), because
    # hst_bench_profile2.cpp only printf()s -- there is no CSV for it. This file
    # is a different harness, corpus and B set: 9 rows over 3 patterns, geomean
    # 0.393x, winning 0/9. Registered so that anyone grepping for the one-shot
    # CSV lands on this note instead of on a number that looks like a
    # correction and is not.
    "results_oneshot.csv": Vintage(
        file="results_oneshot.csv",
        measured="2026-07-27",
        note="NOT the canonical one-shot result. 9 rows, 3 patterns, geomean "
             "0.393x on ratio_oneshot_vs_csc (0.432x on p2_oneshot_vs_csc), "
             "winning 0/9 -- a different harness from the 0.30x (5/18) "
             "quoted estate-wide, which has no CSV and lives in "
             "learn/results/hst_bench_profile2_results_2026-07-18.txt.",
    ),

    # PRE-POOLING P4 files. This is the sign-flipping case and the reason
    # unregistered-means-unknown had to stop being a silent pass: read the
    # pre-pool file and P4 looks AHEAD (1.095x, winning 38/60); read the pooled
    # one and it is behind (0.788x). Same cells, opposite conclusion.
    # analyze_p4.py's docstring warns about this; nothing enforced it.
    **{
        name: Vintage(
            file=name,
            measured="2026-07-30T03:05",
            note="PRE-POOLING. Every HST lane here still pays the M*B scratch "
                 "zero-fill that no baseline pays (up to 10.44 MB, a median "
                 "18-21% of P3's per-step time). Inflated AGAINST HST, and it "
                 "flips P4's verdict: 1.095x here against 0.788x pooled.",
            stale_columns=_P4_TIMINGS,
            superseded_by=(name.replace(".csv", "_pooled.csv"),),
        )
        for name in ("p4_churn_drift.csv", "p4_churn_jump.csv", "p4_router.csv")
    },

    # The pooled counterparts. Same caveat as seeds_*_pooled.csv: post-pooling,
    # but UNASSESSED against #055, which postdates them by a day.
    **{
        name: Vintage(
            file=name,
            measured="2026-07-30T10:19",
            note="post-pooling counterpart of "
                 f"{name.replace('_pooled.csv', '.csv')}. UNASSESSED against "
                 "the 2026-07-31 session-path fixes (#055), which postdate it.",
        )
        for name in ("p4_churn_drift_pooled.csv", "p4_churn_jump_pooled.csv",
                     "p4_router_pooled.csv")
    },
}


class StaleColumnError(RuntimeError):
    """A stale column was read without an explicit acknowledgement."""


class UnregisteredFileError(RuntimeError):
    """A timing was read from a file whose vintage nobody has assessed.

    Distinct from `StaleColumnError`: that one means "we looked and it is old",
    this one means "nobody looked". Conflating them is how the manifest came to
    cover 4 files while the canonical claims read 8.
    """


def read(name: str, *, columns=None, accept_stale: str | None = None,
         accept_unregistered: str | None = None,
         directory: str | None = None) -> list[dict]:
    """Read a committed result CSV, refusing stale columns by default.

    `columns` is what the caller intends to use. Passing it is what makes the
    check possible -- a read that declares nothing cannot be checked, and is
    allowed through unexamined rather than guessed at.

    `accept_stale` is a REASON, not a flag, and it is recorded at the call site.
    "this is the pre-fix arm of the before/after" is a good one.

    `accept_unregistered` is the same shape, for a file with no manifest entry.
    Prefer adding the entry: the reason belongs in the manifest, where the next
    reader will find it, not at one call site.
    """
    path = os.path.join(directory or HERE, name)
    v = MANIFEST.get(name)

    if v is None:
        # Absence from the manifest means UNASSESSED, never "current". Only
        # complain when the caller actually wants something a timing fix could
        # move -- structural columns are safe to read from anywhere.
        wanted = sorted(set(columns) & _TIMING_SENSITIVE) if columns else []
        if wanted and accept_unregistered is None:
            raise UnregisteredFileError(
                f"{name} has no manifest entry, so its vintage is UNKNOWN -- "
                f"not current.\n"
                f"  timing-sensitive columns requested: {', '.join(wanted)}\n"
                f"  add a Vintage to vintage.MANIFEST, or pass "
                f"accept_unregistered='<why>'\n"
                f"  (absence used to read as 'current'; that is the bug this "
                f"check exists to prevent)"
            )
    elif columns is not None and accept_stale is None:
        bad = v.stale(columns)
        if bad:
            raise StaleColumnError(
                f"{name} ({v.measured}) -- {v.note}\n"
                f"  stale columns requested: {', '.join(bad)}\n"
                f"  current vintage: {', '.join(v.superseded_by) or 'none recorded'}\n"
                f"  to read it anyway, pass accept_stale='<why>'"
            )

    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


def unregistered(directory: str | None = None) -> list[str]:
    """Every committed CSV here with no manifest entry. Audit hook.

    `python3 vintage.py` prints this. A file on this list is not necessarily
    stale -- it is unassessed, which is a different and quieter problem.
    """
    d = directory or HERE
    return sorted(f for f in os.listdir(d)
                  if f.endswith(".csv") and f not in MANIFEST)


def describe(name: str) -> str:
    """One line of provenance, for a header or a log."""
    v = MANIFEST.get(name)
    if v is None:
        return f"{name}: no recorded vintage"
    return f"{name} ({v.measured}) -- {v.note}"


def _main() -> int:
    """Print the manifest and the unassessed files."""
    print(f"registered: {len(MANIFEST)}")
    for name in sorted(MANIFEST):
        v = MANIFEST[name]
        flag = f"  [{len(v.stale_columns)} stale cols]" if v.stale_columns else ""
        print(f"  {name} ({v.measured}){flag}")
    missing = unregistered()
    print(f"\nunassessed: {len(missing)} CSVs with no manifest entry")
    print("  (unassessed is not the same as current -- reads of their timing "
          "columns now raise UnregisteredFileError)")
    for name in missing:
        print(f"  {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
