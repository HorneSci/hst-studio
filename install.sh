#!/usr/bin/env bash
# HST Studio Community — install.
#
# Creates a virtualenv in .venv and installs the Apache-2.0 packages into
# it. Nothing is installed system-wide, nothing is downloaded from the network
# beyond what pip needs for numpy/scipy, and nothing outside this directory is
# touched.
#
#     ./install.sh                 online (numpy/scipy from PyPI)
#     ./install.sh --wheels DIR    offline, from wheels you carried across
#
# Re-running is safe.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

VENV="${HST_VENV:-$HERE/.venv}"
PY="${PYTHON:-python3}"

say()  { printf '  %s\n' "$*"; }
die()  { printf '\n  INSTALL FAILED\n\n  %s\n\n' "$*" >&2; exit 1; }

# --- offline install -------------------------------------------------------
# spdelta needs numpy and scipy from PyPI. On an air-gapped machine, fetch the
# wheels somewhere with network and point at them:
#
#     python3 -m pip download 'numpy>=1.24' 'scipy>=1.10' 'setuptools>=68' wheel -d wheels/
#     ./install.sh --wheels ./wheels
#
# setuptools and wheel are NOT optional here, and leaving them out is the
# failure this recipe used to hand people: pip's build isolation builds each
# packages/* sdist in a fresh environment that it populates FROM THE INDEX, so
# under --no-index the install dies on `setuptools>=68` before it ever looks
# for numpy. The error names setuptools, which is not a package anyone thinks
# they asked for, on the first package rather than the last. Keep this line
# character-identical to the one in README.md -- they disagreed until
# 2026-08-06 and the script was the wrong one.
#
# Add `matplotlib` to that same download if you also want repro/paper-artifact
# to render its figures offline. Without it the install still succeeds and the
# figure stage writes none, which verify.sh reports as a count rather than
# hiding.
#
# --wheels implies --no-index, so a missing wheel FAILS rather than silently
# reaching for the network -- the whole point on a machine that has none.
WHEELS=""
while [ $# -gt 0 ]; do
  case "$1" in
    --wheels)   WHEELS="${2:-}"; [ -n "$WHEELS" ] || die "--wheels needs a directory."; shift 2 ;;
    --wheels=*) WHEELS="${1#*=}"; shift ;;
    -h|--help)
      printf '\nusage: ./install.sh [--wheels DIR]\n\n  --wheels DIR   install offline from wheels in DIR (implies --no-index)\n\n'
      exit 0 ;;
    *) die "Unknown argument: $1 (try --help)" ;;
  esac
done

