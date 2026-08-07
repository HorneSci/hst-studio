# fitscreen

The candidate finder for **delta-aware sparse recomputation**: it tells you
*where* in your system the method could pay, before you spend anything
attaching it.

The workload the method wants: a sparse operator `A` is fixed, a state `x`
changes by a sparse update each step, and something downstream needs
`A @ (x + dx)` again and again. Most systems contain no place shaped like
that. Some contain exactly one. This tool exists to find out which you have —
from an event log you already export, on your machine, with nothing sent
anywhere.

**What it is not:** it is not the runtime and contains none of it. It never
benchmarks, phones home, or sends data anywhere. You run it, you read the
report, you keep both.

Requires Python 3.9+, standard library only. Runs anywhere, including an edge
node or a bare container.

Terms used below without stopping to define them — **arm**, **operator**,
**delta** — are in the shared [`../GLOSSARY.md`](../GLOSSARY.md).

## The six conditions

Delta-aware recomputation wins **iff all six hold**, and they fail
independently:

1. **Fixed, valued sparse operator** — `A` is sparse, carries real values,
   and is not rebuilt every iteration. (If it *is* rebuilt, ask what the
   change looks like structurally: a sparse, local change is just another
   delta; a structurally full one kills the fit.)
2. **Decomposable aggregate** — `A(x + dx) = Ax + A dx` holds, i.e. the
   computation is linear. Softmax, percentiles, ratios, cardinality all
   break this, and that is a theorem, not a tuning matter.
3. **Sparse delta in the operator's dimension** — few columns of `A` touched
   per step, not merely "few requests".
4. **Localized updates** — the dirty set may *move* (drift along your
   system's own topology is the winning motion) but must be clustered at
   each step. Scattered updates lose.
5. **In-process call path** — a network or IPC hop on the hot path costs
   more than the recompute it replaces.
6. **Matvec, not solve** — a factorization or triangular substitution does
   not decompose over a sparse input delta, even with the other five
   perfect.

Run `python3 -m fitscreen --conditions` for the full checklist plus the
kill-order questions — the cheapest of which is: *is the loop you want to
accelerate the time-stepping loop, or the Newton loop?*

## What the tool measures, and what it only asks

An event log can show two of the six. The rest live in your code, and this
tool refuses to guess at them.

| | How |
|---|---|
| **Measured from your trace** | condition 3 (delta density, state size, batching) and a *proxy* for condition 4 (tile clustering) |
| **Asked, never measured** | conditions 1, 2, 5, 6 — the `--conditions` checklist |

The screen is **topology-blind**: it sees a tag trace, not your operator's
structure, so it cannot distinguish a dirty set that drifts along a real
topology (the profile that wins) from one that merely occupies a bounded
subset. Clustering is the closest honest proxy. A check that needed your
operator's structure would not belong in a trace tool, and none is pretended
here.

Two gates were removed from this screen and must not return: a
batch-to-batch overlap ("pattern stability") floor — retracted because
locality, not repetition, is the binding condition, and the
drifting-but-local case it penalized is the best-qualified workload — and a
delta-density *win* threshold, removed because on the calibration patterns
it passed the losing shape too, and no density threshold orders wins from
losses there. Density survives as an upper bound only: past roughly a
quarter of the state dirty per batch, there is nothing left to skip. The
test suite guards both removals three ways, including behaviourally, so a
renamed revival fails the build.

## Run it

```bash
python3 -m fitscreen events.csv --batch-ms 5000 --hierarchy tags.csv
```

- `events.csv` — `timestamp,tag_id[,...]`, or `.jsonl` with the same keys.
  Aim for at least ten minutes of stream at representative load; the tool
  streams the file, so size is not a concern.
- `--batch-ms` — your actual emit/aggregation cadence.
- `--hierarchy` — a `tag_id,group_id` CSV mapping tags to their aggregation
  groups. Strongly recommended: without it clustering is estimated by
  hashed tiles, and that estimate errs in *either* direction — on the
  shipped samples it reads low on the clustered trace and **high on the
  scattered one**, which is the direction that admits a non-fit.
- `--json` for machine-readable output.

Try it on the shipped samples first:

```bash
python3 -m fitscreen examples/sample_clustered.csv --hierarchy examples/sample_hierarchy.csv
python3 -m fitscreen examples/sample_scattered.csv --hierarchy examples/sample_hierarchy.csv
```

One is a fit, one is not, and the report says why in both cases.

## Reading the verdict

**The gates were calibrated against an exact column-delta baseline** — a
competitor that already skips every clean column. That is the strictest
comparison, so this screen is the conservative one, and the report says so
in every run. If the pipeline you would be replacing recomputes the full
product every cycle, the bar for a win sits far lower than these gates
assume. A gate calibrated for one comparison must never decide a different
one — that substitution has produced wrong answers in both directions, which
is why the final word on any candidate is a measurement, not a threshold.

**NOT A FIT is a real answer, and it is the cheap one.** It costs a CSV
export and a minute of runtime, against the weeks an integration costs
before a mis-fit fails on its own. This project keeps a catalog of more than
forty settled NO-FIT verdicts, each one a direction permanently closed —
and re-deriving one the hard way is the most common wasted effort on
record. If the screen says no, believe it enough to check the calibration
caveat above, then move on.

**On a STRONG FIT, measure — both arms.** The
[`spdelta`](../spdelta/README.md) package in this same tree is the
measurement harness: reference baselines, motion generators, and a
from-scratch oracle asserted on every arm, so neither side of the
comparison can quietly do less work. If your download includes the runtime
(`bin/` present at the top of the tree), `spdelta.hst` attaches the real
HST arm to your own operator — `bin/hst-compile` turns a plain COO JSON
description of your matrix into an operator artifact, and
`spdelta.hst.before_after(a)` runs the before/after on your hardware.
Neither arm is ever picked by threshold; you run both and keep the numbers.

## Tests

```bash
python3 -m pytest tests/ -q
```

The suite pins the screen's verdicts to the recorded win/loss classification
of the four calibration patterns, keeps both removed gates removed (by
threshold name, by verdict surface, and behaviourally — a drifted-but-local
workload must keep its verdict), pins the no-hierarchy fallback's
determinism across hash seeds, and requires a verdict to print even under a
non-UTF-8 terminal.

## License

Apache-2.0. See [`LICENSE`](LICENSE).
