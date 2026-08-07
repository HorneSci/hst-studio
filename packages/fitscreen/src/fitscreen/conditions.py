"""The six-condition fit screen, as text a person can act on.

Delta-aware sparse recomputation wins if and only if all six conditions hold.
They fail independently: a workload can satisfy five perfectly and die on the
sixth. The trace screen in this package measures the two that are visible in
an event log; the other four are questions about your code, and no amount of
trace analysis answers them — which is why they ship as a checklist rather
than being silently assumed.

Every NO here is an answer worth having. Screening projects against these
conditions has produced far more settled NO-FITs than fits, and each one
closed a direction permanently instead of costing an integration that fails
late. Re-deriving a NO the hard way is the most expensive way to learn it.
"""

# What the trace screen measures, and what it can only ask. Kept as data so
# both output surfaces (text and JSON) say the same thing.
MEASURED = (
    "sparse delta (density, state size, batching)",
    "locality (tile clustering — a topology-blind proxy)",
)
NOT_MEASURED = (
    "fixed valued operator",
    "decomposable (linear) aggregate",
    "in-process call path",
    "matvec, not solve",
)

CALIBRATION_NOTE = (
    "CALIBRATION: these gates were calibrated against an exact column-delta "
    "baseline — a competitor that already skips every clean column. That is "
    "the strictest comparison, so this screen is the conservative one. If "
    "your incumbent recomputes the full product every cycle, the bar for a "
    "win is far lower than these gates assume; a gate calibrated for one "
    "comparison must never decide a different one. On any YES — and on a "
    "NO whose incumbent is a full recompute — measure both arms on your own "
    "workload; never pick by threshold."
)

_CONDITIONS = """\
The six-condition fit screen
============================

Delta-aware sparse recomputation wins iff ALL six hold. They fail
independently, so check every one — the cheapest kills are listed after.

  1. FIXED, VALUED SPARSE OPERATOR. The matrix A is sparse, carries real
     values (not a boolean mask), and its values are not rebuilt every
     iteration. If A is a function of the current solution estimate (a
     Newton loop relinearizing), ask what the change dA looks like
     STRUCTURALLY: a sparse, local dA is just another delta apply and does
     not kill the fit; a structurally full dA — every state variable's
     entry moves — does. Ask for dA's structure, not for whether the
     operator is "rebuilt".

  2. DECOMPOSABLE AGGREGATE. A(x + dx) = Ax + A dx must hold — the
     computation is linear in the state. Softmax, percentiles, ratios and
     cardinalities all break this: one dirty input densifies the whole
     output, so nothing can be skipped no matter how sparse the input
     delta is. This is a theorem about the operation, not a tuning matter.

  3. SPARSE DELTA IN THE OPERATOR'S DIMENSION. Few columns of A are
     touched per step — sparse in the dimension A consumes, not merely few
     of something else (few requests, few users, few files).

  4. LOCALIZED UPDATES. The dirty set may MOVE — drift along the system's
     own topology is the winning motion, not a problem — but at any given
     step it must be clustered. A dirty set that teleports or scatters
     across the state loses. Step-to-step repetition is NOT required and
     is not this condition: a gate that demanded it was retracted, because
     the drifting-but-local case it penalized is the best-measured win.

  5. IN-PROCESS CALL PATH. The apply must be a function call in your
     process. A network hop or IPC boundary on the hot path costs more
     than the recompute it replaces — measured, not supposed — so a
     service boundary between the state and the operator kills the fit
     regardless of everything else.

  6. MATVEC, NOT SOLVE. The hot operation is multiplying by A. A
     factorization or a triangular substitution does not decompose over a
     sparse input delta, even with every other condition perfect. This is
     the condition most often discovered last, and it is a structural
     kill, so check it first when the workload is a solver.

The kill-order questions (cheapest first)
-----------------------------------------

  * Is A rebuilt every iteration as a function of the current solution,
    with a structurally full dA?  ->  stop (condition 1).
  * Is the hot path a linear SOLVE rather than a matvec?  ->  stop
    (condition 6).
  * "Is the loop you want to accelerate the time-stepping loop, or the
    Newton loop?"  Time-stepping over a fixed physical topology is where
    the winning profile lives; a Newton loop usually fails condition 1 —
    but ask about dA's structure rather than assuming.
  * Does the incumbent already do a delta — and does it skip the SCAN, or
    only the arithmetic? An incremental path that still scans every
    nonzero to do a sparse amount of arithmetic is not the same rung as
    one that skips whole regions; "we already do a delta" is a question,
    not a disqualifier.

What this package measures vs what it asks
------------------------------------------

  Measured from your trace:  {measured}
  Asked, never measured:     {not_measured}

  The trace screen covers conditions 3 and (by proxy) 4. Conditions 1, 2,
  5 and 6 live in your code; answer them from the checklist above.

{calibration}
"""


def conditions_text() -> str:
    return _CONDITIONS.format(
        measured="\n                             ".join(MEASURED),
        not_measured="\n                             ".join(NOT_MEASURED),
        calibration=CALIBRATION_NOTE,
    )
