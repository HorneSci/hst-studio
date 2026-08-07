from __future__ import annotations

# The Python-3.11 floor is checked in claimlint/__init__.py, not here --
# `python -m claimlint` imports the `claimlint` package first (to find this
# submodule), so by the time this file's own code would run, an interpreter
# below the floor has already failed with a message that names it.
from .cli import main

raise SystemExit(main())
