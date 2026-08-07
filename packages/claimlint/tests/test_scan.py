"""The three scanner decisions, each pinned separately.

Every test here has been mutation-tested: the guard it protects was removed or
weakened, the test was observed to fail, and the guard was restored. The
mutation is named in the docstring so the next person can repeat it rather than
trust it.
"""

from __future__ import annotations

import re

import pytest

from claimlint import DEFAULT_RATIO, find_claims, scan_text, strip_markup

ELEMENTS = {
    "hardware": re.compile(r"\bx86\b|\bcores?\b", re.I),
    "baseline": re.compile(r"baseline|against\s+the", re.I),
}


def claims(text: str, kind: str = "md") -> list[str]:
    return [c.raw for c in find_claims(text, DEFAULT_RATIO, kind)]


# --------------------------------------------------------------------------
# decision 1: bare integers, and the two lookaheads
# --------------------------------------------------------------------------


def test_bare_integer_ratios_are_matched():
    """MUTATION: revert DEFAULT_RATIO to r'\\b\\d+\\.\\d+\\s*[x×]'.
    -> every assertion here fails. The roundest figures are the most quoted,
    so a decimal-only pattern misses exactly the claims that travel furthest.
    """
    assert claims("we measured 15x here") == ["15x"]
    assert claims("a 21x improvement") == ["21x"]
    assert claims("21× with the unicode sign") == ["21×"]
    assert claims("15x, then a comma") == ["15x"]


def test_decimal_ratios_are_still_matched():
    assert claims("1.46x and 7.25× and 12.8x") == ["1.46x", "7.25×", "12.8x"]


def test_hex_literals_and_dimensions_are_not_ratios():
    """MUTATION: drop the `(?!\\w)` lookahead.
    -> '0x3fffffff' reports as '0x', '1920x1080' as '1920x', '2x2' as '2x'.
    Three false positives on one line of ordinary prose, and a linter that
    cries wolf on hex constants is a linter somebody turns off this afternoon.
    """
    text = "mask 0x3fffffff, frame 1920x1080, a 2x2 block, and 0xdeadbeef"
    assert claims(text) == []


def test_dimension_notation_with_a_space_is_not_a_ratio():
    """MUTATION: drop the `(?!\\s*\\d)` lookahead.
    -> '60,000 × 60,000' reports as '000 ×' and '3 × 60 s' as '3 ×'.
    """
    assert claims("a 60,000 × 60,000 grid sampled in 3 × 60 s windows") == []


def test_the_lookaheads_do_not_eat_a_real_ratio_followed_by_punctuation():
    """The boundary case that makes the second lookahead safe: '15×,' is a
    ratio because the next character is a comma, not a digit."""
    assert claims("15×, 3.2x. 7x!") == ["15×", "3.2x", "7x"]


# --------------------------------------------------------------------------
# decision 2: window, not file
# --------------------------------------------------------------------------


def test_an_element_far_from_the_claim_does_not_count():
    """MUTATION: search the whole document instead of the window.
    -> this passes, and with it the real case it stands for: a repudiated
    benchmark block cleared because a machine name 130 lines above described
    a customer's own deployment.
    """
    text = "Runs on an x86 server in production.\n" + ("filler. " * 400) + "\nWe saw 7.4x."
    report = scan_text(
        text, required=["hardware"], elements=ELEMENTS, window=200
    )
    assert report.missing == {"hardware"}

    wide = scan_text(text, required=["hardware"], elements=ELEMENTS, window=100_000)
    assert wide.missing == set(), "the same document passes file-wide -- that is the bug"


def test_an_element_near_the_claim_counts():
    text = "On a 16-core host we measured 7.4x against the old build."
    report = scan_text(
        text, required=["hardware", "baseline"], elements=ELEMENTS, window=1200
    )
    assert report.missing == set()


def test_a_document_with_no_ratios_is_not_reported():
    """MUTATION: broaden DEFAULT_RATIO's `[x×]` to `[x×]?`.
    -> "5 trials" and "8 cores" become claims, and every prose document in
    the corpus starts reporting missing everything. The first draft of this
    test used a document with no digits at all, and the mutation run showed
    it green -- a pattern that matches bare numbers is invisible to a
    document that has none.
    """
    plain = scan_text(
        "prose with no figures at all", required=["hardware"], elements=ELEMENTS, window=1200
    )
    assert not plain.has_claims

    numbers_but_no_ratios = scan_text(
        "We ran 5 trials on 8 cores over 60 seconds, version 2.1 of the harness.",
        required=["hardware"],
        elements=ELEMENTS,
        window=1200,
    )
    assert numbers_but_no_ratios.claims == [], (
        f"bare numbers are being read as ratios: "
        f"{[c.raw for c in numbers_but_no_ratios.claims]}"
    )
    assert numbers_but_no_ratios.missing == set()


# --------------------------------------------------------------------------
# decision 3: strip code spans, link targets and fenced blocks
# --------------------------------------------------------------------------


