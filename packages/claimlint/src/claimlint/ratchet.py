"""The ratchet. This is the product; the scanner is just how it gets its input.

Point a scanner at an inherited corpus and it produces a wall of red. Nobody
retrofits fifty documents in an afternoon, so the check fails for months, and a
check that fails for months teaches people to ignore the suite. That is worse
than not having it: the suite is now noise, and the next real failure hides in
it.

So the current gaps are recorded, each with a reason, and three rules are
enforced instead:

    1. no NEW incomplete file           -- the debt cannot grow
    2. no allowlisted file may LOSE an element it currently has
    3. an allowlisted file that is now CLEAN must LEAVE the list

Rule 3 is the one that matters, and the one usually missing. An allowlist
nobody prunes becomes a permanent exemption, and a permanent exemption is how a
retracted rule survives a full propagation pass: the place it lives is never
re-read, because a passing test says it does not need to be.

Every entry carries a reason, and the reason must start `n/a -` (the element
genuinely does not apply to what this document measured) or `GAP -` (real debt,
not yet paid). The distinction is enforced because a list where every line
reads "n/a" has stopped meaning anything, and nobody can tell from the outside
which of those it is.

Finally, a floor. If the corpus builder collapses or the ratio regex stops
matching, all three rules pass -- vacuously. `check_floors` is what makes a
green run mean documents were read.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .config import AllowEntry, Config
from .scan import FileReport

__all__ = [
    "RatchetResult",
    "run_ratchet",
    "check_floors",
    "allowlist_stanza",
    "STANZA_PLACEHOLDER",
    "is_placeholder_reason",
]

# The one string `--stanza` emits, defined once so the generator and the check
# that refuses it cannot drift apart. `python -m claimlint . --stanza >> config`
# followed by `--ratchet` was a two-command green build with every generated
# reason left verbatim -- the README says "Step 4 is the work, and it is
# deliberately not automated", and until this constant existed that sentence was
# documentation of an intention rather than a description of the behaviour.
STANZA_PLACEHOLDER = "TODO: say why, or fix the document"

# The generator emits exactly one placeholder, but a reason is hand-edited text
# and the same non-answer arrives spelled several ways. These are the tokens
# that mean "I have not written the reason yet"; a reason containing one has not
# had the work done on it, whatever prefix it carries.
_PLACEHOLDER_TOKENS = re.compile(r"\b(?:TODO|FIXME|TBD|XXX|WIP)\b", re.I)


def is_placeholder_reason(reason: str) -> bool:
    """Is this reason still the generator's placeholder, or a stand-in for one?"""
    if STANZA_PLACEHOLDER.lower() in reason.lower():
        return True
    return bool(_PLACEHOLDER_TOKENS.search(reason))


@dataclass
class RatchetResult:
    # rule 1: files with gaps that are not on the list at all
    new_incomplete: dict[str, set[str]] = field(default_factory=dict)
    # rule 2: allowlisted files missing MORE than their entry permits
    widened: dict[str, set[str]] = field(default_factory=dict)
    # rule 3: allowlisted files that no longer need (part of) their exemption
    stale: dict[str, str] = field(default_factory=dict)
    # every entry's reason must declare which kind of exemption it is
    bad_reasons: dict[str, str] = field(default_factory=dict)
    # reasons still carrying the generator's TODO -- pasted, never written
    placeholder_reasons: dict[str, str] = field(default_factory=dict)
    # documents that could not be read at all -- never silently dropped
    unreadable: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not (
            self.new_incomplete
            or self.widened
            or self.stale
            or self.bad_reasons
            or self.placeholder_reasons
            or self.unreadable
        )

    def messages(self) -> list[str]:
        out = []
        if self.new_incomplete:
            out.append(
                "documents quoting ratios without their conditions nearby:\n"
                + "\n".join(
                    f"  {path} - missing {sorted(missing)}"
                    for path, missing in sorted(self.new_incomplete.items())
                )
                + "\n  Add the missing condition near the number, or -- if it genuinely does "
                "not apply -- add an allowlist entry with a reason starting 'n/a -'."
            )
        if self.widened:
            out.append(
                "allowlisted documents have LOST a condition they used to state:\n"
                + "\n".join(
                    f"  {path} - newly missing {sorted(missing)}"
                    for path, missing in sorted(self.widened.items())
                )
            )
        if self.stale:
            out.append(
                "the allowlist is out of date:\n"
                + "\n".join(f"  {path} - {why}" for path, why in sorted(self.stale.items()))
                + "\n  An allowlist nobody prunes becomes a permanent exemption."
            )
        if self.bad_reasons:
            out.append(
                "allowlist entries whose reason does not declare its kind:\n"
                + "\n".join(f"  {path} - {why}" for path, why in sorted(self.bad_reasons.items()))
            )
        if self.placeholder_reasons:
            out.append(
                "allowlist entries still carrying the generated placeholder:\n"
                + "\n".join(
                    f"  {path} - {why}"
                    for path, why in sorted(self.placeholder_reasons.items())
                )
                + "\n  `--stanza` writes the shape of an exemption, not the exemption. "
                "Replace each placeholder with why this document does not state the "
                "element -- or fix the document and delete the entry."
            )
        if self.unreadable:
            out.append(
                "documents that could not be read (NOT the same as clean):\n"
                + "\n".join(f"  {path} - {why}" for path, why in sorted(self.unreadable.items()))
            )
        return out


