"""Fail honestly when a script asks for a column this release withholds.

`release.config.json` drops some columns from every released CSV on purpose
(`dens`, `tiles`, `router_probes`, ...) -- see `CONFLICTS.md`. The scripts in
this directory were written against the *internal* CSVs, which still carry
those columns, and were never updated when the export policy dropped them.
Left alone, a call reading one of those columns off a released row raises a
bare `KeyError`, which reads to a reader running this artifact as a bug in
the script rather than as a disclosed limitation of the release.

`data/COLUMN_MAP.csv` (written by `tools/export_csvs.py`) already records,
for every column of every released CSV, whether it was kept, `renamed`,
`denied`, or dropped as `free text`. This module is the one place that reads
that map so a caller gets a clear, named condition instead of a stack trace:

    columns.require_row(name, row, "dens", "tiles")
    columns.require_header(name, header, "router_probes")

Both raise `ColumnUnavailable` naming the column, the CSV, and -- if the map
knows why -- whether it was withheld on purpose (`denied`), renamed to
something else (so the caller can be told what to type instead of guessing),
or is simply not a column this release ever shipped or dropped from that CSV
(`unknown`, most likely a typo or a check running against the wrong file).

The convention throughout `paper/*.py`: a figure/table/number that needs a
withheld column catches `ColumnUnavailable` at the smallest block that needs
it, prints `skipped: <what> -- <reason>`, and moves on. Nothing here
reconstructs a withheld value or fabricates a substitute -- the point is an
honest, non-crashing gap, not a workaround.
"""
from __future__ import annotations

import csv
import os

HERE = os.path.dirname(os.path.abspath(__file__))          # paper/
ROOT = os.path.dirname(HERE)                                 # paper-artifact/
COLUMN_MAP_PATH = os.path.join(ROOT, "data", "COLUMN_MAP.csv")


class ColumnUnavailable(RuntimeError):
    """A script asked for a column this release's export does not carry.

    Distinct from a bare `KeyError`: this names the CSV, the column, and (via
    `data/COLUMN_MAP.csv`) whether it was withheld on purpose, renamed, or is
    simply not a recognized column of that file.
    """


_MAP: dict[str, dict[str, dict[str, str]]] | None = None


def _load_map() -> dict[str, dict[str, dict[str, str]]]:
    m: dict[str, dict[str, dict[str, str]]] = {}
    with open(COLUMN_MAP_PATH, newline="") as fh:
        for row in csv.DictReader(fh):
            m.setdefault(row["csv"], {})[row["original_column"]] = row
    return m


def _map() -> dict[str, dict[str, dict[str, str]]]:
    global _MAP
    if _MAP is None:
        _MAP = _load_map()
    return _MAP


def explain(csv_name: str, column: str) -> str:
    """A human-readable reason `column` is not available in `csv_name`."""
    entry = _map().get(csv_name, {}).get(column)
    where = "data/COLUMN_MAP.csv"
    if entry is None:
        return (f"{column!r} is not a recognized original column of "
                f"{csv_name!r} in this release ({where} has no entry for it "
                f"under that CSV) -- check the name and the CSV")
    action = entry["action"]
    if action == "denied":
        return (f"{column!r} is withheld from {csv_name!r} by this "
                f"release's export policy (release.config.json, applied by "
                f"tools/export_csvs.py) -- see {where} and CONFLICTS.md")
    if action == "renamed":
        return (f"{column!r} was renamed to {entry['released_as']!r} in the "
                f"released {csv_name!r} -- read that column instead")
    if action == "free text":
        return (f"{column!r} was dropped from {csv_name!r} as free text "
                f"(prose, not a value) by this release's export policy")
    return f"{column!r} in {csv_name!r}: unrecognized COLUMN_MAP action {action!r}"


def check(csv_name: str, present, *wanted: str) -> None:
    """Raise `ColumnUnavailable` if any of `wanted` is missing from `present`.

    `present` is whatever the caller already has on hand that lists the
    available column names -- a CSV header, or one row's `.keys()` (a
    `csv.DictReader` row only carries the columns that survived the export,
    so `"dens" not in row` is exactly the released-column test). Reports
    every missing name at once, not just the first, since the point is to
    tell a reader everything that block cannot do.
    """
    present = set(present)
    missing = [w for w in wanted if w not in present]
    if missing:
        reasons = "; ".join(f"{m}: {explain(csv_name, m)}" for m in missing)
        raise ColumnUnavailable(reasons)


def require_header(csv_name: str, header, *wanted: str) -> None:
    """`check`, where `header` is a CSV header (list of column names)."""
    check(csv_name, header, *wanted)


def require_row(csv_name: str, row, *wanted: str) -> None:
    """`check`, where `row` is one `csv.DictReader` row (or `{}` if there are
    no rows -- absence of any data is not itself a column-availability
    question, so an empty row just means every `wanted` name is "missing")."""
    check(csv_name, row.keys(), *wanted)


if __name__ == "__main__":
    m = _map()
    denied = sorted({(csv, col) for csv, cols in m.items()
                      for col, row in cols.items() if row["action"] == "denied"})
    print(f"{len(m)} CSVs in {COLUMN_MAP_PATH}, "
          f"{len(denied)} denied (csv, column) pairs")
