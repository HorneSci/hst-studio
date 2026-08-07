# HST Studio — Community

A delta-aware sparse linear algebra runtime, and the tooling to find out whether it
helps you.

```bash
./install.sh      # venv + three Apache-2.0 packages, ~1 minute
./verify.sh       # runs everything and reports what worked on YOUR machine
```

Python 3.11+. No licence key, no account. The runtime **is** in this
download — `bin/` holds the library and the tools — and it is Apache-2.0, like the
packages beside it. Two subtrees under `repro/` are not; *Licence*, below, is exact
about both.

**A C++ compiler is optional.** Exactly one stage of one step uses one — the
correctness self-test of the paper artifact's open reference arm — and it is
skipped, by name and with a reason, when no named GCC (`g++-13`, `g++-14`,
`g++-12`, or your own `CXX=`) is installed. That stage quotes no timing, so its
absence costs a check and no number. This line said a flat "No compiler" until
2026-08-06 while `repro/paper-artifact/build.sh` hard-failed without `g++-13`,
which made `./verify.sh` — the second command in this README — exit 1 on a
machine the README had just called sufficient.

**`install.sh` needs network access once.** `spdelta` depends on `numpy` and `scipy`,
which it fetches from PyPI; `bindnum`, `claimlint` and `fitscreen` have no
dependencies at all. It
also fetches `matplotlib`, which no package here needs — it is what `repro/`'s figure
stage draws with, and since this tier ships the result CSVs (see *Reproduction kit*)
it is the difference between 6 of 14 figures re-derived and 0. That one is non-fatal
either way: if it does not install, everything else still does and the figure stage
skips with its reason. Nothing here phones home, at install time or after — the only
outbound traffic is pip talking to your index.

On an air-gapped machine, fetch the wheels somewhere with network and carry them
across (`matplotlib` is optional; without it the figure stage skips and everything
else still runs):

```bash
# on a networked machine, matching the target's Python and platform
python3 -m pip download 'numpy>=1.24' 'scipy>=1.10' 'setuptools>=68' wheel -d wheels/
# on the air-gapped machine, beside this README
./install.sh --wheels ./wheels
```

`setuptools` and `wheel` are in that list because the three packages here are built
from source at install time, and pip builds them in an isolated environment that it
also expects to populate from your index. Leave them out and the install fails on
`setuptools`, not on `numpy` — which reads like a different problem than it is.

We do not vendor those wheels into the download: they are ~90 MB, platform-specific,
and would go stale against your Python version rather than ours.

When a sparse operator `A` is fixed and the input state `x` changes by a sparse delta
`dx` each step, `A·(x+dx)` can be computed as `A·x + A·dx` by touching only the matrix
tiles the dirty columns pass through. That is the whole idea. Everything else is
working out when it pays.

---

## Read this part first

**HST has a narrow operating envelope, and outside it HST loses.** Not "wins less" —
loses, sometimes badly. A badly-fitted deployment is a pessimization.

It needs a fixed operator, a sparse delta, tile-local dirty columns, and a hot path
that is a matrix-vector product rather than a linear solve. A fixed operator whose
bottleneck is a factorization or a triangular substitution does not decompose, even
with every other condition perfect.

This tooling exists because we could not tell you in advance which side of that line
you are on, and neither could you. So measure it.

## Platforms

**Linux x86_64, macOS arm64, and Windows.** `install.sh` and `verify.sh` are
bash scripts; on Windows run them from Git Bash, which ships with Git for
Windows. All three are built, copied out of their source checkout, installed and
verified in CI on every push, so this is a claim with a run behind it rather
than an intention.

What we have **not** tested, said plainly because "supported" would otherwise be
read as covering it:

- **WSL.** It is Linux and our Linux cell is green, but a nearby green cell is
  not a test of the thing you are running.
- **Windows without Git Bash.** There is no `.ps1` and no `.bat` in this tree.
- **Windows on ARM.** Our runner is x86_64.
- **Linux aarch64 and macOS x86_64.** See the note on architectures below.

⚠️ **The runtime library is not available for every platform this tooling runs
on.** `TIER.json` lists what is actually in `bin/` — both the filenames, under
`runtimePlatforms`, and the architecture each was built for, under
`runtimeArchitectures`. Check it before assuming: the `.so` is x86-64 only and
the `.dylib` is arm64 only, so an Intel Mac, a Graviton instance or a Raspberry
Pi will find a library named for its operating system that cannot load on it.

