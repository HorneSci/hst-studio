"""A document that already has numbers in it, and the values stated inside it.

Every literate-programming tool solves the *generative* direction: the prose is
a template, the number is produced at build time, and the two cannot disagree
because only one of them exists. That is a fine design for a document you are
about to write. It is useless for the document you already have.

`Doc` solves the *assertive* direction. The prose is unchanged. You point at a
value that is already written in it -- by section and by the label beside it --
and bind that site to a derivation. The document keeps being a document; the
test is what makes the two agree.

Locating by label, never by magnitude, is load-bearing. If a binding searched
for the string "1.02" it would still find it after the document swapped which
arm that number described. The site is (section, label); the number is what
happens to be sitting there.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from .compare import parse_number

__all__ = [
    "Doc",
    "Stated",
    "DocError",
    "ValueNotFound",
    "AmbiguousLabel",
    "SectionNotFound",
]

NUMBER = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?(?:[eE][-+]?\d+)?")
HEADING = re.compile(r"^(#{1,6})[ \t]+(.*?)[ \t]*#*$")


class DocError(Exception):
    """Base for every way a document can fail to yield a stated value."""


class ValueNotFound(DocError):
    """The label is not in the document, or carries no number."""


class AmbiguousLabel(DocError):
    """The label appears more than once and no occurrence was named.

    Ambiguity is an error rather than a silent first-match, because a label
    that matches two sites is a binding that will quietly follow the wrong one
    the first time somebody adds a paragraph.
    """


class SectionNotFound(DocError):
    """No heading matched, or more than one did."""


@dataclass(frozen=True)
class Stated:
    """One number as the document writes it, with where it was found."""

    raw: str
    number: float
    line: str
    lineno: int
    path: str
    label: str
    section: str | None = None

    def where(self) -> str:
        return f"{self.path}:{self.lineno}"

    def __str__(self) -> str:
        return f"{self.raw} @ {self.where()} [{self.label!r}]"


class Doc:
    """A Markdown/HTML/plain-text document, read once, searched by label.

    >>> doc = Doc("RESULTS.md")                       # doctest: +SKIP
    >>> doc.stated("median press ratio", section="Headline").number   # doctest: +SKIP
    1.42
    """

    def __init__(
        self,
        path: str | os.PathLike[str],
        *,
        encoding: str = "utf-8",
        normalize_dashes: bool = True,
    ) -> None:
        self.path = os.fspath(path)
        with open(self.path, encoding=encoding, errors="replace") as handle:
            text = handle.read()
        if normalize_dashes:
            # A document may write a range with an en dash and a test author
            # will type a hyphen. Normalizing here means neither side has to
            # remember which one the file uses.
            text = text.replace("–", "-").replace("—", "-").replace("−", "-")
        self.text = text
        self.lines = text.splitlines()

    # ---------------------------------------------------------------- sections

    def headings(self) -> list[tuple[int, int, str]]:
        """(lineno, level, title) for every Markdown heading, 1-based linenos."""
        found = []
        for i, line in enumerate(self.lines, start=1):
            hit = HEADING.match(line)
            if hit:
                found.append((i, len(hit.group(1)), hit.group(2).strip()))
        return found

    def section_span(self, section: str) -> tuple[int, int]:
        """1-based [start, end) line span of the body under a heading.

        `section` matches case-insensitively as a substring of the heading
        text. More than one match is an error for the same reason an ambiguous
        label is.
        """
        needle = section.lower()
        matches = [h for h in self.headings() if needle in h[2].lower()]
        if not matches:
            titles = ", ".join(repr(h[2]) for h in self.headings()[:12])
            raise SectionNotFound(
                f"{self.path}: no heading contains {section!r}. Headings seen: {titles}"
            )
        if len(matches) > 1:
            spots = ", ".join(f"{h[2]!r} (line {h[0]})" for h in matches)
            raise SectionNotFound(
                f"{self.path}: {section!r} matches {len(matches)} headings: {spots}. "
                f"Use a longer, unique fragment of the heading."
            )
        lineno, level, _title = matches[0]
        end = len(self.lines) + 1
        for other_line, other_level, _t in self.headings():
            if other_line > lineno and other_level <= level:
                end = other_line
                break
        return lineno + 1, end

    # ------------------------------------------------------------------ values

    def stated(
        self,
        label: str,
        *,
        section: str | None = None,
        occurrence: int | None = None,
        pattern: str | re.Pattern[str] | None = None,
        case_sensitive: bool = False,
        after_label: bool = True,
    ) -> Stated:
        """The number written beside `label`.

        `pattern` overrides number extraction; it must expose the value either
        as group 1 or as the whole match. `occurrence` (0-based) disambiguates
        a label that genuinely appears more than once.
        """
        start, end = (1, len(self.lines) + 1) if section is None else self.section_span(section)
        needle = label if case_sensitive else label.lower()

        hits: list[tuple[int, str, int]] = []
        for lineno in range(start, min(end, len(self.lines) + 1)):
            line = self.lines[lineno - 1]
            hay = line if case_sensitive else line.lower()
            at = hay.find(needle)
            if at >= 0:
                hits.append((lineno, line, at + len(label)))

        scope = f" in section {section!r}" if section else ""
        if not hits:
            raise ValueNotFound(f"{self.path}: no line contains {label!r}{scope}")
        if len(hits) > 1 and occurrence is None:
            spots = ", ".join(f"line {h[0]}" for h in hits)
            raise AmbiguousLabel(
                f"{self.path}: {label!r}{scope} appears {len(hits)} times ({spots}). "
                f"Pass occurrence=N (0-based) or narrow the label/section."
            )
        lineno, line, label_end = hits[occurrence or 0]

        tail = line[label_end:] if after_label else line
        raw = self._extract(tail, pattern)
        if raw is None and after_label:
            raw = self._extract(line, pattern)
        if raw is None:
            raise ValueNotFound(
                f"{self.path}:{lineno}: {label!r} found but no number beside it: {line.strip()!r}"
            )
        return Stated(
            raw=raw,
            number=parse_number(raw),
            line=line.strip(),
            lineno=lineno,
            path=self.path,
            label=label,
            section=section,
        )

    @staticmethod
    def _extract(text: str, pattern: str | re.Pattern[str] | None) -> str | None:
        rx = NUMBER if pattern is None else re.compile(pattern)
        found = rx.search(text)
        if not found:
            return None
        return found.group(1) if found.groups() else found.group(0)

    def contains(self, needle: str) -> bool:
        """Literal presence check, dash-normalized like the rest of the document."""
        return needle.replace("–", "-").replace("—", "-").replace("−", "-") in self.text
