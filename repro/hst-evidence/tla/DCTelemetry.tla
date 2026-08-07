-------------------------- MODULE DCTelemetry --------------------------
(***************************************************************************)
(* Data-center telemetry hierarchy as an HST-style delta-propagation      *)
(* system, and the correctness property that delta propagation touching   *)
(* ONLY affected paths keeps every aggregate bit-identical to a full       *)
(* recompute.                                                              *)
(*                                                                         *)
(* Topology (fixed for the whole run):                                     *)
(*                                                                         *)
(*        facility                                                         *)
(*        /      \                                                         *)
(*      ra        rb            (racks)                                    *)
(*     /  \      /  \                                                      *)
(*    s1  s2    s3  s4          (servers = leaf sensors)                   *)
(*                                                                         *)
(* A concrete 2x2 tree is used so the whole state space is finite for TLC  *)
(* / Apalache and the parity proof is pure arithmetic for TLAPS.  Adding   *)
(* the aisle level, more racks, or more servers is the identical pattern   *)
(* (each internal node = sum of its children); the C++ harness             *)
(* probes/hst_dc_telemetry.cpp exercises the thousands-of-node scale.       *)
(*                                                                         *)
(* Model is ASYNCHRONOUS: a reading change marks its rack (and the         *)
(* facility) STALE; separate propagation actions recompute exactly the     *)
(* touched internal nodes from their children.  This makes the liveness    *)
(* property ("every disturbance eventually settles to an exact state")     *)
(* non-trivial: without fairness on propagation the system can stall.      *)
(***************************************************************************)
EXTENDS Integers, FiniteSets

(* ---- fixed topology (definitions, not CONSTANTS: no config needed) ---- *)
Servers == {"s1", "s2", "s3", "s4"}
Racks   == {"ra", "rb"}
RackOf  == [s \in Servers |-> IF s \in {"s1", "s2"} THEN "ra" ELSE "rb"]
\* @type: (Str) => Set(Str);
ServersOf(r) == {s \in Servers : RackOf[s] = r}
MaxVal  == 3                     \* reading domain 0..MaxVal (bounds the model)

(* ---- ground truth: what a FULL recompute would produce ---- *)
(* Explicit arithmetic (no folds/recursion) so all four tools agree.      *)
\* @type: (Str -> Int, Str) => Int;
TrueRack(rd, r) == IF r = "ra" THEN rd["s1"] + rd["s2"]
                              ELSE rd["s3"] + rd["s4"]
\* @type: (Str -> Int) => Int;
TrueFac(rd)     == TrueRack(rd, "ra") + TrueRack(rd, "rb")

VARIABLES
    \* @type: Str -> Int;
    reading,    \* current leaf sensor readings
    \* @type: Str -> Int;
    rackAgg,    \* materialized rack aggregates (HST-maintained)
    \* @type: Int;
    facAgg,     \* materialized facility total
    \* @type: Set(Str);
    dirtyR,     \* racks whose aggregate is stale
    \* @type: Bool;
    facStale,   \* facility total is stale
    \* @type: Bool;
    active      \* environment still injecting deltas

vars == << reading, rackAgg, facAgg, dirtyR, facStale, active >>

TypeOK ==
    /\ reading \in [Servers -> 0..MaxVal]
    /\ rackAgg \in [Racks -> Nat]
    /\ facAgg  \in Nat
    /\ dirtyR  \in SUBSET Racks
    /\ facStale \in BOOLEAN
    /\ active   \in BOOLEAN

Init ==
    /\ reading  = [s \in Servers |-> 0]
    /\ rackAgg  = [r \in Racks |-> 0]
    /\ facAgg   = 0
    /\ dirtyR   = {}
    /\ facStale = FALSE
    /\ active   = TRUE

(* Environment: a sensor reading changes.  Only the affected rack and the  *)
(* facility become stale -- this is the "sparse delta" arriving.           *)
Change(s, v) ==
    /\ active
    /\ v \in 0..MaxVal
    /\ v # reading[s]
    /\ reading'  = [reading EXCEPT ![s] = v]
    /\ dirtyR'   = dirtyR \cup {RackOf[s]}
    /\ facStale' = TRUE
    /\ UNCHANGED << rackAgg, facAgg, active >>

