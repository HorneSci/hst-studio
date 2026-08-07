# hst-evidence — golden vectors, bit-exactness probes, and formal specs

Three things you can check yourself, and a careful statement of what each one
does not show.

1. **Golden vectors.** Twelve `(A, x0, dx-schedule, y)` tuples with a reference
   implementation in Python *and* C, so you can validate **any** delta-update
   implementation — yours or ours — without running ours.
2. **Bit-exactness probes.** Two self-contained C++ programs that assert
   byte-identical output against independently written full-recompute
   baselines, and gate their exit codes on it.
3. **Formal specs.** TLA+ models with a machine-checked TLAPS proof, paired
   with the probe that asserts the same property in running code.

Everything here is public domain (CC0 1.0) unless a file says otherwise. No
dependencies: the Python needs only the standard library, the C needs only
libc and libm, the C++ needs only C++17.

**grade**, used throughout below, is defined in the shared
[`../GLOSSARY.md`](../GLOSSARY.md) (covering this package and its four
siblings) — short version: it is a strictness label, not a correctness
ranking, and the section below on the two grades explains why that
distinction matters here specifically.

---

## Run this first

```bash
python3 tools/fetch_matrices.py --out matrices          # provenance -> local .mtx
python3 tools/verify_cases.py --matrices matrices       # Python reference round-trip

make -C reference                                        # C reference, flags pinned
./reference/reference_spmv matrices/bcspwr09.mtx cases/INT-01

make -C probes CXX=g++-13 check                          # name your compiler
./tla/run_tlc.sh                                          # needs java
```

> **The single most actionable fact in this file: FMA will silently fail the
> f64 cases.** `make -C reference` already pins `-ffp-contract=off`, so the
> command above is safe as written. But if you ever compile
> `reference/reference_spmv.c` yourself — outside this Makefile, integrating
> it into your own build — and drop that flag, Apple clang on arm64 fails
> **five of the twelve f64 cases** (last-bit drift from a fused multiply-add,
> `rel_l2` around 1e-16) while Homebrew GCC passes regardless. Same source,
> same summation order, different last bits. Full measurement and the table
> of which cases fail: "A measured warning about the f64 cases," below.

