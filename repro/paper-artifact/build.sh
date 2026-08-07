#!/usr/bin/env bash
# Build and verify the release artifact, in the order a reviewer should run it.
#
#   ./build.sh          everything
#   ./build.sh gate     only the checks that must pass before distribution
#
# Nothing here needs a network, a GPU, or PyTorch. Rebuilding the paper's
# FIGURES does need numpy/matplotlib/scikit-learn; that step is skipped with a
# message rather than failing the build, because it is not part of the gate.
set -uo pipefail
cd "$(dirname "$0")"

# An explicitly-set CXX is honoured as given, and is NOT quietly replaced when
# it does not resolve: you named a compiler, so a build under a different one
# would be a lie about which toolchain produced the result. Only the default is
# searched for (stage 1 below), and only among named GCCs.
CXX_EXPLICIT="${CXX:+1}"
CXX="${CXX:-g++-13}"

# The interpreter, named rather than inherited. Until 2026-08-06 every stage
# below ran bare `python3`, i.e. whatever the caller's shell happened to
# resolve -- on the author's Mac a pyenv install with numpy and matplotlib
# already in it, on a clean machine a bare system python with neither. So this
# script's own skip list was a property of the author's dotfiles, and the
# release's verify.sh reported a clean build for stages that had not run.
# Order: an explicit PYTHON wins, then an active virtualenv, then PATH.
PY="${PYTHON:-}"
if [ -z "$PY" ] && [ -n "${VIRTUAL_ENV:-}" ] && [ -x "$VIRTUAL_ENV/bin/python" ]; then
    PY="$VIRTUAL_ENV/bin/python"
fi
PY="${PY:-python3}"

FAIL=0
SKIPPED=0
# Three reasons a stage skips, and they mean different things to a reader:
#   tool   -- an optional tool is absent from THIS machine. Installable.
#   source -- the stage is a pre-distribution check that only runs inside the
#             umbrella repo this artifact was staged from. Not installable, not
#             a defect, and nothing you do to your machine will change it.
#   data   -- the stage reads result CSVs that this tier of the release does not
#             ship. Also not installable, also not a defect, and a DIFFERENT
#             thing from either of the above: no tool you install and no repo
#             you clone will produce them, because the decision was not to
#             publish them.
# The full-build trailer used to call both of the first two "missing optional
# tools", which is false for the two that are always the source kind in a
# distributed copy.
SKIP_TOOL=0
SKIP_SOURCE=0
SKIP_DATA=0
step() { printf '\n=== %s\n' "$1"; }
fail() { printf 'FAILED: %s\n' "$1"; FAIL=1; }
skip() { printf 'skipped: %s\n' "$1"; SKIPPED=$((SKIPPED + 1)); }
skip_tool()   { skip "$1"; SKIP_TOOL=$((SKIP_TOOL + 1)); }
skip_source() { skip "$1"; SKIP_SOURCE=$((SKIP_SOURCE + 1)); }
skip_data()   { skip "$1"; SKIP_DATA=$((SKIP_DATA + 1)); }

