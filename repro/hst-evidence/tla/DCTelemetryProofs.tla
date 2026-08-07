----------------------- MODULE DCTelemetryProofs -----------------------
(***************************************************************************)
(* Machine-checked TLAPS proof that the HST delta-propagation invariant    *)
(* Inv (TypeOK /\ RackParity /\ FacParity) is inductive, hence Spec=>[]Inv. *)
(*                                                                         *)
(* RackParity+FacParity together say: every materialized aggregate that is  *)
(* not currently flagged stale equals a full recompute over the leaves --   *)
(* i.e. touching only affected paths is bit-identical to rebuilding.        *)
(*                                                                         *)
(* Check with:  tlapm DCTelemetryProofs.tla                                 *)
(***************************************************************************)
EXTENDS DCTelemetry, TLAPS

THEOREM Safety == Spec => []Inv
<1>1. Init => Inv
  BY SMT DEF Init, Inv, TypeOK, RackParity, FacParity, Consistent,
             TrueRack, TrueFac, Racks, Servers, MaxVal
<1>2. Inv /\ [Next]_vars => Inv'
  <2> SUFFICES ASSUME Inv, [Next]_vars PROVE Inv' OBVIOUS
  <2> USE DEF Inv, TypeOK, RackParity, FacParity, Consistent,
              Servers, Racks, RackOf, ServersOf, TrueRack, TrueFac, MaxVal
  <2>1. ASSUME NEW s \in Servers, NEW v \in 0..MaxVal, Change(s, v)
        PROVE Inv'
    BY <2>1 DEF Change
  <2>2. ASSUME NEW r \in Racks, PropagateRack(r)
        PROVE Inv'
    BY <2>2 DEF PropagateRack
  <2>3. ASSUME PropagateFac
        PROVE Inv'
    BY <2>3 DEF PropagateFac
  <2>4. ASSUME Quiesce
        PROVE Inv'
    BY <2>4 DEF Quiesce
  <2>5. CASE UNCHANGED vars
    BY <2>5 DEF vars
  <2>6. QED
    BY <2>1, <2>2, <2>3, <2>4, <2>5 DEF Next
<1>3. QED
  BY <1>1, <1>2, PTL DEF Spec
=============================================================================
