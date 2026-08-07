"""The return-code map.

The shim this replaces rendered every negative code as one string. -3 and -4 are
commercially different events (budget spent vs. a right never granted) and a
caller has to be able to branch on them without parsing prose.
"""

from __future__ import annotations

import pytest

import hstcore
from hstcore._context import _CODES, _raise_for


def test_zero_is_success():
    _raise_for(0, "hst_apply_delta")  # must not raise


@pytest.mark.parametrize(
    "rc,cls",
    [
        (-1, hstcore.HSTArgumentError),
        (-2, hstcore.HSTInternalError),
        (-3, hstcore.HSTQuotaError),
        (-4, hstcore.HSTShadowNotGrantedError),
    ],
)
def test_each_code_maps_to_its_own_class(rc, cls):
    with pytest.raises(cls):
        _raise_for(rc, "hst_apply_shadow")


def test_the_four_classes_are_distinct():
    classes = [cls for cls, _ in _CODES.values()]
    assert len(set(classes)) == 4


def test_no_class_catches_another():
    # A caller writing `except HSTQuotaError` must not also swallow a bad-args
    # bug, and vice versa.
    classes = [cls for cls, _ in _CODES.values()]
    for a in classes:
        for b in classes:
            if a is not b:
                assert not issubclass(a, b)


def test_unknown_code_still_raises_and_says_so():
    with pytest.raises(hstcore.HSTError) as exc:
        _raise_for(-99, "hst_apply_delta")
    assert "-99" in str(exc.value)
    assert "undocumented" in str(exc.value)


def test_quota_message_names_which_budget():
    with pytest.raises(hstcore.HSTQuotaError) as prod:
        _raise_for(-3, "hst_apply_delta")
    with pytest.raises(hstcore.HSTQuotaError) as shadow:
        _raise_for(-3, "hst_apply_shadow")
    assert "production" in str(prod.value)
    assert "shadow" in str(shadow.value)
    assert str(prod.value) != str(shadow.value)


def test_message_carries_the_code_and_the_entry_point():
    with pytest.raises(hstcore.HSTInternalError) as exc:
        _raise_for(-2, "hst_recompute_full")
    assert "hst_recompute_full" in str(exc.value)
    assert "-2" in str(exc.value)


def test_shadow_grant_error_says_the_token_must_be_reissued():
    with pytest.raises(hstcore.HSTShadowNotGrantedError) as exc:
        _raise_for(-4, "hst_apply_shadow")
    msg = str(exc.value)
    assert "token" in msg
    # No flag, argument or environment variable can grant shadow rights, and the
    # message must not imply otherwise.
    assert "reissued" in msg


def test_everything_derives_from_the_base():
    for name in dir(hstcore):
        obj = getattr(hstcore, name)
        if isinstance(obj, type) and name.startswith("HST") and issubclass(obj, Exception):
            assert issubclass(obj, hstcore.HSTError)


def test_argument_error_is_a_value_error_and_buffer_error_a_type_error():
    assert issubclass(hstcore.HSTArgumentError, ValueError)
    assert issubclass(hstcore.HSTBufferError, TypeError)
