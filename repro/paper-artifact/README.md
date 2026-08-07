# Delta-input SpMM — release artifact

The paper, its open reference implementation, and the export policy that governs
the result data behind them.

**Whether the result CSVs are in your copy decides what this artifact can do,
so check first:**

```bash
ls data/*.csv 2>/dev/null | wc -l     # 35 in the released artifact
```

That should print 35: since 2026-08-07 the released artifact **ships** `data/`
— the gated public-profile export of the paper's result CSVs (34 sweeps plus
`COLUMN_MAP.csv`, the per-column audit trail). From it, **6 of the 14 figures
and 9 of the 15 prose sections re-derive on your machine**; the remaining 8
figures and 6 sections are withheld by the column policy in
`release.config.json` — two columns (`dens`, `router_probes`) encode the tiling
ratio, which is the thing not being published — and `build.sh` names each skip
with that reason and still exits 0, because a policy-withheld figure is a
documented limit, not a failure. `CONFLICTS.md` is the full accounting.

If it prints 0 your copy is stripped or predates the publication: the figure
and prose stages then report their input absent (`build.sh` still exits 0),
and what still runs is the open reference arm and its 20-check self-test, the
denylist gate, and everything in `paper/` and `CONFLICTS.md` you can read.

**Two different reproducibility claims, stated apart because they are not the
same claim:**

- **Derivable.** Every figure and prose number the policy releases re-derives
  from the tracked CSVs in `data/` by committed scripts (`paper/figures.py`,
  `paper/paper_numbers.py`) — checkable on a clean clone, no network, no
  hardware of ours.
- **Re-measurable.** A stranger can regenerate *equivalent* CSVs on their own
  hardware: the `spdelta` package beside this artifact (in the release tree)
  runs the open baseline ladder — full recompute, masked row scan,
  column-exact CSC delta, with a from-scratch reference arm asserted every
  repeat — under the same motion models (frozen/drift/jump) and churn rates,
  and this artifact's `src/blocksched_ref.hpp` is the open block-scheduled
  arm with its correctness self-test. What nobody can regenerate is our
  timings byte-for-byte: the `hst` columns come from the closed arm, and every
  timing column here was measured on one named machine and toolchain (Intel
  i7-1165G7, g++ 13.3, turbo off, pinned governor). Those columns are
  **comparison points with their conditions attached, not byte-reproducible
  outputs** — this estate does not claim byte-reproducibility of any
  measurement, its own re-runs reproduce to within a few percent per cell.

Everything here is buildable from a clean checkout with Python 3. No network, no
GPU, no PyTorch, no framework. **A C++ compiler is optional**: exactly one stage
uses one — the reference arm's correctness self-test — and `build.sh` skips that
stage, and says so, when no named GCC is installed. It quotes no timing, so its
absence costs you a check, not a number.

```bash
./build.sh          # compile, self-test, export, scan, typeset, reprint numbers
./build.sh gate     # only the checks that must pass before distribution
```

---

## What is in here

```
paper-artifact/
├── README.md                    this file
├── CONFLICTS.md                 figures whose data the public export cannot support
├── ERRATA.md                    numbers in paper.tex that no longer match the record
├── release.config.json          THE config — public and private are profiles of it
├── build.sh                     build and verify, in review order
├── src/
│   ├── blocksched_ref.hpp       the open block-scheduled reference arm (stdlib only)
│   └── blocksched_selftest.cpp  20 checks against a from-scratch recompute
├── paper/
│   ├── paper.tex, refs.bib, neurips_2026.sty, tab_*.tex
│   ├── figures.py, tables.py    figure and table generators
│   ├── paper_numbers.py         every number in the prose, reprinted from a CSV
│   └── router_data.py           the one reader for the router sweep
├── tools/
│   ├── export_csvs.py           the allowlisted CSV export (the exporter)
│   └── scan_denylist.py         the identifier gate, over every file
└── data/                        the exported CSVs — 35 files, shipped
```