def _reason_ok(reason: str, prefixes: tuple[str, ...]) -> bool:
    normal = reason.replace("—", "-").replace("–", "-").strip()
    return any(normal.startswith(f"{p} -") for p in prefixes)


def run_ratchet(reports: list[FileReport], config: Config) -> RatchetResult:
    """Apply the three rules to a set of scan reports."""
    result = RatchetResult()
    by_path = {report.path: report for report in reports}
    allowlist: dict[str, AllowEntry] = config.allowlist

    for report in reports:
        if report.error:
            result.unreadable[report.path] = report.error
            continue
        missing = report.missing
        if not missing:
            continue
        entry = allowlist.get(report.path)
        if entry is None:
            result.new_incomplete[report.path] = missing
            continue
        extra = missing - entry.missing
        if extra:
            result.widened[report.path] = extra

    for path, entry in allowlist.items():
        if is_placeholder_reason(entry.reason):
            result.placeholder_reasons[path] = (
                f"reason is still the generator's placeholder: {entry.reason!r}. "
                f"`--stanza` deliberately emits text that cannot pass; writing the "
                f"reason is the work."
            )
        if not _reason_ok(entry.reason, config.reason_prefixes):
            allowed = " or ".join(f"'{p} - '" for p in config.reason_prefixes)
            result.bad_reasons[path] = (
                f"reason must start {allowed}, got {entry.reason!r}. "
                f"'n/a' means the element does not apply; 'GAP' means real debt. "
                f"A list where every entry reads 'n/a' is a list nobody prunes."
            )
        report = by_path.get(path)
        if report is None:
            result.stale[path] = "document no longer in the corpus (renamed, deleted, or excluded)"
            continue
        if report.error:
            continue  # already reported as unreadable; not evidence of a fix
        fixed = entry.missing - report.missing
        if fixed:
            result.stale[path] = (
                f"now states {sorted(fixed)} near its ratios - narrow or remove the entry"
            )
    return result


def check_floors(reports: list[FileReport], corpus_size: int, floors: dict[str, int]) -> list[str]:
    """Fail when the scan has stopped looking, rather than passing vacuously.

    Three separate floors, because they collapse for different reasons:

        files                 the corpus builder returned less than it should
        claim_bearing_files   the ratio regex stopped matching
        clean_files           the element regexes stopped matching (if NOTHING
                              is clean, the patterns are broken, not the corpus)
    """
    failures = []
    readable = [r for r in reports if not r.error]
    with_claims = [r for r in readable if r.has_claims]
    clean = [r for r in with_claims if r.clean]

    checks = [
        ("files", corpus_size, "the corpus builder has collapsed; every rule below it "
                               "passes without reading anything"),
        ("claim_bearing_files", len(with_claims), "the ratio pattern has probably stopped "
                                                  "matching; the scan is looking at nothing"),
        ("clean_files", len(clean), "no document passes at all, which usually means an "
                                    "element regex is broken rather than that the corpus is bad"),
    ]
    for key, observed, why in checks:
        # An unset floor is not enforced. It is spelled as a default of 0
        # rather than as a separate `if floor` guard: a count can never be
        # negative, so `if floor and observed < floor` and `if observed <
        # floor` are the same function, and the mutation run showed that the
        # test for the extra clause could not tell them apart. A guard no
        # test can distinguish is a guard that should not be there.
        floor = floors.get(key, 0)
        if observed < floor:
            failures.append(f"{key}: {observed} < floor {floor} -- {why}")
    return failures


def allowlist_stanza(reports: list[FileReport]) -> str:
    """TOML for the documents currently incomplete, ready to paste and annotate.

    Adoption on an inherited corpus starts here: run it once, paste the output,
    then replace every placeholder with a real reason. The placeholders do not
    pass `run_ratchet` -- `is_placeholder_reason` rejects the exact string
    emitted here, and both sides read STANZA_PLACEHOLDER so they cannot drift.
    Writing the reason is the work.
    """
    lines = []
    for report in sorted(reports, key=lambda r: r.path):
        if not report.missing:
            continue
        if not lines:
            lines += [
                "# Generated by `claimlint --stanza`. THIS DOES NOT PASS `--ratchet`",
                f"# until every {STANZA_PLACEHOLDER.split(':')[0]} below is replaced "
                "with a real reason.",
                "",
            ]
        lines.append(f'[allowlist."{report.path}"]')
        lines.append(f"missing = {sorted(report.missing)!r}".replace("'", '"'))
        lines.append(f'reason = "GAP - {STANZA_PLACEHOLDER}"')
        lines.append("")
    return "\n".join(lines)
