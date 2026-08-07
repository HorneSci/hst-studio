"""The claim type: a ratio that cannot travel without its conditions."""

from __future__ import annotations

import math

import pytest

from spdelta import Claim
from spdelta.harness import toolchain


def rows(
    n=3,
    motion="drift[line(radius=3)]",
    rho=0.05,
    baseline="masked_row_scan",
    ratios=None,
):
    ratios = ratios or [2.0] * n
    return [
        {
            "operator": f"op{i}",
            "rho": rho,
            "motion": motion,
            "baseline": baseline,
            "arm": "column_delta_csc",
            "toolchain": toolchain(),
            "control": "reference=scratch_reference; rotate=True",
            "ratio": ratios[i],
        }
        for i in range(len(ratios))
    ]


def a_claim(**overrides) -> Claim:
    fields = dict(
        ratio=2.0,
        baseline="masked_row_scan",
        motion="drift[line(radius=3)]",
        rho=0.05,
        rho_ceiling=0.25,
        toolchain="CPython x / numpy y",
        control="reference=scratch_reference",
        n_cells=12,
        reduction="reduce_median_then_geomean",
    )
    fields.update(overrides)
    return Claim(**fields)


# --------------------------------------------------------------------------
# the number does not come out on its own
# --------------------------------------------------------------------------


def test_a_claim_is_not_a_float():
    """float(claim) must raise. The whole design rests on this."""
    with pytest.raises(TypeError):
        float(a_claim())


def test_float_dunder_is_defined_and_teaches_rather_than_raising_blind():
    """`__float__` IS defined -- on purpose, the opposite of earlier drafts.

    Not defining it left Python's own message: "float() argument must be a
    string or a real number, not 'Claim'" -- true, but it doesn't say what to
    do instead. Defining it lets the message name `claim.ratio` and repeat
    the reason for the refusal, in the same breath that raises.
    """
    assert hasattr(Claim, "__float__")
    assert not hasattr(Claim, "__index__")
    with pytest.raises(TypeError, match="claim.ratio"):
        float(a_claim())


def test_str_renders_every_condition():
    text = str(a_claim())
    for fragment in (
        "2.000x vs masked_row_scan",
        "drift[line(radius=3)]",
        "rho=0.05",
        "ceiling rho<=0.25",
        "unmeasured, not weak",
        "CPython x / numpy y",
        "reference=scratch_reference",
        "12",
        "reduce_median_then_geomean",
    ):
        assert fragment in text, fragment


def test_str_names_the_frozen_control_rather_than_printing_rho_zero():
    assert "frozen (no churn)" in str(a_claim(rho=0.0, motion="frozen"))


def test_as_dict_carries_the_conditions_with_the_ratio():
    d = a_claim().as_dict()
    assert d["ratio"] == 2.0
    assert set(d) == {
        "ratio",
        "baseline",
        "motion",
        "rho",
        "rho_ceiling",
        "toolchain",
        "control",
        "n_cells",
        "reduction",
    }


# --------------------------------------------------------------------------
# validation
# --------------------------------------------------------------------------


def test_a_rate_above_the_measured_ceiling_is_rejected():
    with pytest.raises(ValueError, match="exceeds the measured ceiling"):
        a_claim(rho=0.5, rho_ceiling=0.25)


def test_an_unnamed_baseline_is_rejected():
    with pytest.raises(ValueError, match="baseline must be named"):
        a_claim(baseline="")


def test_a_non_positive_ratio_is_rejected():
    with pytest.raises(ValueError, match="positive"):
        a_claim(ratio=0.0)


def test_an_unregistered_reduction_is_rejected():
    with pytest.raises(ValueError, match="unknown reduction"):
        a_claim(reduction="whatever_the_last_script_did")


def test_zero_cells_is_rejected():
    with pytest.raises(ValueError, match="n_cells"):
        a_claim(n_cells=0)


def test_with_ceiling_raises_it_and_refuses_to_lower_it_below_the_rate():
    claim = a_claim(rho=0.05, rho_ceiling=0.05)
    assert claim.with_ceiling(0.25).rho_ceiling == 0.25
    with pytest.raises(ValueError, match="below this claim"):
        claim.with_ceiling(0.01)


