"""Doc lookup and the two binding kinds."""

from __future__ import annotations

import pytest

from bindnum import (
    AmbiguousLabel,
    Binding,
    BindingError,
    Doc,
    NonDiscriminatingPair,
    SectionNotFound,
    ValueNotFound,
    binds,
    binds_pair,
    bindings,
    check_all,
    mutation_verified,
)

SAMPLE = """\
# Report

Intro text with 99 in it.

## Headline

The throughput ratio is **1.46x** across the sweep.

## Table

| part | ratio |
|---|---|
| bracket | 2.40x |
| flange | 1.90x |

## Arms

- quiet arm: 1.02x
- loud arm: 0.98x

## Repeats

The step count is 12 in the first pass.
The step count is 12 in the second pass.

## Appendix

The throughput ratio is 9.99x in the superseded pilot run.
"""


@pytest.fixture
def doc(tmp_path):
    path = tmp_path / "REPORT.md"
    path.write_text(SAMPLE, encoding="utf-8")
    return Doc(path)


# --------------------------------------------------------------------------
# locating a stated value
# --------------------------------------------------------------------------


@mutation_verified(
    "2026-08-04",
    "made Doc.stated ignore `section` and search the whole document",
    result="AmbiguousLabel -- the Appendix carries the same label; reverted; passes",
)
def test_a_label_is_found_inside_its_section(doc):
    assert doc.stated("throughput ratio", section="Headline").number == 1.46
    assert doc.stated("| bracket |", section="Table").number == 2.40


@mutation_verified(
    "2026-08-04",
    "returned hits[0] instead of raising when more than one line matched",
    result="this test stops raising; reverted; passes",
)
def test_an_ambiguous_label_is_an_error_not_a_first_match(doc):
    """Silent first-match is how a binding starts following the wrong site."""
    with pytest.raises(AmbiguousLabel, match="appears 2 times"):
        doc.stated("step count is")
    assert doc.stated("step count is", occurrence=1).number == 12


@mutation_verified(
    "2026-08-04",
    "changed `if not hits:` to `if False:` in Doc.stated",
    result="IndexError instead of ValueNotFound; reverted; passes",
)
def test_a_missing_label_and_a_missing_section_both_raise(doc):
    with pytest.raises(ValueNotFound):
        doc.stated("no such phrase")
    with pytest.raises(SectionNotFound):
        doc.stated("throughput", section="Nonexistent")


@mutation_verified(
    "2026-08-04",
    "dropped the len(matches) > 1 guard in section_span",
    result="this test stops raising; reverted; passes",
)
def test_two_headings_matching_one_fragment_is_an_error(tmp_path):
    path = tmp_path / "D.md"
    path.write_text("## Results A\n1.0x\n\n## Results B\n2.0x\n", encoding="utf-8")
    with pytest.raises(SectionNotFound, match="matches 2 headings"):
        Doc(path).stated("x", section="Results")


@mutation_verified(
    "2026-08-04",
    "deleted the `if raw is None and after_label` whole-line fallback in Doc.stated",
    result="ValueNotFound; reverted; passes",
)
def test_a_number_before_its_label_is_still_found(doc):
    """Prose puts the number first as often as last; both must resolve."""
    assert doc.stated("across the sweep", section="Headline").number == 1.46


# --------------------------------------------------------------------------
# comparison is at the precision the document states
# --------------------------------------------------------------------------


@mutation_verified(
    "2026-08-04",
    "made values_match use a fixed abs_tol of 0.1 instead of inferring places",
    result="the 1.52 case stops failing; reverted; passes",
)
def test_agreement_is_exact_at_the_stated_precision(doc):
    @binds(doc, section="Headline", label="throughput ratio")
    def close_enough() -> float:
        return 1.4632

    @binds(doc, section="Headline", label="throughput ratio", name="too_far")
    def too_far() -> float:
        return 1.52

    ok, bad = bindings()
    ok.check()
    with pytest.raises(BindingError, match="disagrees with its derivation"):
        bad.check()


@mutation_verified(
    "2026-08-04",
    "removed the abs_tol branch from values_match so the inferred rule always wins",
    result="BindingError on 1.52 vs 1.46; reverted; passes",
)
def test_an_explicit_tolerance_overrides_the_inferred_one(doc):
    @binds(doc, section="Headline", label="throughput ratio", abs_tol=0.1)
    def loose() -> float:
        return 1.52

    loose_binding = bindings()[0]
    loose_binding.check()


# --------------------------------------------------------------------------
# both failure directions
# --------------------------------------------------------------------------


