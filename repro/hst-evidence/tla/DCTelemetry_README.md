# DCTelemetry — formally verified HST delta-propagation

A TLA+ model of the data-center telemetry hierarchy
(`sensors → servers → racks → facility`) as an HST-style delta-propagation
system, with the correctness property that **propagating a sparse delta over
only the affected paths is bit-identical to a full recompute of every
aggregate**. Companion to the scale benchmark in
[`../probes/hst_dc_telemetry.cpp`](../probes/hst_dc_telemetry.cpp).

The model is **asynchronous**: a reading change flags its rack (and the
facility) stale; separate propagation actions recompute exactly the touched
internal nodes from their children. A weakly-fair `Quiesce` action lets the
input stream eventually stop, which is what makes "the tree settles" a
meaningful liveness property (you cannot be globally consistent while inputs
never cease).

Concrete 2×2 tree (finite state space for TLC/Apalache, pure-arithmetic
obligations for TLAPS). Extra racks / servers / the aisle level are the
identical pattern; the C++ harness covers the thousands-of-node scale.

## Properties

Safety (`Inv`, proven inductive):
- `TypeOK`
- `RackParity` — any rack not flagged stale has an exact aggregate
- `FacParity` — when fully settled, the facility total equals a full recompute

Liveness (all fail if the matching `WF_` is dropped → non-vacuous):
- `RackFixed` — every stale rack eventually gets its exact aggregate
- `Progress`  — any disturbed state eventually reaches full consistency
- `Stabilizes`/`Liveness` — the tree eventually stays consistent forever

## All four tools pass

| Tool     | What it checks | Result |
|----------|----------------|--------|
| **SANY** | parse + semantics | clean |
| **TLC**  | `Inv` + 4 temporal props under fairness | 426,496 distinct states, no error |
| **Apalache** | typecheck; `Init⇒Inv` and `Inv∧Next⇒Inv'` (inductive, unbounded) | NoError |
| **TLAPS** | `Spec ⇒ []Inv` (machine-checked, z3 backend) | all 23 obligations proved |

### Non-vacuity evidence (not just "vacuously true")
- Witness invariants `W_InconsistentReachable`, `W_CleanNonzeroReachable`,
  `W_SettledNonzeroReachable` are each **VIOLATED** by TLC → the guarded
  invariants are exercised on non-trivial states, and the temporal antecedents
  actually fire.
- `Liveness` under `SpecNoFair` (no fairness) is **VIOLATED** → the temporal
  properties genuinely depend on fairness; they have teeth.

## Reproduce

```bash
TLA=/opt/tla/tla2tools.jar
APA=~/tools/apalache-0.58.3/bin/apalache-mc
TLAPM=~/tools/tlapm/bin/tlapm

# SANY
java -cp $TLA tla2sany.SANY DCTelemetry.tla

# TLC (safety + temporal)
java -cp $TLA tlc2.TLC -config DCTelemetry.cfg DCTelemetry.tla

# Apalache: typecheck + inductive invariant proof
$APA typecheck DCTelemetry.tla
$APA check --init=Init --inv=Inv --length=0 DCTelemetry.tla    # base case
$APA check --init=Inv  --inv=Inv --length=1 DCTelemetry.tla    # inductive step

# TLAPS
$TLAPM DCTelemetryProofs.tla
```

Tool versions used: tla2tools (SANY 2.2 / TLC2), Apalache 0.58.3,
TLAPS 1.6.0-pre (arm64-darwin, OCaml 5.1.0, z3 backend).
