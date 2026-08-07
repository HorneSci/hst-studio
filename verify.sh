#!/usr/bin/env bash
# HST Studio Community — verify.
#
# Runs everything this tree can prove on your machine and reports what passed.
# Takes about a minute. Needs ./install.sh to have been run first.
#
# This exists because "it installed" and "it works" are different claims, and
# only the second one is worth anything to you.

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

VENV="${HST_VENV:-$HERE/.venv}"

# bin/ everywhere except Windows, where CPython writes Scripts/ and names the
# interpreter python.exe. install.sh resolves this the same way and for the same
# reason; if you change one, change both. Falling through with neither present is
# fine here -- the "run ./install.sh first" check below is what reports it, and
# it should keep reporting a missing venv rather than a missing directory.
VBIN="$VENV/bin"
VPY="$VENV/bin/python"
if [ ! -x "$VPY" ] && [ -x "$VENV/Scripts/python.exe" ]; then
  VBIN="$VENV/Scripts"
  VPY="$VENV/Scripts/python.exe"
fi

PASS=0; FAIL=0; SKIP_TOOL=0; SKIP_TIER=0; PART=0

# Five states, not three. Until 2026-08-06 a stage that ran and produced a
# fraction of its output still printed `ok`, and the tally said
# "8 passed, 0 failed, 0 skipped" while stages had silently skipped -- so the
# last thing a downloader read was a green line for something that had not
# happened. This tree ships a taxonomy of vacuous tests and a scanner for them;
# committing one in the first script a stranger runs is the version that costs
# the most.
#
#   ok    -- ran, and produced everything it was supposed to
#   part  -- ran, and produced SOME of it. The counts go on this line, not into
#            a log nobody opens.
#   FAIL  -- ran, and was wrong. The only state that sets a nonzero exit.
#   skip  -- did not run: an optional tool is missing from THIS machine. Fixable
#            by you.
#   n/a   -- did not run: the input is not in this tier of the release. Not
#            fixable by you, not a defect, and a different thing to be told.
ok()   { printf '  \033[32mok\033[0m    %s\n' "$*"; PASS=$((PASS+1)); }
part() { printf '  \033[33mpart\033[0m  %s\n' "$*"; PART=$((PART+1)); }
bad()  { printf '  \033[31mFAIL\033[0m  %s\n' "$*"; FAIL=$((FAIL+1)); }
skip() { printf '  skip  %s\n' "$*"; SKIP_TOOL=$((SKIP_TOOL+1)); }
tier() { printf '  n/a   %s\n' "$*"; SKIP_TIER=$((SKIP_TIER+1)); }
note() { printf '        %s\n' "$*"; }

# Show a failure's own cause, not just the tail of its output. A bare `tail -12`
# put the paper-artifact build's real error ("g++-13: command not found",
# "FAILED: reference arm did not compile") off the top of the excerpt, behind
# four screens of export-policy text that is this tree's documented, EXPECTED
# behaviour. The reader saw a FAIL whose only visible explanation was a policy
# note, and was invited to report it. Cause lines first, tail after for context.
why() {
  _out="$1"; _n="${2:-12}"
  _cause="$(printf '%s\n' "$_out" \
    | grep -E 'FAILED:|command not found|No such file or directory|^E {3}|^ERROR|error:' \
    | head -6)"
  if [ -n "$_cause" ]; then
    printf '%s\n' "$_cause" | sed 's/^/        /'
    printf '        --- last %s lines ---\n' "$_n"
  fi
  printf '%s\n' "$_out" | tail -"$_n" | sed 's/^/        /'
}

# The host, in the naming the staged artifacts use. Everything below that has to
# choose between per-platform files chooses with this rather than by taking
# whichever file it finds first.
case "$(uname -s)" in
  Darwin) HOST_OS=darwin ;;
  Linux)  HOST_OS=linux ;;
  *)      HOST_OS="$(uname -s | tr '[:upper:]' '[:lower:]')" ;;
esac
case "$(uname -m)" in
  arm64|aarch64) HOST_ARCH=arm64 ;;
  x86_64|amd64)  HOST_ARCH=x86_64 ;;
  *)             HOST_ARCH="$(uname -m)" ;;
esac
HOST_PLAT="$HOST_OS-$HOST_ARCH"

printf '\n  HST Studio Community — verify\n\n'

