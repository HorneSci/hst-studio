"""The three ratchet rules, the reason format, and the floors.

Rule 3 -- an allowlisted document that is now clean must LEAVE the list -- is
the one usually missing from tools of this shape, and the one that keeps the
list honest. Its test is `test_a_fixed_document_must_leave_the_allowlist`.
"""

from __future__ import annotations

import re

import pytest

from claimlint import AllowEntry, Config, FileReport, check_floors, run_ratchet
from claimlint.scan import Claim

ELEMENTS = {"hardware": r"\bx86\b", "baseline": r"baseline"}


def config(allowlist=None, floors=None, **kwargs) -> Config:
    return Config(
        required=["hardware", "baseline"],
        elements=ELEMENTS,
        allowlist=allowlist or {},
        floors=floors or {},
        **kwargs,
    )


def report(path: str, missing: dict[str, int] | None = None, error: str = "") -> FileReport:
    claim = Claim(raw="4x", start=0, end=2, lineno=1, line="4x")
    gaps = {name: [claim] * count for name, count in (missing or {}).items()}
    return FileReport(path=path, claims=[claim] if not error else [], gaps=gaps, error=error)


def entry(missing, reason="GAP - real debt") -> AllowEntry:
    return AllowEntry(missing=set(missing), reason=reason)


# --------------------------------------------------------------------------
# rule 1: the debt cannot grow
# --------------------------------------------------------------------------


def test_a_new_incomplete_document_fails():
    """MUTATION: skip files absent from the allowlist instead of reporting
    them. -> the debt grows silently, which is the failure the ratchet exists
    to prevent."""
    result = run_ratchet([report("NEW.md", {"hardware": 1})], config())
    assert result.new_incomplete == {"NEW.md": {"hardware"}}
    assert not result.ok


def test_a_complete_document_is_not_reported():
    assert run_ratchet([report("OK.md")], config()).ok


# --------------------------------------------------------------------------
# rule 2: an exemption may not widen
# --------------------------------------------------------------------------


def test_an_allowlisted_document_may_not_lose_another_element():
    """MUTATION: compare `missing != entry.missing` instead of set difference.
    -> a document that FIXED one element and lost another reports as merely
    'different', and the loss is indistinguishable from the fix."""
    allow = {"OLD.md": entry({"hardware"})}
    result = run_ratchet([report("OLD.md", {"hardware": 1, "baseline": 1})], config(allow))
    assert result.widened == {"OLD.md": {"baseline"}}
    assert not result.ok


def test_an_allowlisted_document_at_exactly_its_entry_passes():
    allow = {"OLD.md": entry({"hardware"})}
    assert run_ratchet([report("OLD.md", {"hardware": 1})], config(allow)).ok


# --------------------------------------------------------------------------
# rule 3: a fixed document must leave the list
# --------------------------------------------------------------------------


def test_a_fixed_document_must_leave_the_allowlist():
    """MUTATION: delete the `fixed = entry.missing - report.missing` loop.
    -> the entry stays forever. This is the rule that matters: an allowlist
    nobody prunes becomes a permanent exemption, and a permanent exemption is
    how a retracted rule survives a full propagation pass -- the place it
    lives is never re-read, because a passing test says it need not be.
    """
    allow = {"FIXED.md": entry({"hardware"})}
    result = run_ratchet([report("FIXED.md")], config(allow))
    assert "FIXED.md" in result.stale
    assert "now states ['hardware']" in result.stale["FIXED.md"]
    assert not result.ok


def test_a_partially_fixed_document_must_narrow_its_entry():
    allow = {"HALF.md": entry({"hardware", "baseline"})}
    result = run_ratchet([report("HALF.md", {"hardware": 1})], config(allow))
    assert "baseline" in result.stale["HALF.md"]


def test_an_allowlisted_document_that_vanished_is_stale():
    """A renamed or deleted document leaves an entry that can never fail."""
    allow = {"GONE.md": entry({"hardware"})}
    result = run_ratchet([report("OTHER.md")], config(allow))
    assert "no longer in the corpus" in result.stale["GONE.md"]


