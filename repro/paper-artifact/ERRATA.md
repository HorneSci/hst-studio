# Numbers in `paper.tex` that no longer match the record

*(This file is about the **paper**. Corrections to the download's own README
and scripts live in `ERRATA.md` at the root of the tree this ships in — two
directories up from here.)*

Checked 2026-08-04 against `docs/CANONICAL_NUMBERS.md` and
`docs/RETRACTED_NUMBERS.md` as they stand today. **Nothing below was changed in
`paper.tex`.** Updating a published number is a decision, not a cleanup, and
three of these move figures the paper is organized around.

`docs/RETRACTED_NUMBERS.md` §6 already lists `learn/pytorch_fit/paper/paper.tex`
as *embargoed: prose still quotes pre-fix numbers*. This file is the itemization
of that embargo.

⚠️ **Which build produced these: not this one.** Every HST figure quoted below
was measured with the router's **Profile 3** arm. Profile 3 is the Enterprise-tier
arm and is **not in the Community build you are holding**, which ships Profile 1.
There is no
equivalent published table for the Community configuration; it has not been
measured. So read these as figures from the research harness that produced the
paper, not as a specification of this download. `TIER.json` in the root of this
tree records which build you have, and its `namedGap` field states the
difference in the terms that are actually supported.

This note exists because a number without its conditions is how this project has
gone wrong before, and "which build" is one of the conditions.

## 1. Four withdrawals that never landed here — clean

Checked explicitly because they moved today:

| Withdrawn / corrected | In the paper? |
|---|---|
| a bare-kernel A/B power pair, reattributed from one arm to the other | **no** — the paper has no energy, power, thermal or joule content of any kind |
| a sparse-attention latency pair, withdrawn as a self-comparison | **no** — no attention material at all |
| a steps-per-joule figure, corrected in the third significant digit | **no** |
| family-sweep worst error 1.6e-15 → 2.01e-15 | **already correct**, carried as $2.0\times10^{-15}$ at `paper.tex:1455` and `:1717` |

The first three rows name the *subject* of each withdrawal and not its
magnitudes, deliberately. Each belongs to a body of work this paper does not
contain and this download does not carry, so quoting the figures would be the
only place they appear in the public record — and they are figures that were
withdrawn. What the row has to establish is that the paper is unaffected, and
naming the subject establishes that. The fourth row keeps its numbers because
they are this paper's own and both are quoted in it.

⚠️ On the last one: the paper puts `1.6e-15` and `2.0e-15` nineteen lines apart
(`:1698` vs `:1717`) and they are **different populations** — 105 distinct
exactness checks versus the 1050-cell three-arm sweep. Both are currently
supported. Only the prose distinguishes them, so an editor tidying "an
inconsistency" would introduce one.

## 2. What IS stale — one fault line, five sites

All of it descends from **which reduction produced the number**, the open
question in `docs/adr/0002-two-reduction-shapes.md`. `agg.py` names two
reduction shapes and picks neither, and the paper declares one while its own
generators use others.

**2a. The declared aggregation rule is the wrong one.** `paper.tex:549–550`:

> Ratios are reported as the median across the five dirty-set seeds within an
> (operator, ρ) cell, then the geometric mean over operators.

`CANONICAL_NUMBERS.md` §1 names that exact phrasing as the rule that was *never*
used for the table: per-seed-median reproduces all six values, median-then-geomean
reproduces three.

**2b. The consequence, at four sites.** `CANONICAL_NUMBERS.md` §1 says verbatim
that it exists "so the next person to recompute does not get 2.95× where this
file says 2.93×". The paper gets 2.95×.

| Site | Paper | Canonical |
|---|---|---|
| `paper.tex:650` | "under uniform jump it opens at $2.95\times$ and decays to $1.35\times$" | 2.93× → 1.36× |
| `paper.tex:651` | "its curves read $6.94 \to 4.74$ and $2.97 \to 1.54$" | drift 6.94× → **4.75×** |
| `paper.tex:753–757` | "$6.94 \to 4.74\times$ under local drift"; "($2.93$ against $2.95\times$)"; "($1.62$ against $1.35\times$)" | as above |
| `paper.tex:1596` (Conclusion) | "($6.94\times$ against $2.95\times$ at the same churn rate)" | 6.94× against 2.93× |

**2c. `tab_headline.tex` uses a *third* reduction the paper never mentions.**
`tables.py:106` computes a flat geomean with seeds pooled (`agg.reduce_flat`).
All four router headline figures land one tick above canonical, all in the same
direction:

| | Table 1 | `CANONICAL_NUMBERS.md` §2 |
|---|---|---|
| router steady, drift churn | 5.12× | **5.08×** |
| router incl. calibration, drift churn | 4.00× | **3.97×** |
| router steady, jump churn | 1.90× | **1.89×** |
| router incl. calibration, jump churn | 1.55× | **1.54×** |

