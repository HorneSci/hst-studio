#!/usr/bin/env bash
# hstcore-java — build and conformance-test with nothing but a JDK.
#
#   ./build.sh          compile, then run the smoke test against the shared stub
#   ./build.sh --clean
#
# WHY NOT JUST THE POM. Maven is the right way to *depend* on this binding and
# the wrong thing to require in order to *check* it: the public tree's verify.sh
# has to run on an evaluator's laptop with no build tool, no repository access
# and no network, and a check that needs a dependency resolver is a check that
# does not run on an air-gapped box. Both paths compile the same sources.
#
# The stub is the SHARED one from oss/hstcore-abi/conformance, not a Java-local
# fake -- conformance means the bindings agree about one library, not that each
# agrees with itself. It reports a deliberately non-square operator (n=8, m=5),
# which is what catches a binding that confuses output_dim with input_dim.

set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

OUT="$HERE/build"
[ "${1:-}" = "--clean" ] && { rm -rf "$OUT"; echo "  cleaned $OUT"; exit 0; }

say() { printf '  %s\n' "$*"; }
die() { printf '\n  BUILD FAILED\n\n  %s\n\n' "$*" >&2; exit 1; }

printf '\n  hstcore-java — build\n\n'

command -v javac >/dev/null 2>&1 || die \
  "No javac on PATH. This needs JDK 22 or newer (java.lang.foreign left preview
  in 22 -- on 21 it does not compile, and the error is a missing package rather
  than anything that explains itself)."

JV="$(javac -version 2>&1 | sed 's/javac //;s/\..*//')"
[ "$JV" -ge 22 ] 2>/dev/null || die "javac is $JV; this needs 22 or newer."
say "javac       $JV"

# --- locate the conformance stub -------------------------------------------
# Three places, in order: an explicit argument, the sibling abi package (source
# checkout), then a stub already built here.
STUB="${HSTCORE_STUB:-}"
if [ -z "$STUB" ]; then
  for cand in \
    "$HERE/../hstcore-abi/conformance/lib/libhstcore.dylib" \
    "$HERE/../hstcore-abi/conformance/lib/libhstcore.so" \
    "$OUT/stub/libhstcore.dylib" \
    "$OUT/stub/libhstcore.so"
  do
    [ -f "$cand" ] && { STUB="$cand"; break; }
  done
fi

# --- compile ---------------------------------------------------------------
mkdir -p "$OUT"
javac -d "$OUT" src/main/java/com/hornesci/hstcore/*.java 2>/dev/null \
  || die "compile failed:
$(javac -d "$OUT" src/main/java/com/hornesci/hstcore/*.java 2>&1)"
say "compile     com.hornesci.hstcore ok"

# --- conformance -----------------------------------------------------------
# A build that compiles and asserts nothing is the failure mode this estate
# keeps paying for, so a missing stub is reported as SKIPPED in the open rather
# than passed over in silence.
if [ -z "$STUB" ]; then
  printf '\n  compiled, conformance SKIPPED — no stub found.\n'
  printf '  Build one:  ../hstcore-abi/conformance/build-stub.sh\n\n'
  exit 0
fi

say "stub        ${STUB##*/}"
javac -d "$OUT" -cp "$OUT" src/test/java/Smoke.java >/dev/null 2>&1 \
  || die "smoke test failed to compile"

# --enable-native-access silences the JDK 24+ restricted-method warning; without
# it the test still passes but prints a warning that reads like a failure.
java --enable-native-access=ALL-UNNAMED -cp "$OUT" Smoke "$STUB" \
  || die "conformance smoke test FAILED against $STUB"

printf '\n  built and conformance-checked.\n\n'