(* The input stream eventually quiesces (weakly fair): real telemetry      *)
(* deltas arrive as long as the environment is active, but liveness of     *)
(* "the tree settles" is only meaningful once perturbation stops -- you     *)
(* cannot be globally consistent while inputs never cease.                 *)
Quiesce ==
    /\ active
    /\ active' = FALSE
    /\ UNCHANGED << reading, rackAgg, facAgg, dirtyR, facStale >>

(* HST: recompute ONE stale rack's aggregate from its own servers.         *)
(* This is the affected-path touch -- clean racks are never revisited.     *)
PropagateRack(r) ==
    /\ r \in dirtyR
    /\ rackAgg'  = [rackAgg EXCEPT ![r] = TrueRack(reading, r)]
    /\ dirtyR'   = dirtyR \ {r}
    /\ facStale' = TRUE
    /\ UNCHANGED << reading, facAgg, active >>

(* HST: once every rack is clean, roll the facility up from rack aggs.      *)
PropagateFac ==
    /\ facStale
    /\ dirtyR = {}
    /\ facAgg'   = rackAgg["ra"] + rackAgg["rb"]
    /\ facStale' = FALSE
    /\ UNCHANGED << reading, rackAgg, dirtyR, active >>

Next ==
    \/ \E s \in Servers, v \in 0..MaxVal : Change(s, v)
    \/ \E r \in Racks : PropagateRack(r)
    \/ PropagateFac
    \/ Quiesce

Fairness ==
    /\ \A r \in Racks : WF_vars(PropagateRack(r))
    /\ WF_vars(PropagateFac)
    /\ WF_vars(Quiesce)

Spec == Init /\ [][Next]_vars /\ Fairness

\* Same system WITHOUT fairness -- used only to demonstrate that the        *)
\* temporal properties genuinely depend on fairness (they must FAIL here).  *)
SpecNoFair == Init /\ [][Next]_vars

(* =====================  CORRECTNESS PROPERTIES  ===================== *)

(* SAFETY 1: any rack NOT currently stale has an exact aggregate.          *)
RackParity == \A r \in Racks : (r \notin dirtyR) => (rackAgg[r] = TrueRack(reading, r))

(* The system is fully settled. *)
Consistent == (dirtyR = {}) /\ (~facStale)

(* SAFETY 2: when fully settled, the facility aggregate equals a full      *)
(* recompute over ALL leaves -- i.e. delta propagation == full rebuild.    *)
FacParity == Consistent => (facAgg = TrueFac(reading))

Inv == TypeOK /\ RackParity /\ FacParity

(* LIVENESS.  All hold under Fairness and FAIL if the matching WF_ is       *)
(* dropped, so none is vacuous.                                            *)
(*   RackFixed - every stale rack eventually gets its exact aggregate      *)
(*               (holds under WF(PropagateRack), independent of quiescence) *)
(*   Progress  - any disturbed state eventually reaches full consistency    *)
(*   Stabilizes- the tree eventually stays consistent forever (after the    *)
(*               input stream quiesces): delta propagation converges to a   *)
(*               state bit-identical to a full recompute                    *)
RackFixed  == \A r \in Racks : (r \in dirtyR) ~> (rackAgg[r] = TrueRack(reading, r))
Progress   == (dirtyR # {}) ~> Consistent
Stabilizes == <>[]Consistent
Liveness   == []<>Consistent

(* =====================  NON-VACUITY WITNESSES  =====================     *)
(* Each is intended to be VIOLATED by TLC; the counterexample is a         *)
(* concrete reachable state proving the guarded implications above are     *)
(* exercised on non-trivial states (not vacuously true).                   *)

(* Expect VIOLATION: a non-settled state is reachable (so Consistent is    *)
(* not always true -> Liveness/Progress antecedents actually fire).        *)
W_InconsistentReachable == Consistent

(* Expect VIOLATION: a CLEAN rack with a NON-ZERO exact aggregate is       *)
(* reachable (so RackParity constrains real data, not just zeros).         *)
W_CleanNonzeroReachable == \A r \in Racks : (r \in dirtyR) \/ (rackAgg[r] = 0)

(* Expect VIOLATION: a settled state with a NON-ZERO facility total is     *)
(* reachable (so FacParity is exercised on non-trivial totals).            *)
W_SettledNonzeroReachable == ~(Consistent /\ facAgg > 0)
=============================================================================