**There is no `hstcore.dll`.** Nothing in this release builds one. On Windows the
language bindings install and the tooling runs, and there is no runtime for them
to bind to. If you need the runtime on Windows, that is a conversation rather
than a download.

## What is in this tree, and what is not

**This tree carries the HST runtime, and it is free.** `bin/` holds the library, the
operator compiler and the before/after tool. There is no token, no meter, no expiry and
no quota: the community library has the licence check compiled out, not set generously.
It is Apache-2.0 like everything else here — usable in production, redistributable, and
it writes nothing to your disk to keep count.

We could have shipped a token that never runs out. A token that never runs out is still
a token we issue, and a build that verifies one is a build you cannot honestly call
free. So the gate is removed rather than widened.

That is not a crippled version of the product. `spdelta` is a real, competent sparse
delta implementation, and it is deliberately the **baseline** — the honest thing to
measure a product against. If it turns out to be fast enough for your workload, you
have learned something worth more than a trial licence, and you have learned it in a
minute instead of a procurement cycle.

**On the paid tier**, so it is not a mystery: the Enterprise build adds Profile 3,
whose advantage is churn-dependent and **is parity when the dirty set is frozen**.
Profile 3's kernel alone is *slower* in every regime — its advantage is fewer schedule
rebuilds, not faster arithmetic — so if your dirty set does not move, the paid build
will not help you and you should not buy it.

Nothing is throttled or artificially slowed in this build, and a test in our tree fails
if that ever stops being true. Being exact about what exists today: **there is no
shipping Enterprise library yet.** Profile 3 is research code, not a productised arm,
so the only build we have is this one, and the only thing a paid build would currently
add is a licence gate. When an Enterprise library exists it will be these same sources
compiled with the same flags plus the extra arm — but we are not going to describe a
binary you cannot buy as though it were sitting on a shelf.

Every report this software emits declares which build produced it and what the other
build adds. **You may publish those numbers anywhere, including numbers that make us
look bad, without asking us first.** Carry the declaration with the figure and you have
met the whole of the obligation.

## The router

HST is not always the right path. The exact column delta it competes with is not
always the right path either, and picking wrong is expensive.

**This build picks by a threshold, and you should hear that from us rather than find
it.** The library splits each update between the two paths using a structural rule — a
ratio of counts taken from your operator, compared against a fixed cutoff, worked out
once when the plan is built. Nothing is timed, and no alternative is tried.

We know the shape of when that is wrong. The rule was written for one specific
comparison and is only correct for that one. Point it at a workload whose real
alternative is a full matrix-vector product and it declines most of the cases it should
take; when we measured the two paths instead, several of the cases it had declined
turned out to be large wins.

So measuring is the right answer and it is the work in front of us. **It is not in this
library yet.** What exists today is `hst tune`: it measures both paths on your own
workload and reports what it found, and you apply the result. That is a genuinely
useful advisory tool. It is not a router, and we are not going to call it one.

This section said the opposite until 2026-08-07 — that the build ran both arms and took
the winner. That was never true of any build we have ever shipped. It is corrected here
rather than quietly, because a reader who takes a routing claim at face value and then
reads the behaviour has learned something worse about us than a threshold.

When measuring does land it will not be a paid feature. The paid build's difference is a
third path to choose between, never a smarter way of choosing — and the manifest that
defines our tiers fails its own tests if those two ever come apart.

## Energy

HST can finish the same job for less total energy, because it finishes sooner.

**It does not make your machine run cooler.** While it runs it draws *more* power and
sits marginally *hotter* than the baseline it replaces, at every churn rate we
measured. The energy win is entirely the shorter runtime, and the energy ratio is
consistently below the wall-clock ratio by exactly that extra draw.

We are specific about this because the opposite claim is easy to make, sounds better,
and is false. Fan speed we could not measure at all — the bench machine has no
tachometer.

## Reproduction kit

In `repro/`. **This tree ships the method and the released measurements.** You get
the paper's text, its open reference implementation, the export policy that governs
the result data, the evidence manifests — and, since 2026-08-07, the result data the
policy releases: `repro/paper-artifact/data/` holds the gated public-profile export,
35 files, committed and identical in every copy. From it, **6 of 14 figures and 9 of
15 prose sections re-derive on your machine. The other 8 figures and 6 sections are
withheld by the export policy and stay withheld** — that boundary was drawn before
publication and publishing did not move it.

