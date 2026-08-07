-------------------------- MODULE BatchParallelApply --------------------------
\* Formal model of the BATCH-PARALLEL delta-apply strategy: the concurrency
\* argument on its own, independent of any implementation.
\* The spec is self-contained -- it needs no source to check.
\*
\* The B batch vectors are partitioned across T worker threads. Each worker owns
\* a DISJOINT block of the output (the columns b with owner(b) = w) and writes
\* only those. Because ownership is disjoint, there are no shared writes, no
\* locks, and no reduction -- the "embarrassingly parallel" path.
\*
\* TLC checks, over every interleaving of the workers:
\*   NoWriteConflict    -- no output cell is written more than once
\*   OwnershipRespected -- a written cell was written exactly once, by its owner
\*   Correct            -- when all workers finish, output == sequential result
\*
\* This is the formal complement to a bit-exact assert in an implementation;
\* the corresponding harness is not part of this release.
\*
\* Run:  java -cp /opt/tla/tla2tools.jar tlc2.TLC \
\*            -config BatchParallelApply.cfg BatchParallelApply.tla
\*===============================================================================
EXTENDS Naturals

CONSTANTS B,   \* number of batch vectors (output columns)
          T    \* number of worker threads

ASSUME B \in Nat /\ T \in Nat /\ T >= 1 /\ B >= 1

Workers == 0 .. (T - 1)
Cols    == 0 .. (B - 1)

owner(b)    == b % T            \* round-robin static partition
Expected(b) == b + 1            \* deterministic per-column "result" (nonzero)

VARIABLES
  y,       \* y[b]      : value written to output column b (0 = unwritten)
  writes,  \* writes[b] : number of times column b has been written
  done     \* done[w]   : TRUE once worker w has written all of its columns

vars == << y, writes, done >>

Init ==
  /\ y      = [b \in Cols |-> 0]
  /\ writes = [b \in Cols |-> 0]
  /\ done   = [w \in Workers |-> FALSE]

\* A worker writes one of its own, not-yet-written columns.
WriteCol(w, b) ==
  /\ owner(b) = w
  /\ y[b] = 0
  /\ y'      = [y      EXCEPT ![b] = Expected(b)]
  /\ writes' = [writes EXCEPT ![b] = @ + 1]
  /\ UNCHANGED done

\* A worker marks itself done once all of its columns are written.
MarkDone(w) ==
  /\ ~done[w]
  /\ \A b \in Cols : owner(b) = w => y[b] # 0
  /\ done' = [done EXCEPT ![w] = TRUE]
  /\ UNCHANGED << y, writes >>

AllDone == \A w \in Workers : done[w]

Next ==
  \/ \E w \in Workers, b \in Cols : WriteCol(w, b)
  \/ \E w \in Workers : MarkDone(w)
  \/ AllDone /\ UNCHANGED vars        \* stutter once finished (no deadlock)

Spec == Init /\ [][Next]_vars

\* ---- invariants -------------------------------------------------------------
TypeOK ==
  /\ y      \in [Cols -> Nat]
  /\ writes \in [Cols -> Nat]
  /\ done   \in [Workers -> BOOLEAN]

NoWriteConflict    == \A b \in Cols : writes[b] <= 1
OwnershipRespected == \A b \in Cols : y[b] # 0 => writes[b] = 1
Correct            == AllDone => \A b \in Cols : y[b] = Expected(b)
===============================================================================
