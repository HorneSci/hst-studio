"""Make bindnum importable without installing it, and load the teeth plugin.

An uninstalled checkout should still run `python -m pytest` in one command;
that is the fifteen-minute path's first minute.

Only do either of those things when bindnum is not already installed. An
editable or normal install (`pip install -e ".[test]"`) already puts `src/`
on `sys.path` and registers `bindnum.teeth.plugin` once, automatically, via
the `pytest11` entry point in `pyproject.toml`. Doing it a second time here
made pluggy raise `ValueError: Plugin already registered under a different
name` the moment someone followed the README's own install step and then ran
`python -m pytest` from this directory -- the two paths (installed, and
run-in-place) are each fine alone and were never meant to be combined.
"""

from __future__ import annotations

import importlib.util
import os
import sys

if importlib.util.find_spec("bindnum") is None:
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
    pytest_plugins = ["bindnum.teeth.plugin"]