Two reproducibility claims, and they are different claims:

- **Derivable.** Everything the policy releases re-derives from the shipped CSVs by
  committed scripts — `./verify.sh` runs it and prints the counts, and the same
  counts come back on a clean clone of our source tree. No network, no HST binary,
  no access to our hardware.
- **Re-measurable.** You can regenerate *equivalent* data on your own hardware:
  `spdelta`'s ladder is the same open baseline rungs the paper measures — full
  recompute, masked row scan, column-exact CSC delta, with a from-scratch reference
  arm asserted every repeat — under the same motion models and churn rates, and
  `repro/paper-artifact/src/blocksched_ref.hpp` is the open block-scheduled arm with
  its 20-check self-test. What you cannot do is reproduce our timing columns
  byte-for-byte, and we do not claim you can: the `hst` columns come from the closed
  arm, and every timing was measured on one named machine and toolchain (a 4-core
  28 W i7-1165G7, g++ 13.3, turbo off, pinned governor). Read those columns as
  comparison points with their conditions attached — our own re-runs reproduce them
  to within a few percent per cell, not to the byte.

The rest of the shape, stated up front:

- **The withheld 8 are a column decision, not a file decision.** Two columns
  (`dens` and `router_probes`) encode the tiling ratio, which is the thing we are
  not publishing; every figure and prose section that needs them reports exactly
  that and skips. `repro/paper-artifact/CONFLICTS.md` names every affected figure,
  table and paper line, and the per-column audit trail `data/COLUMN_MAP.csv` ships,
  so the policy is checkable column by column from your copy.
- **Three of those conflicts have no resolution we were willing to take** — the
  figure loses its data, or the paper loses the figure. `CONFLICTS.md` states both
  options and which we chose. Those numbers are not wrong; they are unreproducible
  from this artifact alone.
- The build **prints every skip and its reason** rather than quietly producing a
  shorter report, and still ends in `BUILD CLEAN`. That is deliberate: a
  policy-withheld figure is a documented limit, not a failure. It does mean
  **`BUILD CLEAN` is not a claim that the whole paper reproduced** — the build
  prints its own coverage on the line above it, and `./verify.sh` reports the stage
  as `part` with both counts, never as a bare `ok`, while any figure stays withheld.
- **The open reference arm is still the falsifiable core**: the 20-check self-test
  in `repro/paper-artifact/src/` compares it against a from-scratch recompute on
  your machine and passes or fails on your hardware. Its header comment is a
  complete specification of the algorithm.
- **One of the three arms is closed.** You can run the open baseline and the open
  block-scheduled reference; you cannot run the third. Results involving it are
  reproducible only as far as the published aggregates go.
- **Everything here is one machine and one compiler** — a single 4-core 28 W mobile
  part, one toolchain, no replication across machines. That matters more than usual
  here: rebuilding the same source under a second compiler on the same hardware, over
  the same 21-operator set, moves results by 3–7× against the first compiler as
  baseline — larger than any algorithmic change in the paper. Nothing here is a claim
  about a server part, another compiler, or a GPU.

```bash
source .venv/bin/activate            # or: PYTHON=.venv/bin/python
cd repro/paper-artifact && ./build.sh
```

Activate first, or name the interpreter — that is not decoration. `build.sh` takes
`PYTHON`, then `VIRTUAL_ENV`, then whatever `python3` your shell resolves; run it bare
on a machine whose system python has no `numpy` and the figure and prose stages skip,
which is how this artifact came to report a clean build of nothing.

It ends in `BUILD CLEAN`, preceded by what it actually produced — figures re-derived
out of total, prose sections re-derived out of total — and a list of what it skipped
and why, in three kinds: a figure or section whose column the export policy withholds,
a pre-distribution check that only runs inside our own repo, and an optional tool you
could install. Only the last is anything you can act on. A skipped stage is a
documented limit, not a failure; a build that hid them would be worth less to you than
one that names them.

`repro/hst-evidence/` holds the golden-vector case manifests, the bit-exact probe
sources and the TLA+ specs for the parts of the system where exactness is a claim
rather than an aspiration. **The vector bytes themselves are not in this tree**: each
`cases/*/manifest.json` states everything needed to regenerate its case and
`tools/gen_cases.py` does so from the public SuiteSparse matrices `tools/fetch_matrices.py`
downloads, so the cases are reconstructible rather than shipped. It is dedicated to the
public domain under CC0 1.0 rather than Apache-2.0, so you can lift any of it into your
own test suite without carrying a notice with it.

