-------------------------- MODULE ColumnParallelApply --------------------------
\* Formal model of the COLUMN-PARALLEL delta-apply strategy: the concurrency
\* argument on its own, independent of any implementation.
\* The spec is self-contained -- it needs no source to check.
\*
\* When you split the work by COLUMN, several workers contribute to the SAME
\* output cell, so the contributions must be combined. Two ways to do it:
\*
\*   Mode = "safe"  : each worker accumulates into its OWN private partial, then
\*                    a single reduction sums the partials into Y. Correct.
\*   Mode = "naive" : workers add straight into shared Y with a non-atomic
\*                    read-modify-write (read Y; later write reg+1). RACY.
\*
\* This is the customer's point made precise: "when parallelizing by column you
\* have to do a reduction on the resulting vector at the end." The "safe" reduction
\* is what makes it correct; skipping it (the "naive" mode) loses updates.
\*
\* TLC result:
\*   safe  -> No errors found (Correct holds for every interleaving)
\*   naive -> Correct is VIOLATED; TLC returns a lost-update counterexample.
\*            (That violation is the EXPECTED, instructive outcome.)
\*
\* Run:  java -cp /opt/tla/tla2tools.jar tlc2.TLC \
\*            -config ColumnParallelApply_safe.cfg  ColumnParallelApply.tla
\*       java -cp /opt/tla/tla2tools.jar tlc2.TLC \
\*            -config ColumnParallelApply_naive.cfg ColumnParallelApply.tla
\*===============================================================================
EXTENDS Naturals, FiniteSets

CONSTANTS K,     \* number of dirty columns, each contributing 1 to the output cell
          T,     \* number of worker threads
          Mode   \* "safe" or "naive"

ASSUME K \in Nat /\ T \in Nat /\ T >= 1 /\ K >= 1 /\ Mode \in {"safe", "naive"}

Workers   == 0 .. (T - 1)
ColsOf(w) == { k \in 0 .. (K - 1) : k % T = w }   \* columns owned by worker w
Expected  == K                                    \* sum of all contributions

\* sum of f over the worker set (used to reduce the private partials)
RECURSIVE SumSet(_, _)
SumSet(f, S) ==
  IF S = {} THEN 0
  ELSE LET x == CHOOSE e \in S : TRUE IN f[x] + SumSet(f, S \ {x})

VARIABLES
  Y,         \* shared output cell
  partial,   \* partial[w] : private partial sum for worker w  (safe mode)
  remaining, \* remaining[w]: owned columns not yet processed
  reg,       \* reg[w]     : value a worker read from Y         (naive RMW)
  reading,   \* reading[w] : TRUE between a worker's read and its write (naive)
  reduced    \* TRUE once the safe-mode reduction has executed

vars == << Y, partial, remaining, reg, reading, reduced >>

Init ==
  /\ Y         = 0
  /\ partial   = [w \in Workers |-> 0]
  /\ remaining = [w \in Workers |-> Cardinality(ColsOf(w))]
  /\ reg       = [w \in Workers |-> 0]
  /\ reading   = [w \in Workers |-> FALSE]
  /\ reduced   = FALSE

AllConsumed == \A w \in Workers : remaining[w] = 0

\* ---- safe mode: accumulate into a private partial, then reduce --------------
SafeStep(w) ==
  /\ Mode = "safe"
  /\ remaining[w] > 0
  /\ partial'   = [partial   EXCEPT ![w] = @ + 1]
  /\ remaining' = [remaining EXCEPT ![w] = @ - 1]
  /\ UNCHANGED << Y, reg, reading, reduced >>

Reduce ==
  /\ Mode = "safe"
  /\ AllConsumed
  /\ ~reduced
  /\ Y'       = SumSet(partial, Workers)
  /\ reduced' = TRUE
  /\ UNCHANGED << partial, remaining, reg, reading >>

\* ---- naive mode: non-atomic read-modify-write straight into shared Y --------
NaiveRead(w) ==
  /\ Mode = "naive"
  /\ remaining[w] > 0
  /\ ~reading[w]
  /\ reg'     = [reg     EXCEPT ![w] = Y]
  /\ reading' = [reading EXCEPT ![w] = TRUE]
  /\ UNCHANGED << Y, partial, remaining, reduced >>

NaiveWrite(w) ==
  /\ Mode = "naive"
  /\ reading[w]
  /\ Y'         = reg[w] + 1
  /\ reading'   = [reading   EXCEPT ![w] = FALSE]
  /\ remaining' = [remaining EXCEPT ![w] = @ - 1]
  /\ UNCHANGED << partial, reg, reduced >>

Terminated ==
  \/ (Mode = "safe"  /\ AllConsumed /\ reduced)
  \/ (Mode = "naive" /\ AllConsumed /\ \A w \in Workers : ~reading[w])

Next ==
  \/ \E w \in Workers : SafeStep(w)
  \/ Reduce
  \/ \E w \in Workers : NaiveRead(w)
  \/ \E w \in Workers : NaiveWrite(w)
  \/ Terminated /\ UNCHANGED vars        \* stutter once finished (no deadlock)

Spec == Init /\ [][Next]_vars

\* ---- invariants -------------------------------------------------------------
TypeOK ==
  /\ Y         \in Nat
  /\ partial   \in [Workers -> Nat]
  /\ remaining \in [Workers -> Nat]
  /\ reg       \in [Workers -> Nat]
  /\ reading   \in [Workers -> BOOLEAN]
  /\ reduced   \in BOOLEAN

Done ==
  \/ (Mode = "safe"  /\ reduced)
  \/ (Mode = "naive" /\ AllConsumed /\ \A w \in Workers : ~reading[w])

\* Holds in safe mode for every interleaving; violated in naive mode (lost update).
Correct == Done => (Y = Expected)
===============================================================================