`data/` is **generated**, not authored — generated *before* distribution, in the
umbrella repo this artifact was staged from, by `tools/export_csvs.py` under the
`public` profile, then gated and committed. In your copy it is an **input**, not
an output: `python3 tools/export_csvs.py` here reads private raw CSVs that are
not present and are not meant to be, so it writes nothing, says why, and exits
77. The files you have are the ones that command produced in the source repo,
and `data/COLUMN_MAP.csv` records what every column of every source CSV became —
`renamed`, `denied` or `free text` — so the policy is auditable per column, not
just readable in `CONFLICTS.md`.

**What is withheld is columns, not files**: the export drops everything a
tiling ratio can be computed from (`dens`, `scanned`/`exact`, `tiles`,
`router_probes`), which is why 8 of the 14 figures and 6 of the 15 prose
sections cannot re-derive from this copy. That boundary was drawn in
`release.config.json` before publication and the publication did not move it.
`paper/figs/` is not shipped pre-rendered — `figures.py` writes it from
`data/`, and `tectonic` typesets from there.

## The reference arm

`src/blocksched_ref.hpp` is a second, independent member of the block-scheduled
family, written against the externally-visible strategy the paper states and
nothing else. It shares no source with the closed arm, and two of its design
choices differ on purpose so that a result which reproduces on it is a property
of the strategy rather than of one codebase. **It is not tuned to win.** Its
purpose is falsification: if the paper's family dichotomy did not appear on it,
the Families section would be a statement about one product.

Its header comment is a complete five-step specification of the algorithm. That
is deliberate and it is the point of releasing the file.

```bash
mkdir -p build
g++-13 -O3 -std=c++17 -DNDEBUG src/blocksched_selftest.cpp -o build/selftest
./build/selftest       # exit code == number of failed checks
```

(`build/` is created by `build.sh`; this block is the standalone alternative to
it, so it has to make the directory itself or the linker fails with errno 2.)

**Name the compiler with every number you take from it.** Codegen variance on
this kernel is a 3–7× effect — larger than any algorithmic knob in the paper —
and on macOS a bare `g++` is Apple clang, a different toolchain that produces
numbers you cannot compare with the paper's. The paper's own measurements are
g++ 13.3 on an Intel i7-1165G7 with turbo off and the governor pinned.

## Rebuilding the numbers

| To rebuild | Run | Needs |
|---|---|---|
| the released CSVs ‡ | `python3 tools/export_csvs.py` | stdlib |
| the reference arm + self-test | `./build.sh gate` | a named GCC — `g++-13`, `g++-14` or `g++-12`, or `CXX=...`. Skipped, not failed, if none is present |
| the tables † | `cd paper && python3 tables.py` | numpy |
| the figures † | `cd paper && python3 figures.py` | numpy, matplotlib, scikit-learn |
| every number in the prose † | `cd paper && python3 paper_numbers.py` | numpy |
| the PDF † | `cd paper && tectonic -X compile paper.tex` | tectonic |

‡ **runs in the source repo only.** In this artifact it exits 77 — the
conventional "did not run, on purpose" code, chosen so it can never be confused
with a result (`tools/gate_env.py`) — prints which private path is missing, and
writes nothing. The same is true of the denylist scan inside `./build.sh gate`,
which reports `skipped` rather than passing.

† **reads `data/`, which ships in this artifact** (top of this file). Expect
partial coverage by design: 6 of 14 figures and 9 of 15 prose sections
re-derive, and each script names every skip it takes and the withheld column
behind it, then exits 0. A `FileNotFoundError` on a CSV means your copy's
`data/` is missing or stripped — see the check at the top of this file.

Every row without a ‡ runs in your copy; if one exits nonzero for a reason
that is not a named policy skip, something is actually wrong.

`paper_numbers.py` tags each value with the section that quotes it. It is the
mechanism behind the paper's claim that every number is printed from a committed
CSV by a committed script — with the exception the paper itself names, and with
the three gaps in `CONFLICTS.md`.

## Public and private are one pipeline, not two

