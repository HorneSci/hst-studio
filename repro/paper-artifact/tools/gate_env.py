#!/usr/bin/env python3
"""Detect whether a private-umbrella-only path is reachable from here.

`release.config.json` points two paths OUTSIDE this artifact on purpose:
`source_dir` (the private raw CSVs `export_csvs.py` regenerates `data/`
from) and `denylist_path` (the kernel-identifier denylist `scan_denylist.py`
checks the export against). Both live in the umbrella repo this artifact was
staged from, not in the artifact itself -- vendoring the first would leak
exactly what the export pipeline exists to sanitize, and the second's own
header says "keep this list in ONE place; do not re-type tokens anywhere
else" (`docs/kernel-denylist.txt`), naming three consumers, all internal.

So neither is copied in. Instead: inside the umbrella repo (this artifact's
normal home, and the only place `./build.sh gate` was ever run from before
this fix), both paths resolve and the checks run exactly as before.
Distributed standalone -- the shape `./build.sh gate` is described for in
README ("only the checks that must pass before distribution") -- neither
path exists, and that is an expected property of a public release, not
something broken in the copy the recipient has. `export_csvs.py` and
`scan_denylist.py` both call `outside_umbrella()` to tell the two cases
apart and report the second honestly instead of failing as if the artifact
were corrupt.
"""
import os

#: Autotools' long-standing convention for "this check did not run, on
#: purpose" as opposed to 0 (ran, passed) or any other nonzero (ran, failed).
#: Chosen over a small number precisely because it must never collide with a
#: real result -- `scan_denylist.py` returns a files-with-hits count and
#: `export_csvs.py` returns 0/1/2, all plausible small integers.
EXIT_OUTSIDE_UMBRELLA = 77


def outside_umbrella(configured_path: str, resolved_path: str, artifact_root: str) -> bool:
    """True if `resolved_path` is missing AND `configured_path` was pointed
    outside `artifact_root` in the first place -- i.e. this is the private-
    repo-only case, not a file that went missing from inside the artifact
    (which should still fail loudly, not be waved through as "expected").
    """
    if os.path.exists(resolved_path):
        return False
    real_resolved = os.path.realpath(resolved_path)
    real_root = os.path.realpath(artifact_root)
    try:
        inside = os.path.commonpath([real_resolved, real_root]) == real_root
    except ValueError:      # different drives, etc. -- definitely not inside
        inside = False
    return (not inside) and configured_path.startswith("..")
