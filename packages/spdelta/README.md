# spdelta

Reference baselines, motion generators, controls, and a claim type for
**delta-updated sparse matrix-vector products**.

The workload: a sparse operator `A` is fixed, a state `x` changes by a sparse
update `dx` each step, and you want `A @ (x + dx)`. There are several ways to
compute that. They differ by orders of magnitude. Which one wins depends on
conditions that are easy to leave out of the write-up — and every one of those
conditions has, at least once, silently changed underneath a published number.

`spdelta` is the measurement scaffolding, not a kernel. It gives you honest
baselines to compare against, named generators for how the dirty set moves,
controls that are hard to switch off by accident, and a result type that refuses
to hand you a bare float.

Requires Python 3.10+, `numpy` and `scipy`. Nothing else. Commands below use
`python3` rather than bare `python` — on some machines the two resolve to
different interpreters or different major versions. Every package in this
estate (`bindnum`, `claimlint`, `hst-evidence`, `magnitude-guard`) follows the
same convention.

Terms used below without stopping to define them — **arm**, **cell**,
**reduction**, **rho**, **profile** — are in the shared
[`../GLOSSARY.md`](../GLOSSARY.md), one glossary for this package and its four
siblings (`bindnum`, `claimlint`, `hst-evidence`, `magnitude-guard`).

---

## Fifteen minutes

### 1. Install (1 min)

If you got this inside an HST Studio download, `./install.sh` at the top of that
tree has already done this and you can skip to step 2. Standalone:

```bash
python3 -m pip install -e ".[test]"      # from this directory
```

Or skip installing and just put `src/` on the path — the examples and tests do.

### 2. Run the worked example (1 min)

```bash
python3 -m spdelta.example
```

It generates three toy operators, runs the ladder over four motion models and
three churn rates, prints the table, and ends with a `Claim`. Roughly ten
seconds on a laptop. Everything it touches is synthetic and generated from seeds
in this repository.

### 3. The ladder on your own operator (5 min)

```python
import numpy as np
import spdelta as sd

a = sd.banded(4000, 9, seed=11)          # or any scipy sparse matrix

cells = sd.standard_cells(
    [("my_operator", a)],
    [
        lambda name, m, rho: sd.frozen(),
        lambda name, m, rho: sd.drift(sd.Topology.line(m.shape[1], 3), rho),
        lambda name, m, rho: sd.jump_plain(m.shape[1], rho),
        lambda name, m, rho: sd.jump_nnz_matched(m, rho),
    ],
    rhos=(0.01, 0.05, 0.25),
    seeds=(17, 18),
)

rows = sd.sweep(sd.ladder(), cells, reference=sd.reference())
```

`sweep` runs `full_matvec`, `masked_row_scan` and `column_delta_csc` on every
cell, rotates their order, and asserts every one of them against a from-scratch
oracle after every repeat. There is no keyword that turns that assertion off.

### 4. Turn rows into a claim (5 min)

```python
paired = sd.ratio_rows(rows, arm="column_delta_csc", baseline="masked_row_scan")
subset = [r for r in paired if r["motion"].startswith("drift") and r["rho"] == 0.05]

claim = sd.Claim.from_rows(
    subset,
    baseline="masked_row_scan",
    reduction="reduce_median_then_geomean",   # no default: you choose
).with_ceiling(0.25)

print(claim)
```

```
2.673x vs masked_row_scan
  motion      drift[line(radius=3)]
  churn       rho=0.05, measured ceiling rho<=0.25 (above it: unmeasured, not weak)
  toolchain   CPython 3.14.6 / numpy 2.4.1 / scipy 1.17.1 / arm64 Darwin
  control     reference=scratch_reference; rotate=True; repeats=3; steps=64; stat=median; tol=1e-09
  cells       1
  reduction   reduce_median_then_geomean
```

`float(claim)` raises `TypeError`. That is deliberate.

Note `cells 1`. One operator at one churn rate is one cell, however many seeds
and repeats went into it — and the claim says so rather than letting six rows
look like six observations.

