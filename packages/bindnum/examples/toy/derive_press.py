"""Derivations: committed data -> value. No expected values live in this file.

That absence is the design. If this module held the numbers RESULTS.md states,
the suite could only ever compare the document to a second transcription of
itself, and would pass while both drifted away from the CSV together
(VACUOUS_TESTS.md #5, assertion-against-a-transcription).

Every function here is pure and stdlib-only, so it runs anywhere the prose gets
edited -- which is the machine that needs to run it.
"""

from __future__ import annotations

import csv
import math
import os
import statistics

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS_CSV = os.path.join(HERE, "results.csv")

# The unit the reduction aggregates over. Named once, here, so the aggregation
# check and the reduction agree by construction rather than by memory.
UNIT = "part"


def read_rows(path: str = RESULTS_CSV) -> list[dict]:
    with open(path, encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise AssertionError(f"{path} is empty")
    return rows


def parts(rows: list[dict] | None = None) -> list[str]:
    rows = read_rows() if rows is None else rows
    return sorted({row[UNIT] for row in rows})


def run_ratios(part: str, rows: list[dict] | None = None) -> list[float]:
    """fold_ms / press_ms for every run of one part. >1 means press is ahead."""
    rows = read_rows() if rows is None else rows
    values = [
        float(row["fold_ms"]) / float(row["press_ms"]) for row in rows if row[UNIT] == part
    ]
    if not values:
        raise AssertionError(f"no rows for {UNIT}={part!r}")
    return values


def geomean(values: list[float]) -> float:
    return math.exp(sum(math.log(v) for v in values) / len(values))


# --------------------------------------------------------------------------
# the candidate reductions -- named, never implicit
#
# The declared rule is `median`. The other two are here so that
# assert_unique_reduction has something to discriminate against: a table that
# only one of these reproduces is a table that verifies its own methodology
# sentence, and a table that all three reproduce is a table that cannot.
# --------------------------------------------------------------------------

REDUCTIONS = {
    "median": statistics.median,
    "mean": statistics.fmean,
    "geomean": geomean,
}


def part_ratio(part: str, reduction: str = "median") -> float:
    """One published table cell."""
    return REDUCTIONS[reduction](run_ratios(part))


def headline_ratio(reduction: str = "median") -> float:
    """Median within a part, then geometric mean across parts."""
    return geomean([part_ratio(p, reduction) for p in parts()])


def near_unity_pair() -> tuple[float, float]:
    """(gasket, spindle) -- in that order, and the order is the assertion."""
    return part_ratio("gasket"), part_ratio("spindle")