# --- 0. what you received is what was published ------------------------------
# Supply chain before execution: SHA256SUMS covers every file in bin/ plus
# install.sh and verify.sh -- the things this tree asks you to run, including
# the binaries nobody can read the source of. Checked first, before anything
# in bin/ executes. Needs no venv and no network.
if [ -f SHA256SUMS ]; then
  SUMCMD=""
  if command -v shasum >/dev/null 2>&1; then SUMCMD="shasum -a 256"
  elif command -v sha256sum >/dev/null 2>&1; then SUMCMD="sha256sum"
  fi
  if [ -z "$SUMCMD" ]; then
    skip "sums — neither shasum nor sha256sum on this machine"
  elif out="$($SUMCMD -c SHA256SUMS 2>&1)"; then
    ok "sums — bin/ matches SHA256SUMS"
  else
    bad "sums — a file does not match SHA256SUMS. Do not run it; re-download."
    printf '%s\n' "$out" | grep -v ': OK$' | sed 's/^/        /'
  fi
else
  tier "SHA256SUMS — not in this tree"
fi

if [ ! -x "$VPY" ]; then
  printf '  No virtualenv at %s. Run ./install.sh first.\n\n' "$VENV" >&2
  exit 1
fi

# --- 1. the packages import ------------------------------------------------
for m in spdelta bindnum claimlint fitscreen; do
  if "$VPY" -c "import $m" >/dev/null 2>&1; then ok "import $m"; else bad "import $m"; fi
done

# --- 2. their own test suites ----------------------------------------------
# Ours passing on our machine is not evidence about yours.
# Install pytest on demand rather than re-execing: an exec here would repeat
# every check above it and print the banner twice.
if ! "$VPY" -c "import pytest" >/dev/null 2>&1; then
  "$VPY" -m pip install -q pytest >/dev/null 2>&1 || true
fi

if "$VPY" -c "import pytest" >/dev/null 2>&1; then
  for pkg in spdelta bindnum claimlint fitscreen; do
    [ -d "packages/$pkg/tests" ] || { tier "packages/$pkg tests — not in this tree"; continue; }
    if out="$("$VPY" -m pytest -q "packages/$pkg/tests" 2>&1)"; then
      # Not every package prints a "N passed" summary -- spdelta's config does
      # not -- so fall back to the exit code rather than reporting a blank.
      summary="$(printf '%s' "$out" | grep -Eo '[0-9]+ passed[^,]*' | tail -1)"
      ok "packages/$pkg tests — ${summary:-passed}"
    else
      bad "packages/$pkg tests"
      why "$out"
    fi
  done
else
  skip "package test suites (pytest unavailable offline)"
fi

# --- 3. a real measurement -------------------------------------------------
if [ -f packages/spdelta/examples/ladder_demo.py ]; then
  if out="$("$VPY" packages/spdelta/examples/ladder_demo.py 2>&1)"; then
    if printf '%s' "$out" | grep -q "vs masked_row_scan"; then
      ok "spdelta ladder demo — measured on THIS machine"
      printf '%s\n' "$out" | grep -E "vs (full_matvec|masked_row_scan)" | sed 's/^/        /'
    else
      bad "spdelta ladder demo ran but produced no comparison"
    fi
  else
    bad "spdelta ladder demo"
    why "$out" 10
  fi
else
  tier "spdelta ladder demo — not in this tree"
fi

# --- 3b. the candidate finder ----------------------------------------------
# fitscreen screens a trace; it measures no speed, so the honest claim here is
# only that it runs on YOUR machine and prints a verdict on the bundled
# sample. Which verdict belongs to the data, not to this script -- asserting
# a particular one would turn a screen into a demo.
if [ -f packages/fitscreen/examples/sample_clustered.csv ]; then
  if out="$("$VPY" -m fitscreen packages/fitscreen/examples/sample_clustered.csv \
        --hierarchy packages/fitscreen/examples/sample_hierarchy.csv 2>&1)"; then
    if printf '%s' "$out" | grep -qE 'STRONG FIT|MARGINAL|NOT A FIT'; then
      ok "fitscreen — screened the bundled sample, verdict printed"
      printf '%s\n' "$out" | grep -E '^Verdict:' | cut -c1-100 | sed 's/^/        /'
    else
      bad "fitscreen ran but printed no verdict"
    fi
  else
    bad "fitscreen on the bundled sample"
    why "$out" 10
  fi
else
  tier "fitscreen sample — not in this tree"
fi

