"""Building the list of documents to scan -- the least-tested line in any linter.

A corpus builder that returns nothing makes every assertion downstream pass.
One bad pathspec, one rename convention nobody propagated, one `git` that is
not on PATH inside CI, and the run is green having read zero files. That is
`corpus vacuity` in VACUOUS_TESTS.md, and it is why `claimlint.ratchet` ends in
a floor check rather than trusting this module.

Two builders, in order of preference:

  1. `git ls-files` -- tracked files only, which is almost always what you
     want: it skips build output, vendored trees and anything gitignored
     without needing a rule for each.
  2. a filesystem walk -- for a non-repository, or a git that fails.

Which one ran is recorded on the result, because "the corpus shrank" and "the
builder changed" are different problems with the same symptom.
"""

from __future__ import annotations

import fnmatch
import os
import subprocess
from dataclasses import dataclass, field

__all__ = ["Corpus", "discover"]


@dataclass
class Corpus:
    root: str
    paths: list[str] = field(default_factory=list)
    builder: str = ""
    note: str = ""

    def __len__(self) -> int:
        return len(self.paths)


def _matches(path: str, patterns: list[str]) -> bool:
    normal = path.replace(os.sep, "/")
    for pattern in patterns:
        if fnmatch.fnmatch(normal, pattern):
            return True
        # `**/*.md` should also match a file at the root.
        if pattern.startswith("**/") and fnmatch.fnmatch(normal, pattern[3:]):
            return True
    return False


def _git_files(root: str) -> list[str] | None:
    try:
        done = subprocess.run(
            ["git", "-C", root, "ls-files"],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    return done.stdout.splitlines()


def _walked_files(root: str) -> list[str]:
    """Tree-relative paths, always with "/" separators.

    `git ls-files` emits "/" on every platform, so the two builders must agree
    or a document's identity changes with the operating system -- and a
    document's identity is what the allowlist and the ratchet are keyed on.
    Without the normalisation, a Windows run reported every allowlisted
    document as an unallowlisted violation AND every allowlist entry as stale
    ("document no longer in the corpus"), on a corpus where nothing had moved.
    `_matches` below already normalised for globbing, so the corpus was found;
    only the recorded path was host-shaped. First seen 2026-08-07, in the first
    CI run that gated this tree off Linux.
    """
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in {".git", "__pycache__"}]
        for name in filenames:
            rel = os.path.relpath(os.path.join(dirpath, name), root)
            found.append(rel.replace(os.sep, "/"))
    return found


def discover(
    root: str,
    include: list[str],
    exclude: list[str],
    *,
    prefer_git: bool = True,
) -> Corpus:
    """Every document under `root` matching `include` and not `exclude`."""
    candidates = _git_files(root) if prefer_git else None
    builder = "git ls-files"
    note = ""
    if candidates is None:
        candidates = _walked_files(root)
        builder = "filesystem walk"
        note = "git ls-files was unavailable or failed; untracked files are included"

    paths = sorted(
        p for p in candidates if _matches(p, include) and not _matches(p, exclude)
    )
    return Corpus(root=root, paths=paths, builder=builder, note=note)
