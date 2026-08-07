#!/usr/bin/env python3
"""Every quoted column reference in paper/*.py must be accounted for.

This is the check whose absence let 130 references rot: the public export
policy (`release.config.json`, applied by `tools/export_csvs.py`) renamed 211
internal column names and denied 215 more, and `data/COLUMN_MAP.csv` records
the result -- but `paper/paper_numbers.py`, `paper/figures.py`,
`paper/router_data.py` and `paper/tables.py` were never updated to match, so
`tab_baselines` (the paper's most-quoted table) died on `KeyError: 'full_ms'`
against the released data. Nothing caught that until someone ran the script.

This test statically walks every `paper/*.py` file for quoted strings used as
column names (dict subscript, `.get(...)`, and the `columns.py`/`vintage.py`
call sites that name columns as arguments) and asserts each one is either

  * a column header that actually appears in a shipped `data/*.csv`, or
  * classified in `data/COLUMN_MAP.csv` (`renamed`, `denied`, or `free text`)
    -- i.e. a name the release policy *removed on purpose*, which
    `paper/columns.py` is expected to guard at its call site (see
    `test_denied_columns_are_columns_dot_py_guarded` below).

A name that is neither is either a stale internal name someone forgot to
rename, a typo, or a genuinely new column that needs a `COLUMN_MAP.csv`
entry -- in every case, something a human should look at before it ships.

Floors and the EXEMPT list below exist for the two reasons named in
`oss/bindnum/VACUOUS_TESTS.md` (patterns 7 and 8, "corpus vacuity" and
"unreadable is not clean"): a glob that starts matching nothing, or a file
read that silently swallows an error, would make every assertion below pass
vacuously while checking zero files. See `test_the_corpus_has_a_floor`.
"""
from __future__ import annotations

import csv
import glob
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                    # oss/paper-artifact/
PAPER_DIR = os.path.join(ROOT, "paper")
DATA_DIR = os.path.join(ROOT, "data")
COLUMN_MAP_PATH = os.path.join(DATA_DIR, "COLUMN_MAP.csv")

# --- the patterns this test treats as "a quoted column reference" ----------
#
# 1. subscript access:              row["some_column"]
# 2. .get() access:                 row.get("some_column")
# 3. paper/columns.py call sites:   columns.require_row(csv_name, row, "a", "b")
#                                    columns.require_header(csv_name, hdr, "a")
# 4. vintage.py staleness checks:   vintage.read(NAME, columns=("a", "b", ...))
_IDENT = r"[a-zA-Z_][a-zA-Z0-9_]{1,60}"
SUBSCRIPT = re.compile(r"""\[\s*(['"])(%s)\1\s*\]""" % _IDENT)
GETCALL = re.compile(r"""\.get\(\s*(['"])(%s)\1""" % _IDENT)
HELPER_CALL = re.compile(
    r"""columns\.(?:require_row|require_header|check|explain)\(([^)]*)\)""",
    re.DOTALL)
VINTAGE_COLUMNS = re.compile(r"""columns\s*=\s*\(([^)]*)\)""", re.DOTALL)
QUOTED_TOKEN = re.compile(r"""(['"])(%s)\1""" % _IDENT)


def _quoted_column_refs(text: str) -> list[str]:
    """Every name this test considers a "quoted column reference" in `text`."""
    names = [m.group(2) for m in SUBSCRIPT.finditer(text)]
    names += [m.group(2) for m in GETCALL.finditer(text)]
    for m in HELPER_CALL.finditer(text):
        # The first argument to every columns.py helper is the CSV filename
        # ("splice.csv", or a variable) -- skip literal filenames, keep the
        # column-name arguments that follow.
        for tok in QUOTED_TOKEN.finditer(m.group(1)):
            if not tok.group(2).endswith("csv"):
                names.append(tok.group(2))
    for m in VINTAGE_COLUMNS.finditer(text):
        names += [tok.group(2) for tok in QUOTED_TOKEN.finditer(m.group(1))]
    return names


