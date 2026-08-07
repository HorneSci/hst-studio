"""claimlint -- statcheck for performance claims.

statcheck (Nuijten et al., *Behavior Research Methods* 48, 2016) recomputes the
p-values reported in psychology papers from the test statistics printed beside
them, and flags the ones that do not follow. It is not a better statistics
course; it is a mechanical check on text that already exists, run over a corpus
nobody is going to rewrite. It found inconsistencies in roughly half the papers
it scanned.

claimlint is the same shape of intervention, aimed at a different check. It
does not recompute anything -- there is nothing to recompute, because a
performance ratio is not derivable from the sentence containing it. What it
checks is whether the *conditions* that make the ratio mean something are
stated near it: what it was measured against, on what hardware, over how many
runs, with which toolchain.

That is the weaker check, and it is the one that catches the failure that
actually happens. A ratio quoted without its baseline is not a wrong number.
It is a number a reader cannot evaluate, cannot reproduce, and will re-quote
somewhere the missing condition matters.

    python -m claimlint .

Zero configuration; a domain-free default profile; everything tunable lives in
`.claimlint.toml` with a documented private-overlay hook. The ratchet, not the
scanner, is what makes it adoptable on a corpus you inherited.
"""

from __future__ import annotations

import sys

if sys.version_info < (3, 11):
    # Below this, .config's `import tomllib` (stdlib since 3.11, needed to
    # read .claimlint.toml) fails as a bare `ModuleNotFoundError` pointing at
    # config.py's import line -- accurate, but it names the missing module,
    # not the actual requirement or the Python this run is short by. Since
    # `python -m claimlint` imports this package before it can reach
    # __main__.py, the floor has to be checked here to say anything useful
    # before that import chain runs.
    raise ImportError(
        "claimlint requires Python 3.11+ (it reads .claimlint.toml with the "
        f"stdlib tomllib module, added in 3.11); this interpreter is "
        f"{sys.version_info.major}.{sys.version_info.minor}. "
        "Run it with python3.11 or newer."
    )

from .api import Result, run
from .config import AllowEntry, Config, ConfigError, load, load_data
from .corpus import Corpus, discover
from .ratchet import RatchetResult, allowlist_stanza, check_floors, run_ratchet
from .scan import (
    DEFAULT_RATIO,
    Claim,
    FileReport,
    find_claims,
    scan_file,
    scan_text,
    strip_markup,
)

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "run",
    "Result",
    "load",
    "load_data",
    "Config",
    "AllowEntry",
    "ConfigError",
    "discover",
    "Corpus",
    "scan_text",
    "scan_file",
    "find_claims",
    "strip_markup",
    "Claim",
    "FileReport",
    "DEFAULT_RATIO",
    "run_ratchet",
    "check_floors",
    "allowlist_stanza",
    "RatchetResult",
]
