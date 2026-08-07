#!/usr/bin/env python3
"""Scan every file in the release bundle against the kernel identifier denylist.

The denylist's matching contract is PLAIN SUBSTRING, CASE-INSENSITIVE, no word
boundaries, and it is deliberately over-blocking: a false positive costs one
rename, a false negative ships kernel source. This script does not soften it
with a PER-TOKEN exemption list -- a token that hits is never suppressed, and
an exemption that lives in the scanner is an exemption nobody reviews. When a
token hits, rename the data.

That is a different thing from a PATH exemption, and this script has one:
`SKIP_DIRS`/`SKIP_SUFFIX` below skip `.git`/`__pycache__`/`build`/
`.pytest_cache` and binary/generated suffixes (`.pdf .png .pyc .o .so
.dylib`) outright, because they are either not text (grepping a substring
through a compiled `.so` or a rendered `.pdf` is not the same check as
scanning source) or themselves build output already derived from files this
scan does cover. This used to be undocumented -- the exemption existed but
the docstring said "no exemption list", which is a comment that is wrong,
not just incomplete. State it here instead of claiming it doesn't exist:
these five path patterns are the only bytes this scan does not read.

    python3 tools/scan_denylist.py            # scan the whole bundle
    python3 tools/scan_denylist.py --verbose  # print the matching lines

Exit code is the number of files with at least one hit, OR a value >=
CANARY_EXIT_FLOOR if the scan's own preconditions failed (denylist file
missing/truncated, or the matching logic itself does not catch a token it is
handed) -- see `_selftest_or_die`. Without that floor, an empty or
unreadable denylist scans every file against zero tokens, finds zero hits,
and exits 0: "clean" and "broken" would print almost identically (`N files
scanned against 0 tokens, 0 with hits`) and only the `0 tokens` would tell
you, easy to miss in a scrollback. A denylist that fails to load must not be
able to read as clean.

One more exit code: EXIT_OUTSIDE_UMBRELLA (77, `tools/gate_env.py`), when the
denylist path resolves outside this artifact and does not exist -- i.e. this
copy is a standalone distribution, not the umbrella repo the denylist lives
in. That is a DIFFERENT condition from "the denylist failed to load" (which
still refuses and uses CANARY_EXIT_FLOOR): it means the check was never
runnable here, not that it ran and found nothing.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from gate_env import outside_umbrella, EXIT_OUTSIDE_UMBRELLA

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

SKIP_DIRS = {".git", "__pycache__", "build", ".pytest_cache"}
SKIP_SUFFIX = {".pdf", ".png", ".pyc", ".o", ".so", ".dylib"}

#: A little below the denylist's real size (66 non-comment tokens as of
#: 2026-08-05) so trimming a handful of tokens doesn't trip this, but a
#: missing/empty/mostly-comments file does. See the module docstring.
MIN_TOKENS = 20

#: Exit code used ONLY for a scan that never got to run for real (denylist
#: failed to load, or the matching logic itself is broken) -- always well
#: above any plausible `bad` (files-with-hits) count, so a caller checking
#: `exit_code == 0` for "clean" is never fooled, and a caller checking
#: `exit_code` as a hit-count can still tell the two failure shapes apart.
CANARY_EXIT_FLOOR = 1000

#: A token that will never legitimately appear in this bundle, planted into a
#: synthetic string and checked against the SAME `find_hits` function the
#: real scan uses -- not a reimplementation, which is what makes this a
#: canary and not just another assertion that could drift from the code it
#: is meant to guard.
CANARY_TOKEN = "hstfit_denylist_canary_zzq7"


def load_tokens(path):
    with open(path) as fh:
        return [l.strip() for l in fh
                if l.strip() and not l.startswith("#")]


def find_hits(text, tokens):
    """The one matching function -- used by the real scan AND the self-test,
    so a self-test that passes proves the scan's actual logic works, not a
    copy of it that could silently diverge."""
    low = text.lower()
    return [t for t in tokens if t.lower() in low]


def _selftest_or_die(tokens):
    """Fail loudly, before scanning a single real file, if the denylist
    failed to load or the matcher itself cannot catch a token it is handed.
    Both are preconditions the real scan silently assumes; neither produces
    a `HIT` line if it is false, so nothing downstream would ever notice."""
    if len(tokens) < MIN_TOKENS:
        print(f"REFUSING TO SCAN: only {len(tokens)} token(s) loaded, "
              f"expected at least {MIN_TOKENS}. The denylist file is "
              f"missing, empty, or mostly comments -- a scan against a "
              f"near-empty denylist would read as clean regardless of what "
              f"the bundle contains.")
        return False
    canary_text = f"some ordinary line\n{CANARY_TOKEN}\nanother line\n"
    if CANARY_TOKEN.lower() not in [t.lower() for t in tokens]:
        # The canary only proves anything if it IS a loaded token; keep it
        # out of the real denylist file and inject it for this check alone.
        hits = find_hits(canary_text, tokens + [CANARY_TOKEN])
    else:
        hits = find_hits(canary_text, tokens)
    if CANARY_TOKEN.lower() not in [h.lower() for h in hits]:
        print("REFUSING TO SCAN: the canary token was not detected in a "
              "synthetic string that plainly contains it -- the matching "
              "logic in find_hits() is broken, not just the denylist.")
        return False
    return True


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=ROOT)
    ap.add_argument("--config", default=os.path.join(ROOT, "release.config.json"))
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)

    cfg = json.load(open(args.config))
    denylist_path = os.path.join(os.path.dirname(os.path.abspath(args.config)),
                                 cfg["denylist_path"])

    if outside_umbrella(cfg["denylist_path"], denylist_path, args.root):
        print(f"skipped: the kernel identifier denylist ({cfg['denylist_path']}) "
              f"lives in the private umbrella repo this artifact was staged "
              f"from, not in this artifact -- this stage is a pre-distribution "
              f"check that runs there only. A recipient of this artifact "
              f"cannot independently re-run it; the publisher already did, "
              f"before this bundle was assembled (README's 'What this "
              f"artifact does NOT prove' names this limitation). See "
              f"tools/gate_env.py.")
        return EXIT_OUTSIDE_UMBRELLA

    tokens = load_tokens(denylist_path) if os.path.exists(denylist_path) else []

    if not _selftest_or_die(tokens):
        return CANARY_EXIT_FLOOR

    bad = 0
    scanned = 0
    for dirpath, dirnames, filenames in os.walk(args.root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in sorted(filenames):
            path = os.path.join(dirpath, fn)
            if os.path.splitext(fn)[1] in SKIP_SUFFIX:
                continue
            try:
                text = open(path, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            scanned += 1
            hits = find_hits(text, tokens)
            rel = os.path.relpath(path, args.root)
            if hits:
                bad += 1
                print(f"HIT  {rel}: {hits}")
                if args.verbose:
                    for i, line in enumerate(text.split("\n"), 1):
                        ll = line.lower()
                        for t in hits:
                            if t.lower() in ll:
                                print(f"       {i}: {line.strip()[:110]}")
                                break

    if scanned == 0:
        print("REFUSING TO CALL THIS CLEAN: zero files were scanned "
              "(SKIP_DIRS/SKIP_SUFFIX matched everything, or --root points "
              "somewhere empty) -- 0 hits over 0 files is not evidence.")
        return CANARY_EXIT_FLOOR

    print(f"\n{scanned} files scanned against {len(tokens)} tokens, "
          f"{bad} with hits")
    return bad


if __name__ == "__main__":
    sys.exit(main())