def test_an_unreadable_document_is_not_evidence_of_a_fix():
    """MUTATION: drop the `if report.error: continue` in the rule-3 loop.
    -> a document that became unreadable looks 'fixed' and its exemption is
    pruned, so the next readable version fails rule 1 for no reason. Worse,
    the unreadability itself would go unremarked."""
    allow = {"BROKEN.md": entry({"hardware"})}
    result = run_ratchet([report("BROKEN.md", error="unreadable: OSError")], config(allow))
    assert "BROKEN.md" not in result.stale
    assert "BROKEN.md" in result.unreadable
    assert not result.ok


# --------------------------------------------------------------------------
# every entry declares which kind of exemption it is
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "reason,ok",
    [
        ("n/a — measures something with no hardware axis", True),
        ("n/a - ascii dash", True),
        ("GAP — real debt, not yet paid", True),
        ("GAP - ascii dash", True),
        ("not applicable", False),
        ("", False),
        ("n/a: wrong separator", False),
        ("gap - lowercase is not the marker", False),
    ],
)
def test_a_reason_must_declare_n_a_or_gap(reason, ok):
    """MUTATION: accept any non-empty reason.
    -> the two cases stop being distinguishable, and a list where everything
    reads 'n/a' is a list nobody will ever prune."""
    allow = {"X.md": entry({"hardware"}, reason)}
    result = run_ratchet([report("X.md", {"hardware": 1})], config(allow))
    assert ("X.md" not in result.bad_reasons) is ok


def test_reason_prefixes_are_configurable():
    allow = {"X.md": entry({"hardware"}, "WONTFIX - policy")}
    conf = config(allow)
    conf.reason_prefixes = ("WONTFIX",)
    assert run_ratchet([report("X.md", {"hardware": 1})], conf).ok


# --------------------------------------------------------------------------
# the floors -- without which all three rules pass vacuously
# --------------------------------------------------------------------------


def test_a_collapsed_corpus_fails_the_floor():
    """MUTATION: `if floor and observed < floor` -> `if False`.
    -> an empty corpus passes every rule above, having read nothing. One bad
    pathspec is all it takes."""
    failures = check_floors([], 0, {"files": 5})
    assert failures and "corpus builder has collapsed" in failures[0]


def test_a_ratio_regex_that_stopped_matching_fails_the_floor():
    reports = [FileReport(path="a.md"), FileReport(path="b.md")]
    failures = check_floors(reports, 2, {"files": 2, "claim_bearing_files": 1})
    assert any("ratio pattern" in f for f in failures)


def test_broken_element_regexes_fail_the_clean_floor():
    """If NOTHING is clean, the elements are broken, not the corpus."""
    failures = check_floors(
        [report("a.md", {"hardware": 1}), report("b.md", {"hardware": 1})],
        2,
        {"clean_files": 1},
    )
    assert any("element regex is broken" in f for f in failures)


def test_an_unset_floor_is_not_enforced():
    """MUTATION: `floors.get(key, 0)` -> `floors.get(key, 1)`.
    -> a project that has not set any floors starts failing on an empty
    corpus it never asked to be checked, which is how a linter earns a
    `# noqa` in its first week."""
    assert check_floors([], 0, {}) == []
    assert check_floors([], 0, {"files": 0, "claim_bearing_files": 0}) == []


def test_healthy_counts_clear_every_floor():
    reports = [report("a.md"), report("b.md", {"hardware": 1})]
    assert check_floors(reports, 2, {"files": 2, "claim_bearing_files": 2, "clean_files": 1}) == []


def test_the_element_regexes_in_the_fixture_still_match_something():
    """A floor on this module's own fixture: if ELEMENTS stopped matching,
    every 'missing' assertion above would pass for the wrong reason."""
    assert re.search(ELEMENTS["hardware"], "an x86 host")
    assert re.search(ELEMENTS["baseline"], "the baseline")
