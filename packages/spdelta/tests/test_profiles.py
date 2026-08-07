"""The public/private split: configuration, not a fork."""

from __future__ import annotations

import re
import textwrap

import pytest

import spdelta
from spdelta import PUBLIC, Profile, ToySpec, active, derive, load, use
from spdelta.profiles import PROFILE_ENV_VAR


def test_the_public_profile_picks_no_reduction():
    """Choosing moves published numbers, so the public default declines to."""
    assert PUBLIC.reduction is None


def test_the_public_profile_ships_only_generated_operators():
    for spec in PUBLIC.operators:
        assert spec.kind in {"banded", "grid2d", "fanout"}
        assert isinstance(spec.seed, int)


def test_derive_requires_a_new_name():
    with pytest.raises(ValueError, match="requires a new 'name'"):
        derive(PUBLIC, steps=1000)


def test_derive_refuses_to_reuse_the_base_name():
    with pytest.raises(ValueError, match="must not reuse the name"):
        derive(PUBLIC, name="public", steps=1000)


def test_derive_inherits_every_field_it_was_not_given():
    variant = derive(PUBLIC, name="variant", steps=999)
    assert variant.steps == 999
    assert variant.operators == PUBLIC.operators
    assert variant.tolerance == PUBLIC.tolerance


def test_a_profile_is_immutable():
    with pytest.raises(Exception):
        PUBLIC.steps = 1  # type: ignore[misc]


def test_use_pins_the_active_profile_and_none_restores_the_default():
    variant = derive(PUBLIC, name="pinned", steps=7)
    use(variant)
    assert active() is variant
    use(None)
    assert active() is PUBLIC


def test_use_rejects_something_that_is_not_a_profile():
    with pytest.raises(TypeError, match="expected a Profile"):
        use({"steps": 5})  # type: ignore[arg-type]


def test_the_environment_variable_selects_an_overlay(tmp_path, monkeypatch):
    """The documented private hook, exercised end to end."""
    module = tmp_path / "overlay_profile.py"
    module.write_text(
        textwrap.dedent(
            """
            from spdelta.profiles import PUBLIC, derive

            INTERNAL = derive(PUBLIC, name="overlay", steps=4242,
                              reduction="reduce_flat")
            """
        )
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setenv(PROFILE_ENV_VAR, "overlay_profile:INTERNAL")
    assert active().name == "overlay"
    assert active().steps == 4242
    assert active().reduction == "reduce_flat"


def test_a_pinned_profile_wins_over_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv(PROFILE_ENV_VAR, "nonexistent_module:X")
    variant = derive(PUBLIC, name="pinned")
    use(variant)
    assert active() is variant


def test_load_rejects_a_spec_without_a_colon():
    with pytest.raises(ValueError, match="must be 'module:ATTRIBUTE'"):
        load("mycorp.bench_profile")


def test_load_rejects_a_missing_attribute(tmp_path, monkeypatch):
    (tmp_path / "empty_overlay.py").write_text("")
    monkeypatch.syspath_prepend(str(tmp_path))
    with pytest.raises(ValueError, match="has no attribute"):
        load("empty_overlay:INTERNAL")


def test_load_rejects_a_duck_typed_near_miss(tmp_path, monkeypatch):
    (tmp_path / "fake_overlay.py").write_text("INTERNAL = {'steps': 5}")
    monkeypatch.syspath_prepend(str(tmp_path))
    with pytest.raises(TypeError, match="not a spdelta Profile"):
        load("fake_overlay:INTERNAL")


def test_describe_lists_every_field():
    text = PUBLIC.describe()
    for field in (
        "steps",
        "repeats",
        "batch",
        "stat",
        "rotate",
        "tolerance",
        "rho_grid",
        "n_dirty",
        "bootstrap_reps",
        "nnz_bands",
        "drift_radius",
        "reduction",
        "operators",
    ):
        assert field in text, field


def test_the_documented_knobs_all_exist_on_the_profile():
    """The docstring table and the dataclass must not drift apart."""
    import spdelta.profiles as module

    rule = "=" * 25 + "  " + "=" * 50
    body = module.__doc__.split(rule)[2]
    documented = set(re.findall(r"^``([A-Za-z_]+)``", body, flags=re.MULTILINE))
    documented |= set(re.findall(r"^``[A-Za-z_]+``, ``([A-Za-z_]+)``", body, flags=re.MULTILINE))
    assert documented, "the knob table did not parse"
    fields = set(Profile.__dataclass_fields__)
    assert documented <= fields, f"documented but not a field: {documented - fields}"
    # And the other direction: an undocumented field is a knob that will differ
    # between the public package and an internal overlay without anyone having
    # decided that it should. Only `name` is exempt -- it identifies the
    # profile rather than tuning anything.
    assert fields - documented == {"name"}, f"undocumented: {fields - documented}"


def test_defaults_are_read_from_the_profile_not_hardcoded_at_the_call_site(
    tiny_profile,
):
    """Change one place, and the sweep changes. That is the whole claim."""
    from spdelta import ladder, reference, standard_cells, sweep
    from spdelta.motion import jump_plain
    from spdelta.operators import suite

    use(tiny_profile)
    operators = suite()
    assert [n for n, _ in operators] == [s.name for s in tiny_profile.operators]
    cells = standard_cells(
        operators[:1], [lambda n, m, r: jump_plain(int(m.shape[1]), r)]
    )
    rows = sweep(ladder(), cells, reference=reference())
    assert {r["steps"] for r in rows} == {tiny_profile.steps}
    assert {r["batch"] for r in rows} == {tiny_profile.batch}
    assert {r["n_dirty"] for r in rows} == {tiny_profile.n_dirty}
    assert {r["rho"] for r in rows} == set(tiny_profile.rho_grid)
    assert {r["tol"] for r in rows} == {tiny_profile.tolerance}
    assert {r["stat"] for r in rows} == {tiny_profile.stat}


def test_a_toy_spec_is_hashable_and_comparable():
    a = ToySpec(name="x", kind="banded", n_cols=10, param=3, seed=0)
    b = ToySpec(name="x", kind="banded", n_cols=10, param=3, seed=0)
    assert a == b
    assert len({a, b}) == 1


def test_the_package_exposes_the_profile_surface():
    """Importable *and* advertised.

    A name that resolves but is missing from ``__all__`` is a name that will be
    dropped by the next tidy-up, and the profile surface is the documented hook
    an internal overlay depends on.
    """
    for name in ("PUBLIC", "Profile", "ToySpec", "active", "derive", "load", "use"):
        assert hasattr(spdelta, name), name
        assert name in spdelta.__all__, name