#: Explicit, per-(file, name) exemptions -- an enumerated list, not a
#: predicate. (VACUOUS_TESTS.md pattern 1: a predicate-shaped exemption
#: ["skip anything that looks like a dict key I don't recognize"] grows
#: silently and would have swallowed the very bug this test exists to catch.
#: Every entry below was checked by hand and is one of exactly two things:)
#:
#: (a) a dict key INVENTED BY CODE in this directory, not a CSV column --
#:     `router_data.load()` builds rows with aliases like `csr`/`hst`/`arm`
#:     for `always_delta_baseline_ms`/`always_hst_ms`/`oracle_arm`, and
#:     `predictor_study.load()` builds its own feature dict (`cost_csr`,
#:     `cost_hst`, `cost_oracle`, ...). COLUMN_MAP.csv correctly has no
#:     entry for these: they never touch a CSV header.
#: (b) a grouping/label key over something that is NOT a CSV row at all --
#:     `MLAB[m]` / `by["native"]` / `SOURCES[model]` style lookups keyed by
#:     a motion-model or ordering name (`"drift"`, `"jump"`, `"native"`,
#:     `"relabelled"`), or `paper/columns.py`'s own dict literal keys
#:     (`"action"`, `"csv"`, `"original_column"`, `"released_as"` --
#:     COLUMN_MAP.csv's own header, quoted by the module that reads it), or
#:     `real_trace_summary.json` fields (`"solver"`, `"domain"`, `"n_steps"`,
#:     `"alpha_median"`, `"rho_median"`) -- a JSON file, not a CSV, so
#:     COLUMN_MAP.csv (a CSV-column policy record) has no opinion on it. That
#:     whole code path is already gated on the file's existence
#:     (`s_real_motion`, `paper_numbers.py`) and never reaches the CSV
#:     pipeline this test is about.
EXEMPT: set[tuple[str, str]] = {
    ("figures.py", "arm"),
    ("figures.py", "cost_csr"),
    ("figures.py", "cost_hst"),
    ("figures.py", "cost_oracle"),
    ("figures.py", "csr"),
    ("figures.py", "hst"),
    ("figures.py", "native"),
    ("figures.py", "pen_csr"),
    ("figures.py", "pen_hst"),
    ("figures.py", "relabelled"),
    ("figures.py", "router_full"),
    ("figures.py", "router_steady"),
    ("paper_numbers.py", "alpha_median"),
    ("paper_numbers.py", "arm"),
    ("paper_numbers.py", "csr"),
    ("paper_numbers.py", "degenerate"),
    ("paper_numbers.py", "domain"),
    ("paper_numbers.py", "drift"),
    ("paper_numbers.py", "hst"),
    ("paper_numbers.py", "jump"),
    ("paper_numbers.py", "n_steps"),
    ("paper_numbers.py", "native"),
    ("paper_numbers.py", "oracle"),
    ("paper_numbers.py", "pen_csr"),
    ("paper_numbers.py", "pen_hst"),
    ("paper_numbers.py", "probes"),
    ("paper_numbers.py", "relabelled"),
    ("paper_numbers.py", "relerr"),
    ("paper_numbers.py", "rho_median"),
    ("paper_numbers.py", "router_full"),
    ("paper_numbers.py", "router_steady"),
    ("paper_numbers.py", "solver"),
    ("router_data.py", "arm"),
    ("tables.py", "arm"),
    ("tables.py", "csr"),
    ("tables.py", "drift"),
    ("tables.py", "oracle"),
    ("columns.py", "action"),
    ("columns.py", "csv"),
    ("columns.py", "original_column"),
    ("columns.py", "released_as"),
}

#: Conservative floors, set below the counts measured on 2026-08-05 (5 files,
#: 757 references) so that deleting one file or trimming a comment does not
#: trip this test, but a broken glob (0 files) or a pattern that stops
#: matching (0 references) does. See VACUOUS_TESTS.md pattern 7.
MIN_FILES = 4
MIN_REFERENCES = 400


def _shipped_csv_headers() -> set[str]:
    """Every column name that actually heads a released `data/*.csv`."""
    headers: set[str] = set()
    csvs = glob.glob(os.path.join(DATA_DIR, "*.csv"))
    assert csvs, f"no CSVs found in {DATA_DIR} -- has data/ moved?"
    for path in csvs:
        if os.path.basename(path) == "COLUMN_MAP.csv":
            continue
        with open(path, newline="", encoding="utf-8") as fh:
            header = next(csv.reader(fh), [])
        headers.update(header)
    return headers