# --- 4. the paper re-derives -----------------------------------------------
# Two things were wrong here until 2026-08-06, and they compounded.
#
# The build ran bare `./build.sh`, so the artifact probed whatever `python3`
# the caller's shell resolved -- NOT the virtualenv install.sh had just built
# and filled with numpy. On the author's Mac that was a pyenv install that
# happened to have numpy and matplotlib; on a clean Linux box it was a system
# python with neither, so the figure stage and the prose stage both skipped.
# PYTHON= names the interpreter outright and PATH= carries the rest of the venv
# with it.
#
# And the report was `ok "paper artifact re-derives"` plus whatever text
# followed "BUILD CLEAN", which threw away the skip list the README explicitly
# tells the reader to go and read. Six of fourteen figures is not "re-derives".
# The counts below come from build.sh's own BUILD SUMMARY line, so verify.sh
# re-derives nothing and cannot drift from what the build did.
_field() { printf '%s\n' "$1" | tr ' ' '\n' | grep "^$2=" | cut -d= -f2- | head -1; }

if [ -x repro/paper-artifact/build.sh ]; then
  if out="$(cd repro/paper-artifact && PYTHON="$VPY" PATH="$VBIN:$PATH" ./build.sh 2>&1)"; then
    sum="$(printf '%s\n' "$out" | grep '^BUILD SUMMARY ' | head -1)"
    if [ -z "$sum" ]; then
      # An artifact too old to report its own coverage. Say so rather than
      # inheriting the old behaviour of calling that success.
      part "paper artifact built, but reported no coverage summary — cannot say how much of the paper re-derived"
    else
      figs="$(_field "$sum" figures)";  figstage="$(_field "$sum" figstage)"
      secs="$(_field "$sum" sections)"; secstage="$(_field "$sum" secstage)"
      figw="${figs%%/*}"; figt="${figs##*/}"
      secw="${secs%%/*}"; sect="${secs##*/}"

      # `nodata` is the state where the stage COULD NOT RUN because its input
      # CSVs are absent, and it is n/a rather than FAIL. History, in order
      # (issue #67): the artifact used to die on the first missing CSV, so a
      # clean checkout reported red on all three platforms; the first fix
      # withheld data/ entirely and this branch was the shipped tier's normal
      # state; since the 2026-08-07 publication decision the shipped tier
      # CARRIES data/ (the gated public-profile export), so the EXPECTED state
      # here is `part` -- 6 of 14 figures and 9 of 15 sections re-derived, the
      # rest named as policy-withheld below. `nodata` now means a stripped or
      # pre-publication copy, and it stays: what must NOT happen is the counts
      # disappearing, and no line here may read as though the paper fully
      # reproduced.
      if [ "$figstage" = nodata ] && [ "$secstage" = nodata ]; then
        tier "paper artifact — 0 of $figt figures and 0 of $sect prose sections: WITHHELD"
        note "the measured CSVs both stages read are not published in this tier, so"
        note "neither stage ran. Nothing failed, and nothing you install will change it."
        # What DID run, read out of the build's own output rather than asserted.
        # The self-test needs a named GCC and skips without one, so a fixed
        # sentence here would tell a Windows or bare-macOS reader that something
        # passed on their machine when it never started -- which is the same
        # class of claim this whole stage was rewritten to stop making.
        if printf '%s\n' "$out" | grep -qE '^[0-9]+ checks, 0 failed'; then
          note "what DID run and pass, on your hardware: the open reference arm's self-test."
        fi
      elif [ "$figstage" = ran ] && [ "$secstage" = ran ] \
         && [ "$figw" = "$figt" ] && [ "$secw" = "$sect" ]; then
        ok "paper artifact re-derives — $figw of $figt figures, $secw of $sect prose sections, all of it"
      else
        part "paper artifact — $figw of $figt figures and $secw of $sect prose sections re-derived on this machine"
      fi

      # Why the rest did not, in the three categories that mean different
      # things: an input this tier withholds, a stage that never started, and a
      # tool you can install.
      if [ "$figstage" = nodata ] || [ "$secstage" = nodata ]; then
        note "repro/paper-artifact/CONFLICTS.md is the export policy; the README's"
        note "Reproduction kit section says what the artifact is for without the data."
      elif [ "$figstage" != ran ]; then
        note "the figure stage did not run at all — no matplotlib in ${VENV#$HERE/}, so the"
        note "export-policy skips underneath it are not even visible yet"
      elif [ "$figw" != "$figt" ]; then
        note "$((figt - figw)) figures withheld by this release's export policy — repro/paper-artifact/CONFLICTS.md"
      fi
      if [ "$secstage" = nodata ]; then
        : # already said above, and it is one cause for both stages
      elif [ "$secstage" != ran ]; then
        note "the prose stage did not run at all — no numpy in ${VENV#$HERE/}"
      elif [ "$secw" != "$sect" ]; then
        note "$((sect - secw)) prose sections withheld by the same policy"
      fi
      printf '%s\n' "$out" | grep -o '^BUILD CLEAN.*' | head -1 | sed 's/^/        /'
    fi
  else
    bad "paper artifact build"
    why "$out"
  fi