## Run HST on your own operator, and see the before/after

This is the part the rest of the tree exists to set up. Three steps, all local.

```bash
pip install ./packages/hstcore-py
python3 -c "
import spdelta as sd
from spdelta import hst
rt = hst.locate()                      # finds bin/ and the library; no token needed
a  = sd.banded(4096, 13, seed=11)      # or any scipy sparse matrix of yours
rows = sd.sweep(sd.ladder() + [rt.arm()],
                sd.standard_cells([('mine', a)],
                    [lambda n,m,r: sd.frozen(),
                     lambda n,m,r: sd.drift(sd.Topology.line(m.shape[1],3), r)],
                    rhos=(0.01, 0.25), seeds=(17,)),
                reference=sd.reference())
"
```

`sd.ladder()` is the before — full recompute, masked row scan, and a competent
column delta. `rt.arm()` is the after. Every arm, HST included, is checked against
a from-scratch oracle after every repeat, and there is no keyword that turns that
off. What comes back is one row per (arm, motion, ρ, seed) with the conditions
attached.

**Read the ratio against `column_delta_csc`, not against `full_matvec`.** Against
a full recompute everything looks spectacular, including the pure-Python column
delta. The number that decides anything is HST against the best baseline you would
otherwise write — and in the frozen control HST is expected to *lose*, because it
scans tile-padded entries where a column-exact delta touches only the dirty
columns' nonzeros. If your dirty set never moves, the ladder will tell you so and
you should not buy anything.

Two mechanical notes. `bin/hst-compile.<platform>` turns your matrix into an operator
artifact — `hst_open` takes an artifact and none of the thirteen exported
functions makes one, so nothing runs without it; it is not metered and needs no
token. And `bin/hst_compare.<platform>` is the same before/after as a standalone
binary, for a workload you would rather express as a stream than as scipy:

```bash
# pick the build for YOUR machine: ls bin/hst_compare.*
./bin/hst_compare.linux-x86_64 --op your_op.bin --stream your_stream.bin --license ""
./bin/hst_compare.darwin-arm64 --op your_op.bin --stream your_stream.bin --license ""
```

No licence argument is needed for the community library — `--license ""` is fine, and
so is omitting it. Nothing here contacts a server.

## Calling the runtime from your language

`bin/` holds `libhstcore` and its header. `packages/hstcore-*` holds a binding for each
of six languages, all Apache-2.0, all binding the same thirteen `extern "C"` functions:

| | Install | Needs |
|---|---|---|
| `hstcore-py` | `pip install ./packages/hstcore-py` | Python 3.10+ |
| `hstcore-java` | `mvn install` (or `./build.sh`, javac only) | JDK 22+ |
| `hstcore-node` | `npm install ./packages/hstcore-node` | Node 18+ |
| `hstcore-go` | `go mod edit -replace github.com/HorneSci/hstcore-go=./packages/hstcore-go` | Go 1.23+, cgo |
| `hstcore-rs` | `cargo add --path ./packages/hstcore-rs/hstcore` | Rust 2021 |
| `hstcore-dotnet` | `dotnet add reference ./packages/hstcore-dotnet/src/Hstcore/Hstcore.csproj` | .NET 9+ |

**Every command above installs from this download, and that is not a convenience —
it is the only thing that works.** None of these packages is published to PyPI, npm,
Maven Central, NuGet or crates.io yet. Until 2026-08-06 three of these rows read
`go get` / `cargo add` / `dotnet add package`, naming coordinates that return 404, and
`hstcore-rs`'s README linked a GitHub repository for `spdelta` while `spdelta` sat two
directories away in the same tree. Each binding's own README says the same thing and
will name a registry coordinate when one exists.

Each has its own README with a worked example and the concurrency rules — **a session is
one mutable cursor over library-owned memory and is not thread-safe**, which is the
mistake that costs the most here because it produces wrong numbers rather than an error.

`packages/hstcore-abi/abi.json` is the machine-readable ABI, and `validate.py` beside it
checks a built library's exports against it. Run that first if a binding fails to load: a
library missing `hst_apply_shadow` or `hst_set_input` is a **stale build** from before the
1.3 → 1.4 bump, not a different ABI, and every binding reports it by name.