### 5. Confidence, honestly (3 min)

```python
lo, hi = sd.bootstrap_ci(subset, lambda r: r["ratio"])
```

Resamples **operators**, not rows. Five seeds of one operator are not five
observations, and a row-level bootstrap will happily tell you otherwise.

---

## What's in the box

| Module | What it owns |
|---|---|
| `spdelta.delta` | `CompactDelta` / `GlobalDelta` / `GlobalScatter` — two update encodings as distinct types |
| `spdelta.baselines` | `FullMatvec`, `MaskedRowScan`, `ColumnDeltaCsc`, `ScratchReference`, `ladder()` |
| `spdelta.motion` | `frozen()`, `drift()`, `jump_plain()`, `jump_nnz_matched()`, `mix()`, `slice_weight()`, `slice_drift()` |
| `spdelta.harness` | `sweep()`, `order()`, `summarize()`, the three reductions, `bootstrap_ci()`, `ratio_rows()` |
| `spdelta.claim` | `Claim` |
| `spdelta.operators` | toy generators and `Topology` |
| `spdelta.profiles` | every tunable constant, in one place |

---

## The five design decisions, and what each one cost to learn

Everything opinionated in this package is opinionated because the alternative
produced a wrong number that looked right.

### 1. The two delta encodings are different types

A sparse update has two natural encodings, and they are the same dtype and a
similar size:

* **compact** — `vals[i]` updates column `cols[i]`. Indexed by *position in the
  dirty set*.
* **global** — `buf[j]` updates column `j`, zero elsewhere. Indexed by *column*.

Hand a global buffer to a compact-indexed kernel and it reads
`buf[0 : |D|*batch)`: the wrong values, from a region the same size and just as
contiguous as the right one. Every timing looks normal. One such swap produced a
relative L2 error in the 1e-2 range with nothing anomalous anywhere in the output.

So `CompactDelta` and `GlobalDelta` are distinct types, each kernel declares
which it consumes, and passing the wrong one raises `TypeError` before any
arithmetic happens. Reuse of a global buffer goes through `GlobalScatter`, which
re-zeroes exactly the columns it wrote last step — a separate defect, worth
a measurable relative L2 error, was a buffer that was never cleared.

### 2. A ladder, not a baseline

"25x" and "3x" are routinely the same measurement against different comparands,
and they cannot be chained. `spdelta.baselines` runs all the rungs in one
window:

| Rung | Who does this |
|---|---|
| `full_matvec` | almost everyone, including every stock sparse matvec |
| `masked_row_scan` | the engineer who knew about deltas and had row-major storage |
| `column_delta_csc` | a competent delta implementation — **the honest baseline** |

The middle rung is the useful one. It *looks* like a delta method and is not: it
skips the work but not the scan, so its cost stays O(nnz) and its advantage
stays roughly flat across an entire churn range. When somebody says "we already
do a delta", the follow-up question is not whether they skip work. It is whether
they skip the **scan**.

`ScratchReference` is the fourth arm and is not a rung. It recomputes from
scratch through a code path no timed arm shares, and `sweep` asserts every arm
against it after every repeat. It is not in `ladder()` on purpose: an oracle
that is also a timed arm can end up asserted against itself and pass vacuously.

### 3. Frozen is an object, not `rho=0`

A generator that computed its swap count as `max(1, round(rho * |D|))` swapped
one column per step at `rho = 0`. The "frozen control" recompiled on 19% of its
steps and reported the fast arm 1.69x ahead in the one regime where that arm is
known to lose. A control that is not the control is worse than no control.

Here, `frozen()` returns an object with no swap code path, and `drift` /
`jump_plain` / `jump_nnz_matched` reject `rho <= 0` outright. A rate that rounds
to zero swaps raises rather than clamping — the clamp is what caused the
original defect, and a silent floor would cause it in reverse.

`sweep` also refuses a cell that claims a churn rate but whose dirty set never
actually moved.

### 4. "Jump" is not a generator name

