"""Make the package importable from a checkout without installing it."""

from __future__ import annotations

import pathlib
import sys

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import spdelta  # noqa: E402
from spdelta import profiles  # noqa: E402


@pytest.fixture()
def tiny_profile() -> profiles.Profile:
    """A profile small enough to run inside a test.

    Derived rather than hand-built, so a field added to Profile is inherited
    here automatically instead of making the test suite the place that forgets
    it.
    """
    return profiles.derive(
        profiles.PUBLIC,
        name="test-tiny",
        steps=6,
        repeats=2,
        batch=2,
        n_dirty=12,
        # Deliberately not the public value: a test that pins a knob to the
        # default cannot tell whether the knob is being read at all.
        tolerance=5e-10,
        rho_grid=(0.25,),
        bootstrap_reps=50,
        operators=(
            profiles.ToySpec(name="band_240_w5", kind="banded", n_cols=240, param=5, seed=1),
            profiles.ToySpec(name="fanout_240_4", kind="fanout", n_cols=240, param=4, seed=2),
        ),
    )


@pytest.fixture(autouse=True)
def _reset_profile():
    """No test may leak a pinned profile into another."""
    yield
    spdelta.use(None)