@mutation_verified(
    "2026-08-04",
    "removed the values_match call from Binding.check so it never compares",
    result="the post-edit binding stops raising; reverted; passes",
)
def test_editing_the_prose_breaks_the_binding(tmp_path):
    path = tmp_path / "R.md"
    path.write_text("## H\n\nratio is 1.46x\n", encoding="utf-8")

    def derivation() -> float:
        return 1.4632

    binds(Doc(path), section="H", label="ratio is")(derivation)
    bindings()[0].check()

    path.write_text("## H\n\nratio is 1.47x\n", encoding="utf-8")
    binds(Doc(path), section="H", label="ratio is", name="after")(derivation)
    with pytest.raises(BindingError):
        bindings()[1].check()


@mutation_verified(
    "2026-08-04",
    "removed the values_match call from Binding.check so it never compares",
    result="the data-moved direction stops raising; reverted; passes",
)
def test_moving_the_data_breaks_the_binding(doc):
    @binds(doc, section="Headline", label="throughput ratio")
    def moved() -> float:
        return 1.5632

    with pytest.raises(BindingError):
        bindings()[0].check()


# --------------------------------------------------------------------------
# pair bindings: the swap, not the typo
# --------------------------------------------------------------------------


@mutation_verified(
    "2026-08-04",
    "removed the `direct` comparison from PairBinding.check",
    result="the swapped pair stops raising; reverted; passes",
)
def test_a_pair_binding_catches_an_arm_swap(doc):
    @binds_pair(
        doc,
        first=dict(section="Arms", label="quiet arm"),
        second=dict(section="Arms", label="loud arm"),
    )
    def swapped() -> tuple[float, float]:
        return 0.9793, 1.0192  # the right two numbers, the wrong two labels

    with pytest.raises(BindingError, match="pair disagrees"):
        bindings()[0].check()


@mutation_verified(
    "2026-08-04",
    "deleted the swapped-also-passes check from PairBinding.check",
    result="this test stops raising and goes green on a vacuous pair; reverted; passes",
)
def test_a_pair_that_cannot_detect_a_swap_is_reported_not_passed(tmp_path):
    """Two figures that collide at the stated precision prove nothing.

    Both bindings match. Both would still match with the derivations swapped.
    A suite that goes green here is asserting that two numbers exist.
    """
    path = tmp_path / "C.md"
    path.write_text("## Arms\n\n- quiet arm: 1.0x\n- loud arm: 1.0x\n", encoding="utf-8")

    @binds_pair(
        Doc(path),
        first=dict(section="Arms", label="quiet arm"),
        second=dict(section="Arms", label="loud arm"),
    )
    def colliding() -> tuple[float, float]:
        return 1.02, 0.98  # both round to 1.0

    with pytest.raises(NonDiscriminatingPair, match="swapped"):
        bindings()[0].check()


@mutation_verified(
    "2026-08-04",
    "deleted the `window` block from PairBinding.check",
    result="this test stops raising; reverted; passes",
)
def test_the_window_requires_a_visible_separation(doc):
    @binds_pair(
        doc,
        first=dict(section="Arms", label="quiet arm"),
        second=dict(section="Arms", label="loud arm"),
        window=0.5,
    )
    def too_close() -> tuple[float, float]:
        return 1.0192, 0.9793

    with pytest.raises(NonDiscriminatingPair, match="under the required window"):
        bindings()[0].check()


@mutation_verified(
    "2026-08-04",
    "removed the len(values) != 2 guard from PairBinding.derived",
    result="ValueError from tuple unpacking, not BindingError; reverted; passes",
)
def test_a_pair_derivation_must_return_two_values(doc):
    @binds_pair(
        doc,
        first=dict(section="Arms", label="quiet arm"),
        second=dict(section="Arms", label="loud arm"),
    )
    def three() -> tuple[float, float, float]:
        return 1.0, 2.0, 3.0

    with pytest.raises(BindingError, match="exactly two values"):
        bindings()[0].check()


# --------------------------------------------------------------------------
# the registry
# --------------------------------------------------------------------------


@mutation_verified(
    "2026-08-04",
    "made check_all() return 0 on an empty registry instead of raising",
    result="this test stops raising; reverted; passes",
)
def test_check_all_refuses_an_empty_registry():
    """Nothing registered means the module holding the bindings was never
    imported, and every assertion over it passes."""
    with pytest.raises(AssertionError, match="no bindings registered"):
        check_all()


@mutation_verified(
    "2026-08-04",
    "made check_all return after checking the first binding",
    result="the second (bad) binding is never reached and this stops raising; "
    "reverted; passes",
)
def test_check_all_runs_every_registered_binding(doc):
    """It must reach the last one, not stop at the first that passes."""

    @binds(doc, section="Headline", label="throughput ratio")
    def one() -> float:
        return 1.4632

    @binds(doc, section="Table", label="| flange |")
    def two() -> float:
        return 1.9042

    assert check_all() == 2
    assert all(isinstance(b, Binding) for b in bindings())

    @binds(doc, section="Table", label="| bracket |", name="last_one_is_wrong")
    def three() -> float:
        return 9.99

    with pytest.raises(BindingError, match="last_one_is_wrong"):
        check_all()