Uniform teleport does two things at once: it destroys locality, which is
intended, and it drags the dirty set toward the operator's average column
density, which is not. On one measured pair of sweeps the slice's nonzero count
fell 13.7% over a run under uniform jump and 0.0% under an nnz-matched draw, and
the measured ratios differed by 1.41x to 1.82x on identical operators, seeds and
rates — with the gap widening as the churn rate rose. Most of the apparent
"locality decays with churn" effect was the slice getting lighter.

So the two generators have separate names, neither is called "jump", and
`slice_weight` / `slice_drift` are there so any sweep can show which effect it
is looking at. `sweep` records the slice weight at the first and last step of
every run without being asked.

### 5. The number does not travel without its conditions

`Claim` is a frozen dataclass carrying `ratio`, `baseline`, `motion`, `rho`,
`rho_ceiling`, `toolchain`, `control`, `n_cells` and `reduction`. It **does not
implement `__float__`**. You can get the number out — `claim.ratio` — but you
have to decide to, by name, at which point the conditions are right there.

`Claim.from_rows` has no default reduction. Two shapes are in use,
`reduce_flat` and `reduce_median_then_geomean`, both are defensible, they
disagree, and choosing between them moves published numbers. This package will
not make that choice for you.

---

## Public and private tuning

Every tunable constant lives on `spdelta.profiles.Profile`, and there is exactly
one public instance, `PUBLIC`. **The split between what an open package ships
and what an organisation runs internally is configuration, not a fork.**

An internal overlay is a separate module that derives its own profile:

```python
# mycorp/bench_profile.py
from spdelta.profiles import PUBLIC, ToySpec, derive

INTERNAL = derive(
    PUBLIC,
    name="mycorp-bench-v3",
    steps=20_000,
    repeats=4,
    rho_grid=(0.01, 0.05, 0.25),   # NOT 0.0 -- frozen is a control, not a
                                   # churn rate; the sweep adds it itself
    operators=(...),                  # a real corpus
    reduction="reduce_median_then_geomean",
)
```

```bash
SPDELTA_PROFILE=mycorp.bench_profile:INTERNAL python3 -m spdelta.example
```

The profile name is recorded on every result row, so a number produced under the
public profile says so on its face.

**Knobs expected to differ, and why** — the full table is in
`spdelta/profiles.py`. The short version:

| Knob | Why an overlay changes it |
|---|---|
| `steps`, `repeats` | The public values finish in seconds on a laptop, which makes them the wrong values for anything quotable. |
| `operators` | The public list is toy operators generated by this package. This is the field most likely to differ and the one most likely to be quoted past its warrant. |
| `rho_grid` | The measured ceiling is a property of what actually ran. |
| `n_dirty`, `batch` | Workload shape. Both change which arm wins. |
| `tolerance` | Strict here, because the arms are exact. An approximate arm needs a looser one and needs to say so. |
| `stat`, `rotate` | Latency vs throughput; and `rotate=False` exists so order bias can be measured. |
| `reduction` | `None` in public on purpose. An organisation *may* decide once; a library may not decide for everyone. |
| `bootstrap_reps`, `bootstrap_alpha`, `nnz_bands`, `drift_radius` | Cost/precision and workload-locality trade-offs with no universally right value. |

No value in `PUBLIC` came from a measurement. A test asserts that every field on
`Profile` appears in that table, so a knob cannot be added without someone
deciding whether it is expected to differ.

---

## Testing

```bash
python3 -m pytest
```

172 tests, under a second. Every test in the suite is mutation-proven: 160
defects were injected one at a time into the package source, each was confirmed
to make the suite fail, each was reverted, and the suite was confirmed green
again. Every mutation was caught by at least one test, and every test caught at
least one mutation — a test that catches nothing is not a test.

---

## Licence

Apache-2.0. Chosen over MIT for the explicit patent grant: this is measurement
infrastructure for a domain with active patent activity, and users of a
benchmark harness should not have to reason about whether running it exposes
them. The contributor patent grant in §5 also makes the inbound side
unambiguous, which MIT leaves open.
