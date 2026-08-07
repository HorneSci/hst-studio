"""Finding ratio-shaped claims, and asking what is missing near each one.

Three decisions here are not stylistic. Each of them is the difference between
a scan that catches something and a scan that reports zero because it never
looked.

**1. The ratio pattern must match bare integers.**
A decimal-only pattern -- `\\d+\\.\\d+\\s*[x×]` -- is the obvious first draft
and it is wrong. It never sees `15x` or `21x`. In practice the roundest figures
are the most quoted ones, so a decimal-only scan misses exactly the claims that
travel furthest, and reports a clean corpus while doing it.

Matching bare integers needs two negative lookaheads, both shipped as tested
behaviour rather than left for users to rediscover:

    (?!\\w)     kills hex literals and no-space dimensions: `0x3fffffff`,
                `1920x1080`, `2x2`
    (?!\\s*\\d)  kills dimension notation with a space: `60,000 × 60,000`,
                `3 × 60 s`

**2. Window, not file.**
An element must appear *near* the claim. File-wide matching passes a repudiated
block because a machine name appears 130 lines away describing something else
entirely -- a customer's own deployment, a related-work paragraph, a footnote.
The window is a character count around the match, so a document that states its
method once in a dedicated section still covers the numbers a few paragraphs
away, and a document that mentions the word somewhere unrelated does not.

**3. Strip code spans, link targets and fenced blocks before matching.**
A filename satisfies a prose requirement it was never meant to. A document that
had stopped naming its compiler anywhere in prose still passed a toolchain
check, because a data file in a link target happened to be called
`discovery_gcc.csv`. What a document *says* and what its files are *named* are
different claims. Only the first one is being linted.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

__all__ = [
    "DEFAULT_RATIO",
    "Claim",
    "FileReport",
    "strip_markup",
    "find_claims",
    "scan_text",
    "scan_file",
]

# See decision 1 above. Every piece of this is load-bearing; the tests in
# tests/test_scan.py pin each lookahead separately.
DEFAULT_RATIO = r"\b\d+(?:\.\d+)?\s*[x×](?!\w)(?!\s*\d)"

# Markdown
_FENCE = re.compile(r"```.*?```|~~~.*?~~~", re.S)
_CODE_SPAN = re.compile(r"`[^`\n]*`")
_LINK_TARGET = re.compile(r"\]\([^)\n]*\)")
_REF_DEF = re.compile(r"^\s*\[[^\]]+\]:\s*\S+.*$", re.M)
_IMAGE = re.compile(r"!\[[^\]]*\]")
_HTML_ATTR_URL = re.compile(r"""\b(?:href|src|data-\w+)\s*=\s*(?:"[^"]*"|'[^']*')""", re.I)

# HTML
_HTML_DROP = re.compile(r"<(script|style)\b.*?</\1>", re.S | re.I)
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
_HTML_PRE = re.compile(r"<(pre|code)\b.*?</\1>", re.S | re.I)
_HTML_TAG = re.compile(r"<[^>]+>")

# LaTeX
_TEX_COMMENT = re.compile(r"(?<!\\)%.*$", re.M)
_TEX_VERBATIM = re.compile(r"\\begin\{(verbatim|lstlisting|minted)\}.*?\\end\{\1\}", re.S)
_TEX_VERB = re.compile(r"\\verb(.)(.*?)\1")
_TEX_TT = re.compile(r"\\(?:texttt|url|path|lstinline)\{[^{}]*\}")
_TEX_HREF = re.compile(r"\\href\{[^{}]*\}")
_TEX_LABELS = re.compile(r"\\(?:label|ref|cite[a-z]*|input|include)\{[^{}]*\}")

_KIND_BY_EXT = {
    ".md": "md",
    ".markdown": "md",
    ".mdx": "md",
    ".html": "html",
    ".htm": "html",
    ".tex": "tex",
    ".rst": "md",
    ".txt": "md",
}


def kind_of(path: str) -> str:
    return _KIND_BY_EXT.get(os.path.splitext(path)[1].lower(), "md")


def strip_markup(text: str, kind: str = "md") -> str:
    """Replace non-prose spans with spaces, preserving every offset.

    Offsets are preserved deliberately: the windows computed downstream are
    character offsets into the ORIGINAL document, so a report can point at a
    real line number.
    """

    def blank(match: re.Match[str]) -> str:
        return " " * (match.end() - match.start())

    if kind == "html":
        for pattern in (_HTML_DROP, _HTML_COMMENT, _HTML_PRE, _HTML_ATTR_URL, _HTML_TAG):
            text = pattern.sub(blank, text)
        return text

    if kind == "tex":
        for pattern in (
            _TEX_VERBATIM,
            _TEX_COMMENT,
            _TEX_VERB,
            _TEX_TT,
            _TEX_HREF,
            _TEX_LABELS,
        ):
            text = pattern.sub(blank, text)
        return text

    # markdown / plain text
    for pattern in (_FENCE, _REF_DEF, _IMAGE, _LINK_TARGET, _CODE_SPAN, _HTML_COMMENT,
                    _HTML_DROP, _HTML_ATTR_URL):
        text = pattern.sub(blank, text)
    return text


@dataclass(frozen=True)
class Claim:
    """One ratio-shaped figure, and where it sits in the document."""

    raw: str
    start: int
    end: int
    lineno: int
    line: str

    def __str__(self) -> str:  # pragma: no cover - convenience
        return f"{self.raw!r} (line {self.lineno})"