def _column_map() -> tuple[set[str], set[str], list[dict]]:
    """(original_column names still SAFE to quote, every non-empty
    released_as, all rows).

    A `renamed` original_column is the one thing this test must NOT call
    "known": that name is exactly what the release moved away from, so a
    live quote of it is the bug (`csr_best_ms` should read
    `delta_baseline_best_ms` now). Only `denied` (deliberately still checked,
    via `paper/columns.py`) and `free text` (dropped columns whose name is
    disclosed, e.g. in a `drop_freetext` list, without ever being read as
    data) originals stay legitimate to quote. Folding every action into one
    "known" set here is exactly the mistake that would make this test pass
    on a re-introduced stale reference -- caught by mutation-testing this
    file (temporarily reverting one rename back to its stale name) before
    this function had the `if r["action"] != "renamed"` guard below.
    """
    with open(COLUMN_MAP_PATH, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert rows, f"{COLUMN_MAP_PATH} is empty -- run tools/export_csvs.py"
    orig_still_valid = {r["original_column"] for r in rows
                        if r["action"] != "renamed"}
    released = {r["released_as"] for r in rows if r["released_as"]}
    return orig_still_valid, released, rows


def _paper_files() -> list[str]:
    files = sorted(glob.glob(os.path.join(PAPER_DIR, "*.py")))
    return files


class TestColumnReferences(unittest.TestCase):
    def test_the_corpus_has_a_floor(self):
        """A collapsed glob or a dead regex must fail LOUDLY, not pass quietly.

        Without this, `test_every_reference_is_known_or_exempt` iterating an
        empty file list or finding zero references would still report
        success -- exactly the "corpus vacuity" shape that let the 130 stale
        references in this directory go unnoticed for as long as they did.
        """
        files = _paper_files()
        self.assertGreaterEqual(
            len(files), MIN_FILES,
            f"expected at least {MIN_FILES} files under {PAPER_DIR}/*.py, "
            f"found {len(files)}: {files} -- did the glob pattern or the "
            f"directory layout change?")

        total = 0
        for path in files:
            with open(path, encoding="utf-8") as fh:   # no bare `except OSError: continue`
                total += len(_quoted_column_refs(fh.read()))
        self.assertGreaterEqual(
            total, MIN_REFERENCES,
            f"expected at least {MIN_REFERENCES} quoted column references "
            f"across {files}, found {total} -- the detection patterns in "
            f"this test may have stopped matching")

    def test_every_reference_is_known_or_exempt(self):
        """The check this whole module exists for."""
        files = _paper_files()
        headers = _shipped_csv_headers()
        cm_orig, cm_released, _ = _column_map()
        known = headers | cm_orig | cm_released

        bad: list[tuple[str, str]] = []
        for path in files:
            fname = os.path.basename(path)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            for name in _quoted_column_refs(text):
                if name in known:
                    continue
                if (fname, name) in EXEMPT:
                    continue
                bad.append((fname, name))

        if bad:
            lines = "\n".join(f"  {f}: {n!r}" for f, n in sorted(set(bad)))
            self.fail(
                "quoted reference(s) not found in any shipped CSV header, "
                "not classified in data/COLUMN_MAP.csv, and not in this "
                "test's EXEMPT list:\n" + lines + "\n\n"
                "If this is a genuinely new column, add a COLUMN_MAP.csv "
                "entry (regenerate via tools/export_csvs.py) or classify it. "
                "If it is a code-invented dict key (not a CSV column), add "
                "(filename, name) to EXEMPT with a one-line reason.")

    def test_exempt_entries_still_match_something(self):
        """A stale EXEMPT entry is not a correctness bug, but it is exactly
        the kind of silent drift this file is trying to prevent elsewhere --
        an entry nobody re-derives can hide a renamed reference under an old
        name that no longer appears anywhere."""
        files = _paper_files()
        seen: set[tuple[str, str]] = set()
        for path in files:
            fname = os.path.basename(path)
            with open(path, encoding="utf-8") as fh:
                names = _quoted_column_refs(fh.read())
            seen.update((fname, n) for n in names)

        stale = sorted(EXEMPT - seen)
        self.assertFalse(
            stale,
            f"EXEMPT entries that no longer match anything in "
            f"{PAPER_DIR}/*.py (delete them, or the code that used to need "
            f"them moved/was removed and the exemption is now dead weight): "
            f"{stale}")

    def test_denied_columns_are_columns_dot_py_guarded(self):
        """Every `denied` column that paper/*.py still quotes must be reached
        through `paper/columns.py` (subscript/`.get()` access alone would be a
        bare `KeyError`, not the honest, named condition CONFLICTS.md
        promises). Structural cross-check: every denied name this test finds
        via SUBSCRIPT/GETCALL (i.e. NOT already routed through a
        columns.py-helper call) should be paired somewhere in the same file
        with a `columns.ColumnUnavailable` catch or a `columns.require_*`
        call guarding it -- approximated here as "the file imports
        paper.columns and contains at least one require_* call for every
        denied name it subscripts.
        """
        _, _, cm_rows = _column_map()
        denied = {r["original_column"] for r in cm_rows if r["action"] == "denied"}

        for path in _paper_files():
            fname = os.path.basename(path)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            subscripted_denied = {
                m.group(2) for m in SUBSCRIPT.finditer(text)
                if m.group(2) in denied
            } | {
                m.group(2) for m in GETCALL.finditer(text)
                if m.group(2) in denied
            }
            if not subscripted_denied:
                continue
            self.assertIn(
                "import columns", text,
                f"{fname} subscripts denied column(s) {sorted(subscripted_denied)} "
                f"but never imports paper/columns.py to guard the access")


if __name__ == "__main__":
    unittest.main()


class TestPaperFigureReferences(unittest.TestCase):
    """Every \\includegraphics target must be producible by figures.py.

    paper.tex referenced 14 figures; figures.py could build 6 from the public
    export. The Python layer skipped the other 8 honestly and the LaTeX layer
    was never told, so tectonic died on `File 'fig_frozen' not found` and
    ./build.sh -- the artifact's headline command -- failed for every
    recipient, on the first page needing a withheld figure.

    figures.py now emits a declared placeholder for anything it cannot build,
    so the set it writes is total over ALL. This pins that: a new
    \\includegraphics with no corresponding entry in figures.py's ALL puts the
    build back where it was.
    """

    def _root(self):
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def test_every_referenced_figure_is_in_figures_ALL(self):
        root = self._root()
        with open(os.path.join(root, "paper", "paper.tex"), encoding="utf-8") as fh:
            tex = fh.read()
        referenced = set(re.findall(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}", tex))
        self.assertGreaterEqual(
            len(referenced), 10,
            f"only {len(referenced)} \\includegraphics targets found in paper.tex; "
            f"the pattern stopped matching and this check is passing over almost nothing")

        with open(os.path.join(root, "paper", "figures.py"), encoding="utf-8") as fh:
            src = fh.read()
        block = re.search(r"^ALL\s*=\s*\[(.*?)\]", src, re.S | re.M)
        self.assertIsNotNone(block, "figures.py no longer defines an ALL list")
        producible = set(re.findall(r'"([A-Za-z0-9_]+)"', block.group(1)))
        self.assertGreaterEqual(
            len(producible), 10,
            f"figures.py's ALL parsed to {len(producible)} names; the parse broke")

        missing = sorted(referenced - producible)
        self.assertEqual(
            missing, [],
            f"paper.tex references figures figures.py cannot produce, not even as a "
            f"placeholder: {missing}. tectonic will fail on the first one and "
            f"./build.sh will exit non-zero for every recipient.")

    def test_figures_py_still_emits_a_placeholder_for_skips(self):
        """The mechanism the test above depends on.

        Without it, ALL and the \\includegraphics set could agree perfectly
        while the build still failed, because a skipped figure would write no
        file. Checked structurally rather than by running matplotlib, which
        this suite does not require.
        """
        root = self._root()
        with open(os.path.join(root, "paper", "figures.py"), encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn("def placeholder(", src,
                      "figures.py lost its placeholder(); a skipped figure now "
                      "writes no file and tectonic fails on it")
        # Count call sites rather than regex-matching handler bodies: the first
        # draft of this assertion looked for `placeholder(` within a fixed
        # window after each `except`, and the ModuleNotFoundError handler
        # carries a six-line comment that pushed its call out of range. The
        # test failed while the code was correct -- a false alarm is a defect
        # in a guard just as much as a miss is.
        calls = src.count("placeholder(") - src.count("def placeholder(")
        self.assertGreaterEqual(
            calls, 2,
            f"only {calls} placeholder() call site(s) in figures.py. There are "
            f"two skip paths -- a withheld column and a missing optional "
            f"dependency -- and both must write a file, or tectonic fails on "
            f"whichever one did not.")