**2d. The arm-order bound is stated below what was measured.**
`paper.tex:1673–1675` says the ordering effect "moved no ratio by more than
$5\%$", measured on three operators. `RETRACTED_NUMBERS.md` §4 ("the fourth tax:
fixed arm order") measures **1.0736 on `p3_vs_csr` under jump** over 1050 paired
cells — 7.4%. Different harness (`bench_churn.py`), so this is a plausible
contradiction rather than a confirmed one, but a three-operator basis is much
weaker than a 1050-cell one and the paper states the weaker one as a bound.

## 3. The pre-fix vintage dependency

`paper_numbers.py:1283–1305` reads `family.csv` through
`vintage.read(..., accept_stale=...)`. `family.csv` was measured
**2026-07-31T04:57**, before the session-path fixes (ISSUES #055) landed later
the same day. Staleness is per column: `vintage.py::_PREP_TIMINGS` marks
`bs_tile_vs_csr`, `p3_vs_csr`, `p3_vs_bs_tile`, `bs_merge_vs_bs_tile` (and the
raw `*_ms` columns) stale; `merge_ratio`, `dens`, `csr_rebuilds`, `rho`, `seed`
are counts or structure and are **not** stale.

**Every number in these two paper sections rests on the stale columns:**

- **§Families** (`paper_numbers.py:s_reference_arm`) — the whole section. Frozen
  and churning win counts and geomeans for both the open reference arm and the
  closed arm, against the column-exact baseline, at every ρ; the shipped-arm-over-
  open-arm ratios; the per-operator uniform-jump loss breakdown. This includes
  the 5.65× / 5.39× quoted at `paper.tex:416`.
- **§Merge, timed half** (`paper_numbers.py:s_merge_open`) — "merged emission
  over per-tile, frozen (timed)" and the four ρ-by-motion timed cells, i.e. the
  $0.28\times$ at `paper.tex:1118`.

**Not affected, in the same function:** the row-touch identity
(`merge_ratio`, and the 2.87× / 1.74× at `paper.tex:1601`), the degenerate-cell
exclusion (`csr_rebuilds`), the padding residual's `dens` term, and everything
`merge_structural.csv` produces. Those are integer counts; no timing fix moves
them.

`compare_prep_gap.py` re-derives what the fixes moved, from the committed CSVs,
so the size of the correction does not have to be guessed. Switching `_fam()` to
`family_pysess_2026-07-31.csv` changes published numbers and is a decision — the
docstring says so, and it is right.

## 4. Conditions

Every measured ratio in a released paper should carry its baseline, machine,
compiler, motion model and churn rate. The paper states machine and compiler
**once**, at `paper.tex:1382–1385` — line 1382 of 2096, after §3 through §9 have
all reported ratios:

> All timings come from a single Intel i7-1165G7 with turbo disabled and the
> performance governor pinned, g++ 13.3, PyTorch 2.13.0+cpu, f64.

No table caption carries machine or compiler; the abstract and introduction
carry neither; and no optimization flags or `-march=` appear anywhere (`:1425`
says "the same flags" and names none), which matters because `marchparse.py`
chooses the `-march` flag every quotable number is compiled under.

The ratios most exposed by this — stated with the fewest conditions and read by
the most people:

| Line | Text | Missing |
|---|---|---|
| `:519–520` | "adopting the benchmark's best configuration is worth $8.8\times$/$15.2\times$/$22.9\times$ at $B{=}1$/$8$/$16$" | motion model, churn rate, machine, compiler — this is the practitioner headline and carries only $B$ and $n$ |
| `:522` | "the open baseline alone is $22.7\times$ faster than the best in-framework delta" | motion model, churn rate, machine, compiler |
| `:493–507` | the five baseline rungs, "$473\times$ / $219\times$ / $136\times$ / $22\times$" | motion model, churn rate, machine, compiler |
| `:108` (abstract) | "a change-detection cost $29\times$ more expensive on one side than the other" | which arm is the denominator; conditions live 760 lines away at `:864–867` |
| `:114` (abstract) | "raises the uniform-jump margin by $1.58\times$" | churn rate — and `:1516–1517` says this is 1.40× / 1.63× / 1.74× depending on ρ |
| `:1595–1596` (conclusion) | "($6.94\times$ against $2.95\times$ at the same churn rate)" | the churn rate itself is never named (it is ρ=0.002) — and see §2b, the 2.95× is stale |
| `tab_baselines.tex` caption | "$197.9\times$ / $73.3\times$ / $22.7\times$ / $3.5\times$ / $2.5\times$" | motion model, churn rate, machine, compiler. "Two orderings" is RCM-vs-native, not a motion model |

Well-conditioned by contrast, and worth copying as the house pattern:
`:648–650`, the `tab_family` caption at `:696–703`, `:874–879`, `:1104–1110`.