else
  tier "paper artifact — not in this tree"
fi

# --- 5. the runtime, if this tree has one ----------------------------------
if [ -d bin ]; then
  if "$VPY" -c "import hstcore" >/dev/null 2>&1; then
    ok "hstcore binding imports"
  else
    skip "runtime binding not installed"
  fi

  # The library's exports against the ABI manifest. This is the check worth
  # running first when a binding fails to load: a library at HSTCORE_1.3 beside
  # a binding written for 1.4 fails at load with an error nobody enjoys
  # debugging, and that exact skew was live in our own tree on 2026-08-05.
  # Needs no licence -- it reads the symbol table, it does not open a session.
  if [ -f packages/hstcore-abi/validate.py ]; then
    LIBS=""
    for l in bin/libhstcore.so bin/libhstcore.dylib bin/hstcore.dll; do
      [ -f "$l" ] && LIBS="$LIBS --library $l"
    done
    if [ -n "$LIBS" ]; then
      if out="$("$VPY" packages/hstcore-abi/validate.py $LIBS 2>&1)"; then
        ok "libhstcore exports match the ABI manifest"
      else
        bad "libhstcore does not match packages/hstcore-abi/abi.json"
        why "$out"
      fi
    fi
  fi

  # Which bindings you can actually build here. Reported rather than run: a
  # binding's own conformance suite needs a C compiler for the shared stub, and
  # a check that quietly skips on a missing toolchain is one you cannot trust.
  for b in py java node go rs dotnet; do
    d="packages/hstcore-$b"
    [ -d "$d" ] || continue
    case "$b" in
      py)     tool=python3 ;;   java) tool=javac ;;  node) tool=node ;;
      go)     tool=go ;;        rs)   tool=cargo ;;  dotnet) tool=dotnet ;;
    esac
    if command -v "$tool" >/dev/null 2>&1; then
      ok "hstcore-$b staged, $tool present — see $d/README.md"
    else
      skip "hstcore-$b staged, no $tool on this machine"
    fi
  done

  # The runtime, actually run. This said "needs a signed licence token (see
  # EULA.md)" until 2026-08-06 -- pointing at a file this tree does not contain,
  # for a gate this library does not have. The community build is unmetered, so
  # the one step that is the whole point of the tree was the one step verify.sh
  # skipped.
  # The host's build first, then the unsuffixed one, then anything that runs.
  # This loop only escaped the library selector's bug by accident: it EXECUTES
  # each candidate, so a Mach-O build on Linux exits 126 and it moves on. An
  # accident is not a mechanism, and "no build for this platform" is a better
  # thing to print than a list of binaries that were tried in filename order.
  compile_tool=""
  for c in "bin/hst-compile.$HOST_PLAT" bin/hst-compile bin/hst-compile.*; do
    [ -x "$c" ] || continue
    if "$c" >/dev/null 2>&1 || [ $? -eq 2 ]; then compile_tool="$c"; break; fi
  done

  if [ -z "$compile_tool" ]; then
    skip "runtime execution — no hst-compile build for this platform ($HOST_PLAT); bin/ has $(ls bin/hst-compile.* 2>/dev/null | sed 's|bin/hst-compile\.||' | tr '\n' ' ')"
  else
    tmp="$(mktemp -d)"
    printf '{"operator":{"n":64,"m":64,"rows":[' > "$tmp/op.json"
    i=0; while [ $i -lt 64 ]; do [ $i -gt 0 ] && printf ',' >> "$tmp/op.json"; printf '%d' $i >> "$tmp/op.json"; i=$((i+1)); done
    printf '],"cols":[' >> "$tmp/op.json"
    i=0; while [ $i -lt 64 ]; do [ $i -gt 0 ] && printf ',' >> "$tmp/op.json"; printf '%d' $i >> "$tmp/op.json"; i=$((i+1)); done
    printf '],"values":[' >> "$tmp/op.json"
    i=0; while [ $i -lt 64 ]; do [ $i -gt 0 ] && printf ',' >> "$tmp/op.json"; printf '1.0' >> "$tmp/op.json"; i=$((i+1)); done
    printf ']},"compile_options":{"tile_size":32}}' >> "$tmp/op.json"

    # The library ships in this tree's own bin/, which is not on the OS dynamic
    # loader path. Passing lib_path explicitly is required: without it hstcore
    # falls back to a bare "libhstcore.dylib"/".so", dlopen fails, and this
    # check reports a licence problem for what is really a lookup problem.
    #
    # WHICH library: this picked by EXISTENCE, with .dylib listed first, until
    # 2026-08-06. A cross-platform tree stages BOTH, so every Linux box -- the
    # primary target -- handed a Mach-O file to dlopen, failed the one check the
    # runtime tier exists to pass, and was told to look at its licence. Order by
    # host, then actually LOAD each candidate and keep the first that opens:
    # trying also catches a .so built for another libc or another arch, which no
    # amount of reasoning about filenames can.
    case "$HOST_OS" in
      darwin)             lib_order="bin/libhstcore.dylib bin/libhstcore.so" ;;
      cygwin*|mingw*|msys*|windows*)
                          lib_order="bin/hstcore.dll bin/libhstcore.so bin/libhstcore.dylib" ;;
      *)                  lib_order="bin/libhstcore.so bin/libhstcore.dylib" ;;
    esac
    runtime_lib=""
    for l in $lib_order; do
      [ -f "$l" ] || continue
      cand="$(cd "$(dirname "$l")" && pwd)/$(basename "$l")"
      if "$VPY" -c 'import ctypes,sys; ctypes.CDLL(sys.argv[1])' "$cand" >/dev/null 2>&1; then
        runtime_lib="$cand"
        break
      fi
    done

    if ! "$compile_tool" "$tmp/op.json" "$tmp/op.bin" >/dev/null 2>&1; then
      skip "runtime execution — hst-compile could not run on this platform"
    elif [ -z "$runtime_lib" ]; then
      skip "runtime execution — no libhstcore in bin/ loads on $HOST_PLAT"
    elif "$VPY" - "$tmp/op.bin" "$runtime_lib" <<'EOF' >"$tmp/run.log" 2>&1
