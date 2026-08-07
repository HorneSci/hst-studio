# Where the allowlist and the paper disagree

The public CSV export drops three columns that figures and prose in `paper.tex`
are computed from. Each is a real conflict with exactly two resolutions —
**the figure loses its data, or the paper loses the figure** — and neither is
taken here. They are decisions about published content.

> **Publication status, 2026-08-07 (issue #67).** The public-profile export in
> `data/` is now tracked and ships with the artifact, so the releasable side
> of this file's accounting is live: **6 of 14 figures and 9 of 15 prose
> sections re-derive from the shipped CSVs**, and the three conflicts below are
> unchanged — publishing the export did not move the column boundary, and the
> 8 policy-withheld figures stay withheld. One detail supersedes §2's blast
> radius as measured 2026-08-05: `fig_regret_cdf` now reports the withheld
> columns as its blocker (it cascades through `router_data.load()` like the
> other seven), so all 8 skips carry the policy reason; scikit-learn remains a
> second, independent blocker for that one figure if the columns ever return.
> A withheld column reappearing in a tracked CSV fails
> `tests/test_published_csv_policy.py` in the umbrella repo, and the export
> gate itself (`tools/export_csvs.py`) fails on it at generation time.

Reproduce this list at any time:

```bash
python3 tools/export_csvs.py --quiet     # writes data/COLUMN_MAP.csv
```

`COLUMN_MAP.csv` records every column of every released CSV as `renamed`,
`denied` or `free text`, so the cost of the policy is auditable rather than
asserted.

---

## 1. `dens` — dropped from 19 CSVs. The largest conflict.

The release policy forbids `dens` and anything a tiling ratio can be computed
from, so `dens` is dropped and `scanned`/`exact` (whose quotient *is* `dens`)
go with it.

Renaming `dens` to something neutral was tried and reverted: it renames the
leak rather than removing it. The column carries the ratio itself.

**What stops working**

| Site | What it is |
|---|---|
| `tab_operators.tex` | Table 2 has a printed `dens` column, one value per operator |
| `figures.py:286` | the padding figure — x-axis is entries scanned ÷ entries needed, i.e. `1/dens` |
| `figures.py:393–412` | the class-overlap histogram — `dens` by winning arm, the figure whose whole point is that the two classes overlap |
| `paper.tex:1202–1204` | "the two with $\mathrm{dens} < 0.30$", "`circuit_3`, which sits between them at $\mathrm{dens} = 0.80$" |
| `paper.tex:1233` | the cost model's definition, $\mathrm{dens} = \mathrm{nnz}_e/\mathrm{nnz}_s$ |
| `paper.tex:1257–1259` | "divided by $\mathrm{dens}$ is $0.59\times$ (range $0.37$–$1.10$): padding is the …" — prediction 1 of the cost model |
| `paper.tex:1263–1274` | prediction 2, "$\mathrm{dens}$ alone had to fail" |
| `paper.tex:1754–1762` | the appendix bound: "$\mathrm{dens}$ from $0.17$ to $1.00$", "classes overlap on $\mathrm{dens} \in [0.17, 0.91]$, an interval containing 340 …" |
| `paper.tex:1900–1910` | the feature-cost analysis: "Of the six features, only $\mathrm{dens}$ is not free" |
| `paper_numbers.py` §4 | "frozen ratio / dens", the residual that prices padding |

**The shape of the decision.** `dens` is not incidental to the paper — the
entire cost-model section is *about* it, and the paper already discloses it by
name and by formula in prose. Publishing the formula and withholding the column
is a defensible line (the reader can recompute it on their own operators from
their own runs) but it is a line, and it should be drawn deliberately. The three
options, none of which I took:

1. release `dens` and accept that the padding ratio is public — consistent with
   the paper already defining it in §Cost model;
2. cut the cost-model section, Table 2's column and two figures;
3. release `dens` **rounded** or bucketed, which supports Table 2 and the
   overlap histogram but not the $0.59\times$ residual.

## 2. `router_probes` — dropped from 6 CSVs. Quietly the worst one.

Not a figure. **An exclusion rule.**

`router_data.py:28,75` documents and implements it: *a row with `rho > 0` and
`router_probes == 0` never actually churned and is excluded.* That rule is
applied to every router aggregate in the paper, including the four headline
figures in `tab_headline.tex`.

Dropped, the released CSVs still contain those rows and a reader has no way to
identify them. **Every router number in the paper becomes non-recomputable from
the released artifact** — not wrong, unreproducible, which is worse for a paper
whose Artifact section says every number is printed from a released CSV by a
committed script.

Note the family sweep does *not* have this problem: its exclusion rule keys off
`csr_rebuilds` (released as `delta_baseline_rebuilds`), which survives.

The cheap fix, if it is acceptable: export a boolean `excluded` column computed
from `router_probes` and drop the count. That releases the rule without
releasing the probe count. It is one line of config and I did not add it,
because a derived column that silently encodes a dropped one is exactly the kind
of thing that should be approved rather than slipped in.

### Measured blast radius (2026-08-05)

The paragraph above says "every router number" without saying how many that is.
Counted by running `python3 paper/figures.py` against the released `data/`:

**6 of 14 figures are produced. 8 are not.** Seven fail on withheld columns:

| figure | withheld column it needs |
|---|---|
| `fig_frozen` | `dens`, `router_probes` |
| `fig_churn_response` | `dens`, `router_probes` |
| `fig_heatmap` | `dens`, `router_probes` |
| `fig_overlap` | `dens`, `router_probes` |
| `fig_asymmetry` | `dens`, `router_probes` |
| `fig_third_arm` | `dens`, `router_probes` |
| `fig_motion_control` | `router_probes` (via `alpha400_mix.csv`) |

The eighth, `fig_regret_cdf`, is a different problem entirely — it needs
scikit-learn, which is a dependency gap and not a release-policy one. Do not
count it against the export.

All seven cascade through `router_data.load()`, so they stand or fall together:
releasing the `excluded` boolean proposed above would restore the exclusion rule
but **not** `dens`, and `dens` alone still blocks six of the seven. The one that
would come back is `fig_motion_control`.

This number is stated here because "unreproducible" is a claim with a size, and
a reader deciding whether the artifact is worth downloading needs the size.

## 3. `tiles` — dropped from 9 CSVs.

The number of column-tiles the dirty set spans. Combined with `dirty_cols`, it
recovers the tile width, so it is inside the policy's "anything a tiling ratio
can be computed from".

**What stops working**

| Site | What it is |
|---|---|
| `paper_numbers.py:778` | "tiles the dirty set spans" as a candidate offline predictor in the selection study |
| `paper_numbers.py:875` | "tile count stationary at $X$" — the splice section's control, showing arrivals balance departures while the tile count does not move |

Smaller than the other two: one appendix predictor row and one supporting
sentence.

---

## Not a conflict, but adjacent

- **`family.csv` is pre-fix vintage and it is in the release set.** Its
  preparation *timings* predate the 2026-07-31 session-path fixes; its row
  counts do not. `vintage.py` enforces this per column against the working copy,
  and the released copy carries the same columns with the same staleness. See
  `ERRATA.md` §3.
- **`csr_delta.hpp` is promised by the paper and is NOT in this bundle.** It has
  not been cleared. A denylist scan of the working copy returns **five hits**.
  Four are the same generic-C++ class `blocksched_ref.hpp` hit — the restrict
  qualifier, the accumulator subscript, the fixed-batch-width dispatch suffix,
  and the runtime-dispatch suffix — and rename or drop the same way. The fifth
  is a delta-offset name from the schedule kernel's hot-loop group, and it needs
  a look rather than a mechanical rename. Reproduce the list with
  `python3 tools/scan_denylist.py --root ../../learn/pytorch_fit --verbose`.
  Clear it before the artifact matches what §Artifact promises.
