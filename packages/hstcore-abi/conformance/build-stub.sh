#!/usr/bin/env bash
# Build the shared conformance stub — ONE fake libhstcore that every binding
# tests against.
#
# WHY SHARED. Each binding having its own stub means each binding proves it
# agrees with itself. Conformance is agreement about ONE library, so there is one
# stub, and it lives here rather than inside any single language's tree.
#
# The stub reports a deliberately NON-SQUARE operator (n=8, m=5). That is
# load-bearing: state buffers are output_dim*batch and input buffers are
# input_dim*batch, and a binding that confuses the two passes every square test
# and corrupts memory on a real operator. Square fixtures hide the bug that
# costs the most to find.
#
# The source is hstcore-py's stub, which is the most complete one and already
# carries call counters and forced return codes. It is compiled here rather than
# copied, so there is exactly one C file to keep correct.
#
#   ./build-stub.sh            -> ./lib/libhstcore.{dylib,so}
#   ./build-stub.sh --clean

set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$HERE/../../hstcore-py/tests/stub/hst_stub.c"
OUT="$HERE/lib"

[ "${1:-}" = "--clean" ] && { rm -rf "$OUT"; echo "  cleaned $OUT"; exit 0; }

[ -f "$SRC" ] || { echo "  stub source missing: $SRC" >&2; exit 1; }

# `cc` may be shadowed by an alias in an interactive shell; use the real one.
CC="${CC:-/usr/bin/cc}"
command -v "$CC" >/dev/null 2>&1 || CC="$(command -v clang || command -v gcc)"
[ -n "$CC" ] || { echo "  no C compiler found" >&2; exit 1; }

mkdir -p "$OUT"

case "$(uname -s)" in
  Darwin)
    LIB="$OUT/libhstcore.dylib"
    # An ABSOLUTE install_name. Without it the recorded name is the relative
    # build path, and any test binary run from another directory fails to load
    # it with a message that reads like a missing file rather than a wrong path.
    "$CC" -shared -fPIC -O0 -install_name "$LIB" -o "$LIB" "$SRC"
    ;;
  *)
    LIB="$OUT/libhstcore.so"
    "$CC" -shared -fPIC -O0 -o "$LIB" "$SRC"
    ;;
esac

# A stub that does not export the whole ABI would make every binding's
# conformance run a test of nothing in particular.
COUNT=$(nm -g "$LIB" 2>/dev/null | grep -cE " [TtWw] _?hst_[a-z_]+$" || true)
echo "  built $LIB"
echo "  exports $COUNT hst_* symbols"
if [ "$COUNT" -lt 13 ]; then
  echo "  ERROR: fewer than the 13 ABI symbols; the stub is incomplete" >&2
  exit 1
fi