import sys
import numpy as np
import hstcore
ctx = hstcore.HSTContext(sys.argv[1], "", batch=1, lib_path=sys.argv[2])   # no token: unmetered build
cols = np.arange(0, 32, dtype=np.int32)
vals = np.full(32, 0.5, dtype=np.float64)
ctx.apply(cols, vals)
got = np.asarray(ctx.state).copy()
want = ctx.recompute_full()
ctx.close()
assert np.max(np.abs(got - want)) < 1e-12, "delta and recompute disagree"
assert np.count_nonzero(got) == 32, "delta touched the wrong number of rows"
EOF
    then
      ok "runtime execution — opened with NO licence token, delta == recompute"
    else
      bad "runtime execution — the library did not run. Error below; if it mentions a licence, this is the metered build, not the community one."
      sed 's/^/      /' "$tmp/run.log" >&2
    fi
    rm -rf "$tmp"
  fi
fi

# ---------------------------------------------------------------------------
# The tally has to account for everything, including the states that are not
# failures. "8 passed, 0 failed, 0 skipped" while stages had skipped is the bug
# this whole script exists to not commit.
printf '\n  %d passed, %d partial, %d failed, %d skipped' \
  "$PASS" "$PART" "$FAIL" "$((SKIP_TOOL + SKIP_TIER))"
if [ "$((SKIP_TOOL + SKIP_TIER))" -gt 0 ]; then
  printf ' (%d missing a tool on this machine, %d not in this tier)' "$SKIP_TOOL" "$SKIP_TIER"
fi
printf '\n\n'

if [ "$FAIL" -gt 0 ]; then
  printf '  Something above did not work on your machine. That is worth telling us\n'
  printf '  about — it is more useful to us than a clean run.\n\n'
  exit 1
fi

# A partial or a skip is not a failure and must not be reported as one -- the
# exit status stays 0. But it is also not "everything proved", and saying so
# was the whole defect. Only the clean run gets the clean sentence.
if [ "$PART" -eq 0 ] && [ "$SKIP_TOOL" -eq 0 ] && [ "$SKIP_TIER" -eq 0 ]; then
  printf '  Everything this tree can prove without a licence, proved. The numbers\n'
  printf '  above came from your hardware, not ours.\n\n'
else
  printf '  Nothing here failed, and the numbers above came from your hardware, not\n'
  printf '  ours. But this is not a full reproduction: the part/skip lines above say\n'
  printf '  what did not run and why. Read those before quoting this run.\n\n'
fi