# Does this copy have the measured CSVs the figure and prose stages read?
#
# Issue #67, in two acts. Until 2026-08-07 `data/` existed on the author's
# laptop and in no git history, so a build here shipped 35 uncleared CSVs and
# a build from a clean clone died on the first open(). The first fix withheld
# them entirely (0 of 14 figures). Eric's release decision, later the same
# day, published the half that was always publishable: the PUBLIC-PROFILE
# export -- produced and gated by tools/export_csvs.py, columns allowlisted,
# the tiling-ratio columns (dens, router_probes, tiles) withheld -- is now
# TRACKED, so every copy of this artifact carries the same data/ and the
# stages below re-derive 6 of 14 figures and 9 of 15 prose sections. The
# remaining 8 figures and 6 sections stay withheld by the column policy;
# CONFLICTS.md names each one.
#
# A copy WITHOUT data/ is therefore no longer the shipped tier -- it is a
# stripped or incomplete copy, or a future tier that withholds -- and the
# stages report that their input is absent rather than that something broke.
#
# Checked by content, not by directory: an empty `data/` is the same situation
# as an absent one, and `[ -d data ]` alone would send the build back into the
# FileNotFoundError it is here to prevent.
if ls data/*.csv >/dev/null 2>&1; then
    DATA_PRESENT=1
else
    DATA_PRESENT=0
fi
DATA_NOTE="the result CSVs this stage reads are not in this copy. The released
           artifact ships them in data/ (the gated public-profile export, 35
           files), so their absence here means this copy is stripped or
           predates the 2026-08-07 publication -- re-download, or check out the
           artifact's data/ directory. This is not a failure of your machine.
           What this artifact still does without it: the open reference arm and
           its self-test, the denylist gate, and every word of the method in
           paper/ and CONFLICTS.md."

# How many figures and prose sections this artifact HAS, read out of the
# scripts without importing them -- `ast` is standard library, so the total is
# knowable even on a machine where the stage that produces them cannot run.
# Without it a skipped stage can only say "no figures", which reads like a
# smaller gap than "0 of 14".
count_figures_total() {
    "$PY" - <<'PYEOF' 2>/dev/null || printf '0'
import ast
tree = ast.parse(open("paper/figures.py").read())
for node in tree.body:
    if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "ALL":
        print(len(node.value.elts))
        break
else:
    print(0)
PYEOF
}
count_sections_total() {
    "$PY" - <<'PYEOF' 2>/dev/null || printf '0'
import ast
tree = ast.parse(open("paper/paper_numbers.py").read())
n = 0
for node in ast.walk(tree):
    for d in getattr(node, "decorator_list", []):
        if isinstance(d, ast.Call) and getattr(d.func, "id", "") == "section":
            n += 1
print(n)
PYEOF
}

# build/ is where every stage below writes -- created ONCE, up front, so a
# first run on a clean checkout doesn't fail to link stage 1 while a second
# run (with build/ already present from a previous invocation, or from `git
# clean` never having removed it) silently succeeds on the same tree. This
# used to be `mkdir -p build/tex` inside stage 4 only, well after stage 1
# had already tried to write build/blocksched_selftest.
mkdir -p build

# --- 1. the reference arm -----------------------------------------------------
# NOT bare `g++`. On macOS that is Apple clang, and codegen variance between
# toolchains on this kernel is a 3-7x effect -- larger than any algorithmic
# knob in the paper. Name the compiler with every number you quote from it.
#
# So the compiler stays named, and no search here ever falls back to `g++` or
# `c++`: on a Mac those are Apple clang wearing a GNU name, and a stage that
# silently built under a third toolchain would be worse than one that did not
# run. What changed on 2026-08-06 is what happens when NONE of the named
# compilers is installed. That was a hard `fail`, which made the whole build
# exit 1 and the release's verify.sh report FAIL -- on a tree whose README
# promises "no compiler". It is a `skip` now, for one specific reason: this
# stage quotes no timing. blocksched_selftest is a correctness driver whose
# exit code is the number of failed checks, and stage 5 of it is explicitly
# "a counter rather than a timing". Nothing in the paper's numbers comes from
# it, so its absence costs a check, not a measurement, which is exactly the
# status tectonic and matplotlib already have below.
if [ -n "${CXX_EXPLICIT:-}" ] || command -v "$CXX" >/dev/null 2>&1; then
    CXX_FOUND="$CXX"
else
    CXX_FOUND=""
    for c in g++-13 g++-14 g++-12; do
        if command -v "$c" >/dev/null 2>&1; then CXX_FOUND="$c"; break; fi
    done
fi

if [ -z "$CXX_FOUND" ]; then
    step "the reference arm — no compiler on this machine"
    skip_tool "reference arm -- no named GCC on this machine (looked for: $CXX g++-14 g++-12).
           This is the only stage that needs a compiler, and it quotes no
           timing: it is a correctness self-test of the open block-scheduled
           reference. Everything else here, and every number in the paper, is
           unaffected.
             Debian/Ubuntu   sudo apt install g++-13
             Fedora          sudo dnf install gcc-c++      # then CXX=g++
             macOS           brew install gcc@13
           Bare 'g++' is deliberately not searched: on macOS it is Apple clang,
           and a stage that quietly changed toolchain would be worse than one
           that skipped. Set CXX=... to name any compiler you want used."
else
    step "compiling the reference arm with $CXX_FOUND"
    "$CXX_FOUND" --version | head -1
    "$CXX_FOUND" -O3 -std=c++17 -DNDEBUG -Wall -Wextra \
        src/blocksched_selftest.cpp -o build/blocksched_selftest 2>&1 \
        | grep -v 'overriding deployment version' || true
    if [ ! -x build/blocksched_selftest ]; then
        fail "reference arm did not compile"
    else
        step "running the self-test (exit code == number of failed checks)"
        ./build/blocksched_selftest || fail "self-test reported failures"
    fi
fi

# --- 2. the CSV export --------------------------------------------------------
# `source_dir`/`denylist_path` in release.config.json point OUTSIDE this
# artifact, into the private umbrella repo it was staged from (vendoring the
# raw source would leak exactly what the export exists to sanitize; the
# denylist's own header forbids re-typing it elsewhere). Exit 77
# (EXIT_OUTSIDE_UMBRELLA, tools/gate_env.py) means this stage detected that
# and is not runnable from a standalone copy -- a documented, honest gap
# distinct from a broken tree, not something to fail the build over.
step "exporting the result CSVs under the public profile"
"$PY" tools/export_csvs.py --quiet
rc=$?
if [ "$rc" = 77 ]; then
    skip_source "CSV export -- pre-distribution check, runs in the source repo only"
elif [ "$rc" != 0 ]; then
    fail "CSV export gate"
fi

# --- 3. the denylist gate over the WHOLE bundle -------------------------------
# Per file, not per directory: the leak that mattered historically was in one
# column of one raw artifact, not in anything rendered.
step "scanning the assembled bundle against the kernel denylist"
"$PY" tools/scan_denylist.py
rc=$?
if [ "$rc" = 77 ]; then
    skip_source "denylist scan -- pre-distribution check, runs in the source repo only"
elif [ "$rc" != 0 ]; then
    fail "denylist scan"
fi

if [ "${1:-all}" = "gate" ]; then
    echo
    if [ "$FAIL" != 0 ]; then
        echo "GATE FAILED"
    elif [ "$SKIPPED" != 0 ]; then
        echo "GATE CLEAN, $SKIPPED stage(s) skipped (see above -- pre-distribution checks unavailable outside the source repo, not failures)"
    else
        echo "GATE CLEAN"
    fi
    exit "$FAIL"
fi

# --- 4. the paper -------------------------------------------------------------
# paper.tex \graphicspath{{figs/}}s every \includegraphics{fig_*} -- tectonic
# cannot typeset the paper without paper/figs/ already populated, so figures.py
# runs first. figures.py handles the columns this release withholds itself
# (skips the affected figure, prints why, keeps going -- see paper/columns.py);
# a nonzero exit here means something else broke.
step "generating the paper's figures"
FIG_TOTAL="$(count_figures_total)"
FIG_WRITTEN=0
FIG_STAGE=notrun
FIG_POLICY=0
FIG_DEP=0
if [ "$DATA_PRESENT" = 0 ]; then
    # `nodata`, not `notrun`. verify.sh reads this word out of the BUILD SUMMARY
    # line below and reports the stage as n/a rather than as a partial
    # reproduction, so the two states must stay distinguishable here.
    FIG_STAGE=nodata
    skip_data "figures ($FIG_TOTAL of them) -- $DATA_NOTE"
elif "$PY" -c "import numpy, matplotlib" 2>/dev/null; then
    figout="$( cd paper && "$PY" figures.py 2>&1 )"; frc=$?
    printf '%s\n' "$figout"
    [ "$frc" = 0 ] || fail "figures.py"
    FIG_STAGE=ran
    # figures.py's own tally is the authority; the ast count above is only the
    # fallback for the case where this stage did not run at all.
    figline="$(printf '%s\n' "$figout" | grep -Eo '^[0-9]+/[0-9]+ figures written' | tail -1)"
    if [ -n "$figline" ]; then
        FIG_WRITTEN="${figline%%/*}"
        FIG_TOTAL="$(printf '%s' "$figline" | sed -E 's#^[0-9]+/([0-9]+).*#\1#')"
    fi
    # Which blocker, per figure. Reported separately because they are not the
    # same news: a withheld column is a tier boundary the reader cannot cross,
    # a missing dependency is a pip install. Getting this backwards is #27,
    # which cost a reader a 100 MB download for a figure that was never coming.
    FIG_POLICY="$(printf '%s\n' "$figout" | grep -c 'skipped -- .*withheld')"
    FIG_DEP="$(printf '%s\n' "$figout" | grep -c 'skipped -- missing dependency')"
else
    skip_tool "numpy/matplotlib not installed under $PY (needed to regenerate paper/figs/)"
fi

step "typesetting the paper"
# paper.tex \includegraphics{fig_*} out of paper/figs/, which figures.py writes
# and which this tier does not ship pre-rendered either. With no data there are
# no figures, so tectonic would fail on a missing graphic -- which reads like a
# broken LaTeX install rather than like the withheld input it is.
if [ "$DATA_PRESENT" = 0 ]; then
    skip_data "typesetting -- paper.tex needs paper/figs/, which the figure stage
           above could not draw. Same cause, same non-failure."
elif command -v tectonic >/dev/null 2>&1; then
    mkdir -p build/tex
    ( cd paper && tectonic -X compile paper.tex --outdir ../build/tex --keep-logs ) \
        || fail "tectonic"
    grep -h "Output written" build/tex/paper.log 2>/dev/null || true
else
    # Name an instruction that works on the platform this is running on.
    # `brew install tectonic` was printed unconditionally, and this release is
    # Linux-first: the upstream installer script is the one line that works
    # everywhere and needs no package manager.
    if [ "$(uname -s)" = "Darwin" ]; then
        skip_tool "tectonic not installed (brew install tectonic, or cargo install tectonic)"
    else
        skip_tool "tectonic not installed (curl --proto '=https' --tlsv1.2 -fsSL https://drop-sh.fullyjustified.net | sh, or cargo install tectonic)"
    fi
fi

step "reprinting every number in the prose from the released CSVs"
SEC_TOTAL="$(count_sections_total)"
SEC_SKIPPED=0
SEC_STAGE=notrun
if [ "$DATA_PRESENT" = 0 ]; then
    SEC_STAGE=nodata
    skip_data "prose ($SEC_TOTAL sections) -- $DATA_NOTE"
elif "$PY" -c "import numpy" 2>/dev/null; then
    # paper_numbers.py now handles the columns this release withholds itself:
    # each affected section catches the gap, prints which output is
    # unavailable and why, and the script still exits 0 -- a documented,
    # honestly-reported skip is not a build failure. A nonzero exit here
    # means something ELSE broke; see the script's own traceback, not
    # CONFLICTS.md.
    pnout="$( cd paper && "$PY" paper_numbers.py 2>&1 )"; prc=$?
    printf '%s\n' "$pnout"
    [ "$prc" = 0 ] || fail "paper_numbers.py"
    SEC_STAGE=ran
    secline="$(printf '%s\n' "$pnout" | grep -Eo '^[0-9]+ of [0-9]+ section\(s\) skipped' | tail -1)"
    if [ -n "$secline" ]; then
        SEC_SKIPPED="${secline%% *}"
        SEC_TOTAL="$(printf '%s' "$secline" | sed -E 's#^[0-9]+ of ([0-9]+) .*#\1#')"
    fi
else
    skip_tool "numpy not installed under $PY"
fi

# --- what this build actually produced ----------------------------------------
# The trailer below used to be the only thing a caller read, and it said
# "BUILD CLEAN" whether fourteen figures were written or none. The counts now
# sit next to it, because a number on the screen is the only version of this
# a reader will see -- release/templates/verify.sh parses the BUILD SUMMARY
# line rather than re-deriving any of it.
step "what this build actually produced"
if [ "$FIG_STAGE" = ran ]; then
    printf 'figures     %s of %s re-derived, %s skipped' \
        "$FIG_WRITTEN" "$FIG_TOTAL" "$((FIG_TOTAL - FIG_WRITTEN))"
    [ "$FIG_POLICY" != 0 ] && printf ' -- %s by this release'\''s export policy' "$FIG_POLICY"
    [ "$FIG_DEP"    != 0 ] && printf ', %s for a missing dependency' "$FIG_DEP"
    printf '\n'
elif [ "$FIG_STAGE" = nodata ]; then
    # The count still goes on the screen. "0 of 14" is the honest headline and
    # burying it would be the same defect as printing BUILD CLEAN over it.
    printf 'figures     0 of %s re-derived -- WITHHELD: this tier ships no data/, so\n' "$FIG_TOTAL"
    printf '            there is nothing for the figure stage to read\n'
else
    printf 'figures     0 of %s re-derived -- the figure stage did not run, so the\n' "$FIG_TOTAL"
    printf '            export-policy skips are not even visible yet\n'
fi
# A stage that did not run re-derived NOTHING, which is not the same arithmetic
# as "total minus the skips it reported" -- it reported none. Deriving the
# written count from SEC_SKIPPED alone printed `sections=15/15` for a stage
# that never started, which is this whole issue in one subtraction.
if [ "$SEC_STAGE" = ran ]; then
    SEC_WRITTEN="$((SEC_TOTAL - SEC_SKIPPED))"
    printf 'prose       %s of %s sections re-derived, %s skipped by the export policy\n' \
        "$SEC_WRITTEN" "$SEC_TOTAL" "$SEC_SKIPPED"
elif [ "$SEC_STAGE" = nodata ]; then
    SEC_WRITTEN=0
    printf 'prose       0 of %s sections re-derived -- WITHHELD: same data/, same reason\n' "$SEC_TOTAL"
else
    SEC_WRITTEN=0
    printf 'prose       0 of %s sections re-derived -- the prose stage did not run\n' "$SEC_TOTAL"
fi
if [ "$DATA_PRESENT" = 0 ]; then
    printf '\n'
    printf 'None of that is a failure, and none of it is fixable by installing anything.\n'
    printf 'The released artifact SHIPS these CSVs in data/ -- the gated public-profile\n'
    printf 'export -- so this copy is stripped or predates the 2026-08-07 publication.\n'
    printf 'See the Reproduction kit section of the top-level README.md, and\n'
    printf 'CONFLICTS.md for the export policy that governs the data.\n'
fi

echo
printf 'BUILD SUMMARY figures=%s/%s figstage=%s sections=%s/%s secstage=%s skipped_tool=%s skipped_source=%s skipped_data=%s\n' \
    "$FIG_WRITTEN" "$FIG_TOTAL" "$FIG_STAGE" \
    "$SEC_WRITTEN" "$SEC_TOTAL" "$SEC_STAGE" \
    "$SKIP_TOOL" "$SKIP_SOURCE" "$SKIP_DATA"

if [ "$FAIL" != 0 ]; then
    echo "BUILD FAILED"
elif [ "$SKIPPED" != 0 ]; then
    # Name the two kinds of skip separately. This line said "missing optional
    # tools" for every skip until 2026-08-06, including the two that are
    # ALWAYS the source kind in a distributed copy -- so it told a reader to go
    # and install something that does not exist, and verify.sh relayed the
    # wrong reason verbatim. `./build.sh gate` had the right words all along.
    reason=""
    [ "$SKIP_SOURCE" != 0 ] && reason="$SKIP_SOURCE pre-distribution check(s) unavailable outside the source repo"
    if [ "$SKIP_DATA" != 0 ]; then
        [ -n "$reason" ] && reason="$reason, "
        reason="$reason$SKIP_DATA stage(s) whose result CSVs this tier withholds"
    fi
    if [ "$SKIP_TOOL" != 0 ]; then
        [ -n "$reason" ] && reason="$reason, "
        reason="$reason$SKIP_TOOL missing optional tool(s) on this machine"
    fi
    echo "BUILD CLEAN, $SKIPPED stage(s) skipped: $reason. See above -- not failures, and not a claim that the paper reproduced."
else
    echo "BUILD CLEAN"
fi
exit "$FAIL"
