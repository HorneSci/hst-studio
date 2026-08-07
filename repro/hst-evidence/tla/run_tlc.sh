#!/usr/bin/env bash
# Model-check the published specs with TLC. Public domain (CC0 1.0).
#
#   DCTelemetry                   -> expect "No errors found"
#                                    (safety invariant + 4 temporal properties;
#                                     this is the one with a machine-checked
#                                     TLAPS proof and a bit-exact companion
#                                     probe -- see DCTelemetry_README.md)
#   BatchParallelApply            -> expect "No errors found"
#   ColumnParallelApply  (safe)   -> expect "No errors found"
#   ColumnParallelApply  (naive)  -> a lost-update counterexample is EXPECTED;
#                                    it is the instructive failure, not a bug here.
#
# The counterexample trace is REGENERATED here rather than shipped. Committed
# TLC trace artifacts are build output, and a binary blob is not evidence a
# reader can check -- run this and read the trace TLC prints.
#
# Uses an existing tla2tools.jar if present (set TLA_JAR to override), otherwise
# downloads the latest release.
#
# EXIT CODE CONTRACT (added 2026-08-04, and it is the point of this rewrite).
# Until now this script had `set -u` and nothing else: a violated invariant in
# check 1, 2 or 3 printed "Error: Invariant ... is violated." and the script
# still exited 0, because the exit status was whatever the LAST command
# returned -- and the last command was check 4, whose `|| echo` swallows every
# failure unconditionally. So the one script in this package with no exit-code
# contract was the formal-verification runner, in a package that ships
# probes/include/assert_rel.hpp whose header reads "a check that does not gate
# the exit code is a check on paper". Now:
#
#   0  every expectation met
#   1  an expectation was violated (a spec that must pass didn't, or the naive
#      spec that must FAIL passed -- see below)
#   2  the harness could not run (no jar, no java)
#
# Check 4 is gated in the direction people forget. Its expected outcome is a
# counterexample, so the failure mode that matters is TLC finding NO error:
# that means the lost-update trace this package exists to exhibit has stopped
# reproducing -- because the spec drifted, the cfg lost a constraint, or the
# naive algorithm was silently repaired. Under the old script that regression
# printed the "EXPECTED result" banner over a clean run and exited 0. An
# expected-failure check that does not verify the failure happened asserts
# nothing at all.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"

command -v java >/dev/null 2>&1 || {
  echo "java not found; TLC needs a JRE. Install one, then re-run." >&2
  exit 2
}

JAR="${TLA_JAR:-/opt/tla/tla2tools.jar}"
if [ ! -f "$JAR" ]; then
  JAR="$HERE/tla2tools.jar"
  if [ ! -f "$JAR" ]; then
    echo "Fetching tla2tools.jar ..."
    curl -fsSL -o "$JAR" \
      https://github.com/tlaplus/tlaplus/releases/latest/download/tla2tools.jar || {
        echo "Could not download tla2tools.jar. Set TLA_JAR to a local copy." >&2
        exit 2
      }
  fi
fi
echo "Using TLC jar: $JAR"
echo

failures=0
note() { echo ">> $*"; }
fail() { echo ">> FAIL: $*"; failures=$((failures + 1)); }

# A state floor, for the same reason every other check in this estate has one.
# TLC reports success on a model it barely explored, and "No errors found" over
# 10 states is a sentence about the cfg, not about the algorithm. These floors
# are set BELOW the counts observed on 2026-08-04 (DCTelemetry 426496,
# BatchParallelApply 125, ColumnParallelApply_safe 10) so ordinary TLC version
# drift does not trip them, but a cfg edit that collapses the state space --
# an over-tight CONSTRAINT, a constant narrowed to a singleton -- does. The
# safe/batch models are genuinely small; the floor pins them at small rather
# than letting them shrink to nothing unnoticed. If you widen a model, raise
# its floor in the same commit or the floor stops meaning anything.
distinct_states() { # logfile -> distinct state count, or empty if TLC did not say
  sed -n 's/.*[^0-9]\([0-9][0-9]*\) distinct states found.*/\1/p' "$1" | tail -1
}

run_tlc() { # logfile cfg module
  java -XX:+UseParallelGC -cp "$JAR" tlc2.TLC \
    -config "$HERE/$2" "$HERE/$3" 2>&1 | tee "$1"
  return "${PIPESTATUS[0]}"
}

expect_clean() { # label cfg module floor
  local label="$1" cfg="$2" mod="$3" floor="$4"
  local log rc states
  log="$(mktemp)"
  echo "=================================================================="
  echo " $label  (expect: No errors found)"
  echo "=================================================================="
  run_tlc "$log" "$cfg" "$mod"
  rc=$?
  if [ "$rc" -ne 0 ]; then
    fail "$label: TLC exited $rc -- a spec that must hold does not. Read the trace above."
  else
    states="$(distinct_states "$log")"
    if [ -z "$states" ]; then
      fail "$label: TLC exited 0 but reported no state count. It did not model-check anything a reader can size."
    elif [ "$states" -lt "$floor" ]; then
      fail "$label: only $states distinct states (floor $floor). The model collapsed; 'No errors found' over $states states is a claim about the cfg, not the algorithm."
    else
      note "$label: clean over $states distinct states."
    fi
  fi
  rm -f "$log"
}

expect_counterexample() { # label cfg module
  local label="$1" cfg="$2" mod="$3"
  local log rc
  log="$(mktemp)"
  echo
  echo "=================================================================="
  echo " $label  (expect: a lost-update counterexample)"
  echo "=================================================================="
  run_tlc "$log" "$cfg" "$mod"
  rc=$?
  if [ "$rc" -eq 0 ]; then
    fail "$label: TLC found NO error. This check exists to exhibit the lost update, and the lost update did not reproduce -- the spec, the cfg or the naive algorithm changed. This is a regression in the evidence, not a pass."
  elif ! grep -q "Invariant .* is violated" "$log"; then
    fail "$label: TLC exited $rc but not on an invariant violation. Something broke other than the intended counterexample; read the output above."
  else
    note "$label: counterexample reproduced. The trace above is the EXPECTED result for the naive (un-reduced) version."
  fi
  rm -f "$log"
}

expect_clean       "1) DCTelemetry"                DCTelemetry.cfg              DCTelemetry.tla          1000
echo
expect_clean       "2) BatchParallelApply"         BatchParallelApply.cfg       BatchParallelApply.tla    100
echo
expect_clean       "3) ColumnParallelApply safe"   ColumnParallelApply_safe.cfg ColumnParallelApply.tla     8
expect_counterexample "4) ColumnParallelApply naive" ColumnParallelApply_naive.cfg ColumnParallelApply.tla

echo
echo "=================================================================="
if [ "$failures" -eq 0 ]; then
  echo " all 4 expectations met"
  exit 0
fi
echo " $failures of 4 expectations VIOLATED"
exit 1