def test_a_filename_does_not_satisfy_a_prose_requirement():
    """MUTATION: stop stripping link targets and code spans.
    -> both assertions flip. A data file called `discovery_gcc.csv` satisfied
    a toolchain requirement in a document that had stopped naming a compiler
    in prose. What a document says and what its files are named are different
    claims; only the first is being linted.
    """
    elements = {"toolchain": re.compile(r"gcc|clang", re.I)}
    text = "Result 3.1x. See [the log](out/discovery_gcc.csv) and `run_clang.sh`."
    report = scan_text(text, required=["toolchain"], elements=elements, window=1200)
    assert report.missing == {"toolchain"}

    spelled_out = "Result 3.1x, built with gcc 13."
    assert scan_text(
        spelled_out, required=["toolchain"], elements=elements, window=1200
    ).missing == set()


def test_ratios_inside_fenced_blocks_are_not_claims():
    """MUTATION: stop stripping fences.
    -> sample output pasted into a code block starts producing claims, and
    every one of them reports missing everything.
    """
    text = "Prose.\n\n```\nspeedup: 12.5x\nspeedup: 3x\n```\n\nMore prose."
    assert claims(text) == []


def test_offsets_survive_stripping_so_line_numbers_are_real():
    """MUTATION: make strip_markup return '' for a stripped span instead of
    equal-length spaces. -> the reported line numbers drift, silently, and a
    report nobody can act on is a report nobody reads.
    """
    text = "`code span here`\n\nline two\n\nThe ratio is 4.2x on 8 cores.\n"
    found = find_claims(text)
    assert len(found) == 1
    assert found[0].lineno == 5
    assert "4.2x" in found[0].line


def test_html_script_style_and_tags_are_stripped():
    html = (
        "<style>.a{width:3x}</style><script>var k=2.5;</script>"
        "<p>We measured 9x on 8 cores.</p>"
    )
    assert claims(html, "html") == ["9x"]


def test_latex_verbatim_and_texttt_are_stripped():
    tex = (
        "\\begin{verbatim}\nspeedup 99x\n\\end{verbatim}\n"
        "% a comment saying 88x\n"
        "The result is \\texttt{7x.log} and the speedup is 4.5x.\n"
    )
    assert claims(tex, "tex") == ["4.5x"]


# --------------------------------------------------------------------------
# unreadable is not clean
# --------------------------------------------------------------------------


def test_an_unreadable_document_is_reported_not_skipped(tmp_path):
    """MUTATION: `except OSError: continue`.
    -> the document vanishes from every assertion below and the run goes
    green having read less than it thinks (VACUOUS_TESTS.md #8).
    """
    from claimlint import scan_file

    report = scan_file(
        str(tmp_path / "does_not_exist.md"),
        required=["hardware"],
        elements=ELEMENTS,
        window=1200,
    )
    assert report.error
    assert not report.clean, "an unreadable document must never count as clean"


def test_a_required_element_with_no_regex_is_an_error_not_a_pass():
    report = scan_text(
        "we saw 4x", required=["nonexistent"], elements=ELEMENTS, window=1200
    )
    assert "no regex configured" in report.error


@pytest.mark.parametrize("kind", ["md", "html", "tex"])
def test_stripping_preserves_length_in_every_dialect(kind):
    text = "```\n1x\n```\n<b>2x</b>\n\\texttt{3x}\n% 4x\n[a](b.csv)\n`c`\n"
    assert len(strip_markup(text, kind)) == len(text)


def test_a_ratio_in_a_code_span_is_a_claim():
    """MUTATION: put _CODE_SPAN back in the ratio strip.
    -> `17.6x` written in a headline sentence stops being a claim, which is
    how it behaved until 2026-08-05.

    Stripping existed so that a link to `results_2.5x.md` does not invent a
    ratio -- an address is not prose. A code span is not an address. It is a
    number the reader sees, in the sentence they read it in, and a tool whose
    job is finding claims without conditions cannot be blind to the most
    emphatic way of writing one.
    """
    text = "The headline is `17.6x` faster, measured on nothing in particular."
    found = claims(text)
    assert found == ["17.6x"], f"expected the code-span ratio to be a claim, got {found}"


def test_fenced_ratios_stay_out_by_default_and_can_be_opted_in():
    """The other half of the same finding, deliberately left as configuration.

    Pasted harness output is the most common way a performance number enters a
    README, so a fence CAN hold a real claim. It is also the most common way
    to hold fifty numbers that state no conditions, which is why
    test_ratios_inside_fenced_blocks_are_not_claims pins the default. Measured
    on a 220-document corpus the difference is 41 ratios -- small there,
    unknowable elsewhere -- so the default stands and the switch exists.
    """
    text = "Prose.\n\n```\nspeedup: 12.5x\n```\n\nMore prose."
    assert find_claims(text) == []
    opted_in = find_claims(text, scan_fences=True)
    assert len(opted_in) == 1, (
        f"scan_fences=True must surface the fenced ratio, got {opted_in}"
    )
    assert opted_in[0].lineno == 4, (
        f"line number drifted to {opted_in[0].lineno}; offsets must survive "
        f"the ratio strip or the report points at the wrong line"
    )