Read the caveats in the next section before trusting any of the above — they
are short, and they say what this repository does **not** prove. (Jump to:
[golden vectors](#1-golden-vectors) · [probes](#2-bit-exactness-probes) ·
[formal specs](#3-formal-specs).)

---

## READ THIS FIRST: what this repository does NOT prove

We would rather say this ourselves than have you discover it.

**The two probes do not exercise a sparse mat-vec kernel.** One is a grid
wavefront. The other is a tree aggregator. Neither links, calls, or contains a
sparse linear-algebra runtime. They are strong evidence for exactly one claim —
*delta propagation over an exactly-determined dirty set is exact* — and they
are **zero evidence about the performance or correctness of any product**. If
you are trying to decide whether some sparse runtime is fast, these two
programs are not the artifact you want, and no arrangement of their numbers
will become that artifact.

**The golden vectors are the part that is about sparse mat-vec**, and they are
deliberately implementation-neutral. They pin down what the right answer *is*.
They say nothing about how quickly anyone reaches it. **The golden vectors
carry not a single timing claim.** That is on purpose: a timing number without
its baseline, its motion model, its churn rate, its toolchain and its control
is not a result, and this set does not carry those conditions.

**The two bit-exactness probes are a different thing, and they do print
numbers.** `make -C probes check` (§2, below) builds
`hst_dc_telemetry`, and its exit code depends only on bit-exact parity — but
before it exits, it also prints a latency ratio and a combine-op ("energy
proxy") ratio, because a probe that gates on doing the work has a timer
sitting right there regardless. Read those numbers as **diagnostic**, not as
a claim: one host, one process, no baseline arm, no repeats, no churn sweep —
none of the five conditions above. The probe's own output says so directly
("a modeled proxy \[...], not a RAPL measurement"); the one number in that
block that *is* platform-independent is the touched-node ratio, because it
counts work, not time. If you want to quote a timing number from this
project, this is not where it comes from — see `hst-measurement` in the
parent repo for what a timing claim needs.

**GRADE-A on a floating-point case is a strictness test, not a correctness
test.** A perfectly correct implementation that sums in a different order will
fail it. See the grades section below; we measured how badly, and published the
numbers.

**The formal specs prove properties of the models**, which are small by design
(a 2×2 tree; a handful of workers). A proof about a model is a proof about the
model. What makes the DCTelemetry pairing worth something is that the same
property is *also* asserted bit-exactly in running code at a scale the model
cannot reach — spec, machine-checked proof, and implementation check, agreeing.

**Some cases lose, and they are published for that reason.** `ADV-01` and
`ADV-02` dirty 85% and 70% of all columns with a fresh random scatter every
step. That is the regime a delta approach is supposed to be bad in. A golden
vector set containing only the flattering cells would not be evidence of
anything.

---

## 1. Golden vectors

```
cases/<id>/
  manifest.json    everything needed to regenerate y, and the grade it is judged at
  SHA256SUMS       the hashes the three .bin files below must have
  dx.bin           the delta schedule (documented format, below)      ┐ generated,
  y0.f64.bin       A @ x0            -- shape [rows, batch], LE f64   │ not
  y.f64.bin        y after each step -- shape [steps, rows, batch]    ┘ redistributed
```

**The three `.bin` files are generated, not shipped.** A distributed copy of this
package carries the manifests and the checksums and no vector bytes — the same
treatment the operator gets one paragraph down, for the same reason, and it means
the file set is identical however you obtained this tree. Rebuild them:

```bash
python3 tools/fetch_matrices.py --out matrices     # public SuiteSparse .mtx, hash-checked
python3 tools/gen_cases.py --manifest cases.public.json --matrices matrices
```

`SHA256SUMS` is what makes that a check rather than a copy: if your regenerated
bytes hash to what the manifest says, you have reproduced our vectors on your
machine, which is worth more than receiving them.

**The operator is provenance, not payload.** We do not redistribute matrix
bytes. Each manifest names a SuiteSparse group, matrix, URL and the **sha256 of
the exact `.mtx`** the case was generated from. `tools/fetch_matrices.py` turns
that back into a local file and the verifier checks the hash before it checks
anything else.

### The twelve cases

| case | grade | operator | rows | nnz | batch | motion | dirty |
|---|---|---|---|---|---|---|---|
| INT-01 | GRADE-A int | HB/bcspwr09 | 1723 | 6511 | 1 | frozen | 2% |
| INT-02 | GRADE-A int | HB/bcspwr10 | 5300 | 21842 | 1 | drift | 2% |
| INT-03 | GRADE-A int | Hamm/add32 | 4960 | 23884 | 4 | drift | 5% |
| INT-04 | GRADE-A int | Nasa/nasa2910 | 2910 | 174296 | 1 | drift | 10% |
| INT-05 | GRADE-A int | Rajat/rajat03 | 7602 | 32653 | 8 | drift | 5% |
| INT-06 | GRADE-A int | HB/bcspwr10 | 5300 | 21842 | 4 | scattered | 5% |
| F64-01 | GRADE-A f64 | HB/bcspwr09 | 1723 | 6511 | 1 | drift | 2% |
| F64-02 | GRADE-A f64 | Hamm/add32 | 4960 | 23884 | 1 | drift | 5% |
| F64-03 | GRADE-A f64 | Nasa/nasa2910 | 2910 | 174296 | 1 | frozen | 5% |
| F64-04 | GRADE-A f64 | Rajat/rajat03 | 7602 | 32653 | 4 | drift | 5% |
| **ADV-01** | GRADE-B | Hamm/memplus | 17758 | 126150 | 1 | scattered | **85%** |
| **ADV-02** | GRADE-B | Nasa/nasa2910 | 2910 | 174296 | 4 | scattered | **70%** |

`nnz` is after the stated preprocessing, which expands a symmetric Matrix
Market file into both triangles. Six steps per case.

### The two grades, honestly

**GRADE-A — byte-identical.** Every f64 in the shipped `y` must match bit for
bit. This is only achievable because the summation order is written down (see
`reference.summation_order` in every manifest), and it means a correct
implementation using a different order **will fail**. It is a strictness test.

We did not assert that; we measured it. Re-running each case with a row-major
summation order instead of the specified column-major one moves this many f64
values:

| case | f64s differing under a different, equally correct order |
|---|---|
| INT-01 … INT-06 | **0** |
| F64-01 | 9 |
| F64-02 | 314 |
| F64-03 | 7098 |
| F64-04 | 2452 |
| ADV-01 | 60783 |
| ADV-02 | 59551 |

**GRADE-B — `rel_l2 <= bound`, published per case.** The bound is calibrated,
not chosen: it is the measured disagreement between those two legitimate
summation orders on that exact case, times a 10× margin, floored at 1e-12. A
tolerance derived from the data it judges.

### Start with the integer cases — they are the strongest object here

The six `INT-*` cases assign small integer values by a stated rule
(`A[i,j] = 1 + ((i + 3j) mod 5)`, discarding the stored values), with integer
`x0` and integer `dx`. The generator asserts

```
max_i sum_j |A[i,j]| * (max|x0| + steps * max|dx|)  <  2^53
```

so every partial sum is an integer that f64 represents exactly, and **no
addition in the entire computation rounds**. Bit-equality therefore holds
regardless of summation order, compiler, or vectorization. GRADE-A becomes
order-independent, and the strictness caveat above simply does not apply.

These cost nothing extra to produce and they are the only cases a correct
implementation cannot fail for a benign reason. If you are checking one thing,
check these.

### A measured warning about the f64 cases: FMA will fail them

This bit us while building the artifact, so it is here rather than in a
footnote. Compiling the C reference at `-O2` **without** `-ffp-contract=off`:

| toolchain | INT-01..06 | F64-01 | F64-02 | F64-03 | F64-04 | ADV-01 | ADV-02 |
|---|---|---|---|---|---|---|---|
| Apple clang 17.0.0, arm64 | pass | pass | **fail** | **fail** | **fail** | **fail** | **fail** |
| Homebrew GCC 13.4.0, arm64 | pass | pass | pass | pass | pass | pass | pass |

Same source. Same summation order. Apple clang contracts `y[i] += a * x[j]`
into a fused multiply-add, which rounds once where the spec rounds twice, and
every f64 GRADE-A case moves in its last bits (`rel_l2` around 1e-16). Adding
`-ffp-contract=off` makes both toolchains bit-identical on all twelve. It is in
`reference/Makefile` for that reason.

The integer cases pass under both compilers, with and without the flag. That
contrast *is* the argument.

F64-01 survives FMA only because `bcspwr09` is a `pattern` matrix: every value
is 1.0, so the multiply is exact and contraction changes nothing. Do not read
that as the f64 cases being robust.

### Verifying

```bash
python3 tools/fetch_matrices.py --out matrices          # provenance -> local .mtx
python3 tools/gen_cases.py --manifest cases.public.json --matrices matrices
                                                        # writes cases/*/[dx|y0|y].bin
python3 tools/verify_cases.py --matrices matrices       # Python reference round-trip

make -C reference                                        # C reference, flags pinned
./reference/reference_spmv matrices/bcspwr09.mtx cases/INT-01
```

The generation step is not optional in a distributed copy: the `.bin` files are
generated rather than redistributed, so without it the verifier has manifests and
checksums and no bytes to check them against.

The verifier checks four things, in the order in which a failure would tell you
the most: the case bytes match `SHA256SUMS` and the operator matches its
pinned sha256; the reference reproduces `y0` and every step at the stated grade;
a *different* summation order behaves the way the grade claims it should (still
bit-identical for the integer cases, not bit-identical for the f64 GRADE-A
ones); and `dx.bin` round-trips through its own documented format with sorted,
unique dirty columns.

**Skip the fetch and the verifier fails.** A case whose operator `.mtx` is not
on disk can only be SKIPped, and the summary says so in as many words —
`12 of 12 verified, 0 skipped, 0 failing`, never a bare "0 failing". By default
every case must be verified; anything less exits **2** and names the fetch. That
default is not politeness. The twelve cases cover different things — integer
against f64, order-independent against order-sensitive — so a partial fetch
proves a partial claim, and if that is what you want you say so:

```bash
python3 tools/verify_cases.py --matrices matrices --require-verified 4
```

| exit | meaning |
|---|---|
| 0 | every required case verified, none failing |
| 1 | a case failed: bytes, round trip, order contrast or `dx.bin` format |
| 2 | not enough cases verified (usually a missing fetch), or a usage error |

### `dx.bin` format

Little-endian throughout.

```
offset  size          field
0       8             magic "GVDX0001"
8       4             version = 1
12      4             steps
16      4             cols            (columns of A; dirty indices are into this)
20      4             batch
24      4             dtype           (0 = f64)
28      4             reserved = 0
32      ...           per step:
                        uint32  k                    dirty column count
                        uint32  cols[k]              ascending, unique
                        f64     vals[k * batch]      position-major, then batch lane
```

### The reference implementations

`reference/reference_spmv.py` and `reference/reference_spmv.c` are independent
implementations of the same spec, in two languages. Both are public domain and
both are short enough to read in full. The kernels are the first ~25 lines of
each file; the rest is Matrix Market parsing and file I/O.

They exist so that the golden vectors are not checked only by the program that
wrote them. All twelve cases are confirmed under both languages and both
compilers named above.

Everything a manifest *names* — the preprocessing rule, the `x0` generator, the
SplitMix64 PRNG, the delta-schedule generator — is implemented in the
reference. The manifest is executable, not aspirational.

---

## 2. Bit-exactness probes

```bash
make -C probes CXX=g++-13 check
```

Name your compiler. On macOS `g++` and `cc` are Apple clang, not GCC.

`hst_dc_telemetry`'s exit code is bit-exact parity, and only that — but its
summary block also prints a latency ratio and a combine-op ratio along the
way, since a probe already timing itself for the parity gate has the numbers
on hand. Those are diagnostic, from one host and one run, not a claim (see
"READ THIS FIRST," above): no baseline arm, no repeats, none of a claim's
five conditions. The touched-node ratio in the same block is the one
platform-independent number there, because it counts work, not wall time.

**`probes/hst_wavefront_exact_probe.cpp`** — a front propagates across a
512×512 grid with a per-cell traversal cost. Three independently written
algorithms compute the same integer `arrival_step[]`: Bellman-Ford full-grid
relaxation, Dial's bucket-queue Dijkstra, and a tile-scheduled frontier. The
output is integer, so agreement is bit-equality with no tolerance anywhere. The
exit code gates on both comparisons.

**`probes/hst_dc_telemetry.cpp`** — a fixed
`sensors → servers → racks → aisles → facility` hierarchy, 2304 servers, four
metrics, SUM and MAX aggregations. A full recompute and an affected-path delta
propagation run as two independent copies, and parity is checked **bit-exactly
at every one of 400 steps**, across scripted disturbances. Any parity failure at
any step returns 1.

Two details in that probe are worth copying if you write harnesses:

- **The frozen control is real.** `./hst_dc_telemetry 0 400` asserts that zero
  leaves are dirtied per step rather than flooring to one. A "frozen" cell that
  is not actually frozen reports a speedup in the one regime where the method is
  documented to lose.
- **Arm order is rotated per step**, seeded off the step index so reruns
  reproduce, because whichever arm runs second inherits the cache and TLB state
  the first one left.
- **Its arguments are validated, and `make check` asserts that they are.**
  `./hst_dc_telemetry banana -5` used to run to completion and exit 0 having
  performed zero parity checks: `atof`/`atoi` return 0 on garbage with no way to
  say they did, so churn became 0.0, steps became -5, and the loop body never
  executed. Churn must be a number in `0.0–1.0` (5 is not 5%, it is 500%), steps
  a positive integer, locality a number in `0.0–1.0`; anything else prints the
  usage and exits **2**. Exit 1 stays reserved for a parity failure, so the two
  are never confused.

**`probes/include/assert_rel.hpp`** is the plumbing that makes those exit codes
mean something: `hst_check_rel(tag, rel, tol)` and `hst_check(tag, ok)` record
and print, `hst_checks_exit()` is what `main` returns. It exists because a check
that does not gate the exit code is a check on paper — a harness can print the
word FAIL and still exit 0.

We do not ship run outputs. The contract is the exit code, and you get it by
running the program.

---

## 3. Formal specs

```bash
./tla/run_tlc.sh          # needs java; fetches tla2tools.jar if you have none
```

**`tla/DCTelemetry.tla`** is the one to look at, because it is paired. The same
property — propagating a sparse delta over only the affected paths is identical
to a full recompute — appears three ways:

- a TLA+ model, checked by TLC over 426,496 distinct states (safety invariant
  plus four temporal properties under fairness),
- a machine-checked TLAPS proof that the invariant is inductive
  (`DCTelemetryProofs.tla`, 23 obligations, z3 backend),
- and the bit-exact assertion in `probes/hst_dc_telemetry.cpp` at a scale the
  model cannot reach.

`tla/DCTelemetry_README.md` has the tool versions, the four-tool results, and
the non-vacuity evidence — witness invariants that TLC is *supposed* to
violate, proving the guarded invariants are exercised on non-trivial states
rather than holding vacuously, plus a no-fairness variant in which the liveness
properties genuinely fail.

**`tla/ColumnParallelApply.tla`** and **`tla/BatchParallelApply.tla`** are
concurrency models: disjoint-ownership batch parallelism needs no reduction,
column parallelism does, and the `naive` configuration exists to produce the
lost-update counterexample on demand. That counterexample is regenerated by
`run_tlc.sh` rather than shipped — a committed binary trace is build output, not
evidence a reader can check.

We verified all four configurations behave as documented before release.

---

## Public and private variants

Every tuning decision here is a **configuration, not a fork**. `cases.public.json`
is the only thing that decides which cases exist, which operators they use,
which grade each carries and which are adversarial; `tools/gen_cases.py` reads
it via `--manifest` and contains no case list. A private superset is a second
manifest file against the same generator and the same reference.

`tools/gen_cases.py` also enforces an **allowlist** on every field that reaches
a shipped manifest — a field cannot appear unless it is named in `ALLOWED_KEYS`.
This is deliberately an allowlist and not a denylist, because the disclosure
risk in a data file is the *data*, not the identifiers: a triple of per-arm work
counts contains no forbidden word and still pins an internal layout by its
ratios. Adding a field to a published manifest is a decision someone has to make
on purpose.

## Layout

```
README.md                  this file
cases.public.json          the manifest that decides the public case set
cases/<id>/                the golden vectors
reference/                 reference_spmv.py, reference_spmv.c, Makefile
tools/                     fetch_matrices.py, gen_cases.py, verify_cases.py, altorder.py
probes/                    the two bit-exactness probes + assert_rel.hpp + Makefile
tla/                       the specs, the proof, run_tlc.sh
```