# --------------------------------------------------------------------------
# from_rows
# --------------------------------------------------------------------------


def test_from_rows_requires_the_caller_to_choose_a_reduction():
    with pytest.raises(TypeError):
        Claim.from_rows(rows(), baseline="masked_row_scan")  # type: ignore[call-arg]


def test_from_rows_rejects_an_unknown_reduction_and_says_there_is_no_default():
    with pytest.raises(ValueError, match="no default"):
        Claim.from_rows(rows(), baseline="masked_row_scan", reduction="geomean")


def test_the_two_reductions_give_different_numbers_on_the_same_rows():
    """Which is exactly why neither is the default."""
    unbalanced = rows(ratios=[1.0, 1.0, 1.0, 8.0])
    unbalanced[0]["operator"] = unbalanced[1]["operator"] = unbalanced[2]["operator"] = "A"
    unbalanced[3]["operator"] = "B"
    flat = Claim.from_rows(
        unbalanced, baseline="masked_row_scan", reduction="reduce_flat"
    )
    nested = Claim.from_rows(
        unbalanced,
        baseline="masked_row_scan",
        reduction="reduce_median_then_geomean",
    )
    assert flat.ratio != pytest.approx(nested.ratio)
    assert flat.reduction != nested.reduction


def test_from_rows_reads_the_conditions_off_the_rows():
    claim = Claim.from_rows(
        rows(), baseline="masked_row_scan", reduction="reduce_flat"
    )
    assert claim.motion == "drift[line(radius=3)]"
    assert claim.rho == 0.05
    assert claim.toolchain == toolchain()
    assert claim.control.startswith("reference=")
    assert claim.n_cells == 3


def test_from_rows_refuses_to_pool_two_motion_models():
    mixed = rows() + rows(motion="jump_plain")
    with pytest.raises(ValueError, match="disagree on 'motion'"):
        Claim.from_rows(mixed, baseline="masked_row_scan", reduction="reduce_flat")


def test_from_rows_refuses_to_pool_two_churn_rates():
    mixed = rows() + rows(rho=0.25)
    with pytest.raises(ValueError, match="span churn rates"):
        Claim.from_rows(mixed, baseline="masked_row_scan", reduction="reduce_flat")


def test_from_rows_refuses_to_pool_two_toolchains():
    mixed = rows() + rows()
    for r in mixed[3:]:
        r["toolchain"] = "some other machine"
    with pytest.raises(ValueError, match="disagree on 'toolchain'"):
        Claim.from_rows(mixed, baseline="masked_row_scan", reduction="reduce_flat")


def test_from_rows_checks_the_baseline_the_rows_were_actually_paired_against():
    with pytest.raises(ValueError, match="were paired against"):
        Claim.from_rows(rows(), baseline="full_matvec", reduction="reduce_flat")


def test_from_rows_rejects_an_empty_set_of_rows():
    with pytest.raises(ValueError, match="not a claim"):
        Claim.from_rows([], baseline="x", reduction="reduce_flat")


def test_from_rows_rejects_rows_that_did_not_come_from_pairing():
    unpaired = [{"operator": "A", "rho": 0.1, "ratio": 2.0}]
    with pytest.raises(ValueError, match="missing 'baseline'"):
        Claim.from_rows(unpaired, baseline="x", reduction="reduce_flat")


def test_n_cells_counts_operator_by_rate_pairs_not_rows():
    many = rows(ratios=[2.0] * 6)
    for i, r in enumerate(many):
        r["operator"] = "A" if i < 3 else "B"
    claim = Claim.from_rows(
        many, baseline="masked_row_scan", reduction="reduce_flat"
    )
    assert claim.n_cells == 2


def test_a_claim_is_immutable():
    claim = a_claim()
    with pytest.raises(Exception):
        claim.ratio = 99.0  # type: ignore[misc]


def test_geometric_reduction_is_used_not_arithmetic():
    claim = Claim.from_rows(
        rows(ratios=[1.0, 4.0]), baseline="masked_row_scan", reduction="reduce_flat"
    )
    assert claim.ratio == pytest.approx(2.0)
    assert not math.isclose(claim.ratio, 2.5)