Every tuning decision that differs between the internal and the released version
lives in `release.config.json`, as a **profile**. There is no second codebase and
no fork. Both profiles are publisher-side (‡ above): they read raw CSVs that are
not in this artifact, so neither invocation below does anything here. They are
written out because the policy is worth reading in the same file that enforced
it — not as steps for a recipient to run.

```bash
# in the source repo, before distribution:
python3 tools/export_csvs.py --profile public                    # produces the released data/
python3 tools/export_csvs.py --profile private --output-dir /tmp/full
```

`public` renames the arm vocabulary to `full_recompute` / `delta_baseline` /
`block_open` / `hst`, drops the tiling-structure and profile-versioned columns,
rewrites categorical values, drops the free-text columns, and then **gates** the
result against the release policy and against the kernel identifier denylist.
`private` is the superset: no policy, gate off, nothing renamed. Which figures
ship is in the same file, so a figure cannot quietly outlive the column it needs.

**`private` is not a switch you have.** The columns `public` drops are withheld
deliberately and their source never left the umbrella repo, so naming the other
profile does not restore them — it is the label for the internal run that already
happened, documented so you can see exactly what was applied. What this section
lets a reader verify is the *shape* of the policy; checking that it was actually
applied, column by column, is what `data/COLUMN_MAP.csv` is for, and it is in
your copy — every column of every source CSV, with what became of it.

The gate is not advisory — where it runs, which is the source repo, on the way
to producing this artifact. `export_csvs.py` exits non-zero if a forbidden or
denylisted token survives into an export — header *or* values, because the leak
that mattered historically was an internal arm name carried as **data** in a
`router_arm` column and inside a free-text JSON blob, where a header-only check
would never have seen it.

---

## What this artifact does NOT prove

Read this before quoting anything from here.

**It does not prove the closed arm's numbers.** One of the three arms is closed.
You can run the open baseline and the open block-scheduled reference arm; you
cannot run the third. The closed arm's per-step cost traces are deliberately not
released, so every result involving it is reproducible only as far as the
published aggregates go. The Merge section's row counts come from schedules only
the closed arm builds and are not reproducible at all. This is the largest
limitation and the paper says so.

**It does not prove that block scheduling is faster.** The headline result is a
*dichotomy*, not a ranking: which family wins depends on how the dirty set moves,
and on a frozen set the block-scheduled family **loses** — it scans padding to
buy re-preparation it does not need. A number from this artifact without its
motion model and churn rate attached is not a claim, it is a coincidence.

**It does not generalize past one machine and one compiler.** Every timing comes
from a single 4-core 28 W mobile part with one compiler. The paper splits its own
results by how much that threatens them: the family dichotomy and the integer row
counts are toolchain-robust; the selection study is toolchain-fragile, because it
lives on 53 near-parity cells and codegen variance alone is a 3–7× effect on this
kernel. Nothing here is a claim about a server part, another compiler, or GPUs.

**The reference arm is not a product and was not tuned to be one.** It is a
control. It is *deliberately better* than the arm it stands in for on one axis
(its scratch is tile-local, so it cannot incur the measurement defect the paper
describes) and it makes no attempt to be competitive on any other. Do not read
its timings as an upper bound on what the strategy can do, and do not read them
as a lower bound either.

**It does not resolve motion locality against index locality.** The index-locality
control draws four permutations of one relabelling process over 21 operators.
Four draws show that no single permutation was unrepresentative; they narrow
nothing, because each is bootstrapped separately. Whether motion locality
contributes *beyond* index locality is unresolved — that contrast's interval
covers 1 in every permutation. What the ranking is short of is a wider operator
set, not more permutations of these 21.

**It does not carry within-cell replication.** Multi-seed brackets quantify
dirty-set variance only. They are not run-to-run error bars, and between-session
deviation on this family of measurements is largest exactly where the cells are
tightest.

**Three of its figures cannot be recomputed from the released data**, and one
exclusion rule cannot be reapplied. See `CONFLICTS.md`. The affected numbers are
not wrong; they are unreproducible from this artifact alone.

**Several numbers in `paper.tex` are stale against the current internal record.**
See `ERRATA.md`. They are itemized rather than corrected, because changing a
published number is a decision.
