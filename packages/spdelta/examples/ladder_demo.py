"""Run the worked example without installing anything but the dependencies.

    python examples/ladder_demo.py

Identical to ``python -m spdelta.example``; this file exists so the example is
findable from a directory listing.
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from spdelta.example import main  # noqa: E402

if __name__ == "__main__":
    main()