PIP_SRC=()
if [ -n "$WHEELS" ]; then
  [ -d "$WHEELS" ] || die "--wheels: no such directory: $WHEELS"
  case "$WHEELS" in /*) ;; *) WHEELS="$HERE/${WHEELS#./}" ;; esac
  PIP_SRC=(--no-index --find-links "$WHEELS")
fi

printf '\n  HST Studio Community — install\n\n'
# An `&&` one-liner here would exit the whole script under `set -e` whenever the
# test is false, i.e. on every normal online install.
if [ -n "$WHEELS" ]; then say "offline     --no-index, wheels from ${WHEELS}"; fi

# macOS still ships bash 3.2, where "${arr[@]}" on an empty array trips `set -u`,
# so every expansion of PIP_SRC below uses the ${x[@]+"${x[@]}"} guard.

# --- preflight -------------------------------------------------------------
# 3.11, not 3.10: bindnum and claimlint both declare requires-python >= 3.11.
# This floor said 3.10 until 2026-08-06, so a 3.10 user cleared preflight and
# then died inside pip's resolver on the second package -- a confusing failure
# halfway through an install that had already told them they were fine. The
# floor is 3.11 because bindnum and claimlint both declare
# `requires-python = ">=3.11"` -- check packages/bindnum/pyproject.toml and
# packages/claimlint/pyproject.toml, which ship in this tree. Keep this in
# step with the strictest requires-python across packages/*.
command -v "$PY" >/dev/null 2>&1 || die \
  "No '$PY' on PATH. Install Python 3.11 or newer, or set PYTHON=/path/to/python3."

PYV="$("$PY" -c 'import sys;print("%d.%d"%sys.version_info[:2])')"
"$PY" - <<'EOF' || die "Python $("${PYTHON:-python3}" -V 2>&1) is too old. This needs 3.11+."
import sys
sys.exit(0 if sys.version_info[:2] >= (3, 11) else 1)
EOF
say "python      $PY ($PYV)"

# --- venv ------------------------------------------------------------------
if [ ! -d "$VENV" ]; then
  "$PY" -m venv "$VENV" || die \
    "Could not create a virtualenv at $VENV.
  On Debian/Ubuntu this usually means python3-venv is missing:
      sudo apt install python3-venv"
  say "venv        created at ${VENV#$HERE/}"
else
  say "venv        reusing ${VENV#$HERE/}"
fi

# CPython puts a venv's executables in Scripts/ on Windows and in bin/ on every
# other platform. Hardcoding bin/ meant this script created a perfectly good
# virtualenv and then rejected it -- "looks broken — no bin/pip" -- on a machine
# where nothing was broken, and told the reader to delete the one thing that had
# just worked. Resolve the directory ONCE, here, and use $VBIN everywhere below;
# "bin" is not spelled again in this file.
VBIN="$VENV/bin"
VPY="$VENV/bin/python"
if [ ! -x "$VPY" ] && [ -x "$VENV/Scripts/python.exe" ]; then
  VBIN="$VENV/Scripts"
  VPY="$VENV/Scripts/python.exe"
fi
[ -x "$VPY" ] || die \
  "Virtualenv at $VENV has no interpreter in bin/ or Scripts/. Delete it and re-run."

# pip through the interpreter, never as a program on disk. $VBIN/pip is pip.exe
# on Windows, and whether a bare `pip` path resolves to it depends on the shell's
# .exe fallback -- one more thing to be wrong about, on the platform that has
# already been wrong about paths twice. `python -m pip` is the same pip, found
# the same way, on all three.
vpip() { "$VPY" -m pip "$@"; }

vpip install -q --upgrade pip >/dev/null 2>&1 || true

# --- packages --------------------------------------------------------------
# spdelta first: it is the one that actually computes, and it is the one whose
# dependencies (numpy, scipy) can take a while or fail on an unusual platform.
for pkg in spdelta bindnum claimlint fitscreen; do
  [ -d "packages/$pkg" ] || { say "skip        packages/$pkg (absent)"; continue; }
  printf '  install     %-12s' "$pkg"
  if out="$(vpip install -q ${PIP_SRC[@]+"${PIP_SRC[@]}"} "./packages/$pkg" 2>&1)"; then
    printf 'ok\n'
  else
    printf 'FAILED\n'
    die "pip could not install packages/$pkg:

$out"
  fi
done

# The figure toolchain for repro/paper-artifact. Not a dependency of the three
# packages above -- they run on numpy and scipy alone, which is a claim this
# tree makes and keeps.
#
# It has to be here because the artifact now runs under THIS virtualenv rather
# than under whatever `python3` the caller's shell resolves. Before 2026-08-06
# it ran under the latter, so on the author's Mac it found a global matplotlib
# and wrote 6 of 14 figures, and on a clean Linux box it found none and wrote
# 0 of 14 -- and verify.sh reported the same clean line either way. Fixing the
# interpreter without installing matplotlib would have made every machine the
# clean-Linux one.
#
# Non-fatal on purpose: an air-gapped tree whose wheels/ has no matplotlib
# should still install, and verify.sh prints the figure count it actually got,
# so a skip here is on the reader's screen rather than in a log.
if [ -d repro/paper-artifact ]; then
  printf '  figures     %-12s' "matplotlib"
  if vpip install -q ${PIP_SRC[@]+"${PIP_SRC[@]}"} 'matplotlib>=3.7' >/dev/null 2>&1; then
    printf 'ok\n'
  else
    printf 'skipped — repro/paper-artifact will write 0 figures\n'
  fi
fi

# Optional: the runtime binding, present only in a --with-runtime tree.
if [ -d packages/hstcore-py ]; then
  printf '  install     %-12s' "hstcore"
  vpip install -q ${PIP_SRC[@]+"${PIP_SRC[@]}"} ./packages/hstcore-py >/dev/null 2>&1 && printf 'ok\n' || printf 'skipped\n'
fi

# --- prove it works --------------------------------------------------------
# An installer that exits 0 without demonstrating anything is how you find out
# at demo time. This imports every package it just claimed to install.
printf '  verify      '
"$VPY" - <<'EOF' || die "Packages installed but do not import. The install is not usable."
import sys

missing = []
for m in ("spdelta", "bindnum", "claimlint", "fitscreen"):
    try:
        __import__(m)          # actually import it, not just locate it
    except Exception as e:
        missing.append(f"{m} ({e.__class__.__name__}: {e})")

if missing:
    print("FAILED — " + "; ".join(missing))
    sys.exit(1)
print("ok — spdelta, bindnum, claimlint, fitscreen all import")
EOF

cat <<EOF

  Installed. Activate the environment:

      source ${VBIN#$HERE/}/activate

  Then try, in rough order of how much they tell you:

      ./verify.sh                              everything at once, ~1 minute
      python packages/spdelta/examples/ladder_demo.py
                                               a real measurement, with its
                                               conditions attached
      cd repro/paper-artifact && ./build.sh    re-derive the paper's figures

  No HST binary is needed for any of the above. See README.md.

EOF
