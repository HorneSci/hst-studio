# Glossary

Shared vocabulary across `spdelta`, `bindnum`, `claimlint`, `hst-evidence`
and `magnitude-guard`. One file so five READMEs don't each carry (and
drift on) their own copy. Each entry says which tool(s) actually use the
word — several of these are overloaded across the estate, and the overload
is exactly what a cold read trips on.

### arm

One of the alternative ways of computing the same answer that a benchmark
is comparing. `spdelta.baselines` ships `full_matvec`, `masked_row_scan`
and `column_delta_csc` as arms on one ladder; a router picks between
arms by measurement rather than by a fixed rule. An arm is a *code path*,
not a result — "the arm won" means it was fastest under the conditions
tested, not that it is fastest in general.

### cell

One `(operator, motion, rho)` combination that a sweep measured — a single
point in the grid, however many seeds and repeats fed into it. `spdelta`:
five seeds of one operator at one churn rate is **one** cell, not five
observations, and a `Claim`'s `n_cells` field says so on purpose (a ratio
over three cells and a ratio over three hundred must not print
identically).

### element

`claimlint`-specific. One of the conditions a performance claim is
required to state nearby for the ratio to be interpretable — the default
profile's four are `baseline`, `hardware`, `sample_size`, `toolchain`.
"Missing an element" means the scanner found a ratio-shaped figure without
that condition inside its proximity window, not that the number is wrong.

### grade

`hst-evidence`-specific. A strictness label on a golden-vector case,
**GRADE-A** (byte-identical) or **GRADE-B** (`rel_l2 <= bound`, a
calibrated tolerance). This is not a correctness ranking: a perfectly
correct implementation that sums in a different order will fail
GRADE-A, and the README measures by how much, case by case.

### profile

Two unrelated shapes share this name:

- **`spdelta.profiles.Profile`** — a bundle of tunable constants (steps,
  repeats, `rho_grid`, operators, reduction, ...). `PUBLIC` is the one
  shipped instance; an organisation derives its own with `derive(PUBLIC,
  ...)` rather than forking the package.
- **`claimlint`'s `--profile`** — a named builtin starting point
  (`default` or `strict`) for which elements are required, the window
  size, and so on, further layered by a project's own `.claimlint.toml`.

Both senses mean "a named, swappable bundle of settings, not a fork of the
code that reads them." Which one a given README means is always the tool
it's written under.

### reduction

How several measurements at one cell (or several cells) collapse into one
number. `spdelta` ships two shapes that disagree on purpose —
`reduce_flat` (pool every row, then one geomean) and
`reduce_median_then_geomean` (median within a cell first, geomean across
cells second) — and `Claim.from_rows` has **no default**, because the
choice between them moves the published number.

### rho (ρ)

`spdelta.motion`-specific. The fraction of the dirty column set a motion
generator (`drift`, `jump_plain`, `jump_nnz_matched`) retires and replaces
each step, passed as a plain float in `(0, 1]`. `rho <= 0` is rejected
outright rather than clamped: an earlier version computed the swap count as
`max(1, round(rho * |D|))`, which meant a "frozen" run at `rho = 0` was
still swapping one column every fifth step. `frozen()` is therefore a
separate object with no swap code path at all, not a special case of a
churning generator.

*(Deliberately not defined in the sentence above: a workload's general
"churn rate" is the property `rho` numerically expresses in this project.
The two are not interchangeable everywhere in the estate — magnitude-guard's
proximity scanner treats the literal token `rho` as one measurement-word cue
among several, `speedup`/`median`/`ceiling` included, not as a name for a
concept — so `rho` here names the parameter, and the sentence that
introduces it should not also be the sentence that tries to gloss "churn
rate" in general.)*

### ratchet

Three referents share this word across two tools; pick the sense from
context, and when this glossary or a README uses "ratchet" alone with no
qualifier, it means the third one below.

1. **`claimlint`'s three named rules** — no new incomplete document; no
   allowlisted document may lose an element it currently states; a
   document that is now clean must leave the allowlist. `RESULT.ratchet`
   is the object that holds the outcome of applying all three.
2. **A specific allowlist file** that `magnitude-guard` can generate —
   pre-populated with a `GAP —` entry per magnitude already present in a
   tree on the day it was generated, so a CI job can go green immediately
   and red on anything *new*.
3. **The general enforcement shape**, in both tools: debt is recorded
   with a reason rather than silently allowed, the recorded set must
   strictly shrink or hold — never regrow without a new reason attached —
   and a passing check today is not a promise the check ran on everything,
   only that everything it found is accounted for. This is the sense
   meant when either README calls itself "a ratchet, not a denylist."

### rule 4

The no-kernel-source packaging assertion: a build-side check that extracts
the artifact a packaging step just produced and fails if it contains a
C/C++ source file or any identifier on a shared kernel denylist. It is
implemented where the kernel sources are, which is not here and not in any
distribution — so nothing in this tree can show it to you, and none of
these tools performs it.

The word appears here because `magnitude-guard` contrasts itself with it,
and the contrast is the point: rule 4 asks "is a kernel symbol present";
magnitude-guard asks "is a measured magnitude present". Neither subsumes
the other — a whole measured envelope can sit in javadoc and pass rule 4
cleanly, because not one line of it is a kernel symbol.

### teeth

`bindnum`-specific. `bindnum.teeth` (shipped as the pytest plugin
`pytest-teeth`) is the pair of standing rules that keep a binding suite
from passing vacuously: `assert_corpus_floor` (the registry of bound
numbers cannot silently shrink to zero) and `mutation_verified` /
`pytest --mutation-todo` (a test that has never been observed to fail is
a hypothesis, not a test). "Teeth" names the property, not a specific
check — a suite that cannot fail has none.