**This is an in-process library.** Putting it behind REST or IPC destroys the win it
exists to deliver — per-call overhead has been worth more here than every kernel change
combined. If your call path crosses a process boundary, measure that path, not this one.

## Packages

Standalone and Apache-2.0. Only `spdelta` has dependencies:

| | Dependencies | |
|---|---|---|
| `packages/fitscreen` | none | the candidate finder — screens your own event-log trace against the six-condition fit envelope, and says NOT A FIT when it is not |
| `packages/spdelta` | `numpy`, `scipy` | sparse delta baselines, motion models, controls |
| `packages/bindnum` | none | binds a number in prose to the data it came from |
| `packages/claimlint` | none | statcheck for performance claims — flags ratios missing their conditions |

Start with `fitscreen`: it answers *where* in your system delta-aware
recomputation could pay, from a CSV export, before you attach anything.
`spdelta` is then the measurement; a `fitscreen` verdict is never one.

Shared vocabulary for all of them — **arm**, **cell**, **reduction**, **rho**,
**profile** — is in [`packages/GLOSSARY.md`](packages/GLOSSARY.md).

`claimlint` is pointed at our own documentation in CI. It is not a courtesy.

## Measuring honestly

Two rules this project learned expensively, offered in case they save you the same
tuition:

**Put a from-scratch reference arm in every timing harness and assert against it every
repeat.** We once had three defects in one probe produce clean, well-formed, entirely
plausible timings, because each arm did the right *amount* of work with the wrong
values. Correct-looking timers are not evidence of correct work.

**Name the baseline, and name the rung.** "Faster" against a full recompute and
"faster" against a competent delta implementation are different claims by more than an
order of magnitude, on the same operator in the same run. "We already do a delta" is
not a disqualifier — ask whether they skip the *scan*.

## Licence

**Apache-2.0, `bin/` included.** The library, the operator compiler and the before/after
tool are under the same licence as the packages beside them: production use, modification
and redistribution are permitted, and there is no key, token, quota or expiry anywhere in
this tree.

This is the free tier in the ordinary sense of the word. The paid tier is a *capability*
we have not put in this build — Profile 3 — and not a lock on this one.

`LICENSE` beside this file is the full Apache-2.0 text, and it is what covers this tree
wherever a subtree does not say otherwise. Two subtrees do, and both live under `repro/`:

- **`repro/hst-evidence/` is CC0 1.0, not Apache-2.0.** A public domain dedication, so
  it is *less* restrictive rather than more; `repro/hst-evidence/LICENSE` is the text and
  that package's own README says the same. Take a golden vector, keep no notice.
- **`repro/paper-artifact/` is *not* Apache-2.0 — it is all-rights-reserved with an
  explicit use grant.** `repro/paper-artifact/LICENSE` is the
  text. You may read it, run it, compile and execute the reference implementation in
  `src/`, reproduce its outputs, report what you measured whether or not it agrees with
  what we published, and quote and cite it — all without asking us, including
  commercially. What is **not** granted is redistribution: publishing, mirroring or
  repackaging that subtree for third parties.

  This is narrower than the rest of the tree on purpose. A licence grant is one-way —
  Apache-2.0 text we publish today cannot be withdrawn from copies already made — and
  the paper is not yet placed, so where it lands may carry its own terms for the text
  and figures. Reserving redistribution is revisable; granting it is not. If you need
  rights this does not give you, write to us.

  It does not restrict the use that matters: if your goal is to check whether our
  numbers are real, that licence grants everything you need and asks nothing of you.

Nothing anywhere in this tree is restricted to evaluation, and nothing here needs a
licence key.

We said "Apache-2.0, all of it" here until 2026-08-06. That was wrong about roughly a
third of the file count, in the one section a reader consults precisely because they
intend to rely on it.

## The Enterprise build, when it exists

**It does not exist yet, and this section is a roadmap rather than a price list.**
Profile 3 lives in our tree as research probes; productising it into the runtime is
the follow-on engineering track, not a build you can be sold today. Nothing about the
tree you just downloaded expires or degrades if that never ships.

The intent is that it adds Profile 3, applied auto-tuning rather than advisory, and
per-workload engineering. The honest pitch: the kernel is not the moat and we will not
pretend otherwise — what you would be buying is the fit work and the larger arm set.

If the reproduction kit says HST does not fit your workload, we would rather you
found that out here, for free, than six weeks into a pilot. We have told prospects no
before and we will again.

**HorneSci Research**