@dataclass
class FileReport:
    path: str
    claims: list[Claim] = field(default_factory=list)
    # element -> the claims that had no evidence of it within the window
    gaps: dict[str, list[Claim]] = field(default_factory=dict)
    error: str = ""

    @property
    def missing(self) -> set[str]:
        return set(self.gaps)

    @property
    def has_claims(self) -> bool:
        return bool(self.claims)

    @property
    def clean(self) -> bool:
        return not self.gaps and not self.error


def _linenos(text: str) -> list[int]:
    """Prefix offsets of each line start, for offset -> lineno lookup."""
    starts = [0]
    for i, ch in enumerate(text):
        if ch == "\n":
            starts.append(i + 1)
    return starts


def _lineno_of(starts: list[int], offset: int) -> int:
    low, high = 0, len(starts) - 1
    while low < high:
        mid = (low + high + 1) // 2
        if starts[mid] <= offset:
            low = mid
        else:
            high = mid - 1
    return low + 1


#: Spans that can produce a FALSE ratio because they are addresses rather than
#: prose -- a link to `results_2.5x.md`, an image path, a reference definition,
#: a URL in an HTML attribute. These are blanked before looking for ratios.
#:
#: Fences and code spans are deliberately NOT in this list, though they ARE
#: stripped before looking for the surrounding conditions. Until 2026-08-05
#: both used the same strip, so a document whose only performance number was
#: pasted harness output --
#:
#:     ```
#:     speedup 17.6x
#:     ```
#:
#: -- reported "0 quoting ratios" and exited 0. So did `17.6x` written as a
#: code span in a headline sentence. Pasted output in a fence is the single
#: most common way a performance number enters a README, and stripping was
#: suppressing the CLAIM rather than only the evidence.
#:
#: The asymmetry is the point: a compiler name inside a fence is still not the
#: document stating its toolchain in prose, so element detection keeps the
#: stricter strip. A ratio inside a fence is still a ratio the reader sees.
_RATIO_NOISE_MD = (_REF_DEF, _IMAGE, _LINK_TARGET, _HTML_COMMENT, _HTML_ATTR_URL)


def strip_for_ratios(text: str, kind: str = "md", scan_fences: bool = False) -> str:
    """Blank only what would create a false ratio, keeping code the reader sees.

    Code SPANS are always kept. `17.6x` written in a headline sentence is a
    claim by any reading, and treating it as markup was simply wrong.

    FENCES are stripped unless `scan_fences` is set, which preserves the
    behaviour test_ratios_inside_fenced_blocks_are_not_claims was written to
    pin. Its reasoning is sound in general -- raw pasted output states no
    conditions, so every line of it flags -- even though on the corpus this
    was measured against the cost is small (41 additional ratios across 220
    documents). Whether that is signal or noise depends on the repository, so
    it is configuration rather than a decision made here for everyone.
    """
    def blank(match: re.Match[str]) -> str:
        return " " * (match.end() - match.start())

    if kind != "md":
        # html and tex keep the conservative strip: their code constructs are
        # markup-heavy and produce noise rather than readable claims.
        return strip_markup(text, kind)
    patterns = _RATIO_NOISE_MD if scan_fences else (_FENCE,) + _RATIO_NOISE_MD
    for pattern in patterns:
        text = pattern.sub(blank, text)
    return text


def find_claims(text: str, ratio: re.Pattern[str] | str = DEFAULT_RATIO, kind: str = "md",
                scan_fences: bool = False) -> list[Claim]:
    """Every ratio-shaped claim in the prose of `text`."""
    pattern = ratio if isinstance(ratio, re.Pattern) else re.compile(ratio)
    prose = strip_for_ratios(text, kind, scan_fences)
    starts = _linenos(text)
    lines = text.splitlines()
    found = []
    for match in pattern.finditer(prose):
        lineno = _lineno_of(starts, match.start())
        found.append(
            Claim(
                raw=match.group(0),
                start=match.start(),
                end=match.end(),
                lineno=lineno,
                line=lines[lineno - 1].strip() if lineno <= len(lines) else "",
            )
        )
    return found


def scan_text(
    text: str,
    *,
    path: str = "<text>",
    required: list[str],
    elements: dict[str, re.Pattern[str]],
    window: int,
    ratio: re.Pattern[str] | str = DEFAULT_RATIO,
    kind: str = "md",
) -> FileReport:
    """Report which required elements are absent within `window` of each claim."""
    prose = strip_markup(text, kind)
    claims = find_claims(text, ratio, kind)
    report = FileReport(path=path, claims=claims)
    if not claims:
        return report
    for claim in claims:
        low = max(0, claim.start - window)
        high = min(len(prose), claim.end + window)
        context = prose[low:high]
        for name in required:
            pattern = elements.get(name)
            if pattern is None:
                report.error = f"required element {name!r} has no regex configured"
                continue
            if not pattern.search(context):
                report.gaps.setdefault(name, []).append(claim)
    return report


def scan_file(
    path: str,
    *,
    required: list[str],
    elements: dict[str, re.Pattern[str]],
    window: int,
    ratio: re.Pattern[str] | str = DEFAULT_RATIO,
    root: str = "",
) -> FileReport:
    """Scan one file. An unreadable file is reported, never skipped.

    Silently skipping on OSError is `unreadable-is-not-clean`
    (VACUOUS_TESTS.md #8): the document disappears from every assertion below,
    and the run goes green having read less than it thinks.
    """
    full = os.path.join(root, path) if root else path
    try:
        with open(full, encoding="utf-8") as handle:
            text = handle.read()
    except (OSError, UnicodeDecodeError) as exc:
        return FileReport(path=path, error=f"unreadable: {exc.__class__.__name__}: {exc}")
    return scan_text(
        text,
        path=path,
        required=required,
        elements=elements,
        window=window,
        ratio=ratio,
        kind=kind_of(path),
    )
