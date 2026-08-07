"""Count the unit of aggregation, never the row count.

A sweep that dies half way through leaves a **perfectly well-formed** data
file. Every row in it is valid. The header is right. It parses, it loads, it
plots. Nothing about the file says it is a prefix.

The instance this generalizes from: a findings document was written from a CSV
holding 11 of an intended 21 units. Every aggregate in it came out roughly 2x
optimistic, and nothing flagged it -- not the parser, not the plotting code,
not a value check, because the values were correctly computed over the rows
that were there. A row-count check would not have caught it either: the count
was a plausible number, and nobody knew what the right one was.

What catches it is counting the *unit the aggregation is over*. If the reduction
is "median within an operator, then geomean across operators", then the number
that must be pinned is the count of distinct operators -- not rows, not cells,
not seeds. Pin it once, beside the derivation, and a truncated sweep fails
loudly on the next run.

The corollary is a design rule for the derivation module: every reduction
should name its unit, and every published aggregate should have that unit's
count asserted next to it.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable, Sequence

__all__ = ["aggregation_unit", "units_of", "assert_aggregation_unit"]


def _keyfn(key: str | Callable[[Any], Any]) -> Callable[[Any], Any]:
    if callable(key):
        return key

    def get(row: Any) -> Any:
        try:
            return row[key]
        except (TypeError, KeyError, IndexError):
            return getattr(row, key)

    return get


def units_of(rows: Iterable[Any], key: str | Callable[[Any], Any]) -> set:
    """The distinct values of `key` across `rows`."""
    get = _keyfn(key)
    return {get(row) for row in rows}


def aggregation_unit(rows: Iterable[Any], key: str | Callable[[Any], Any]) -> int:
    """How many distinct units the data covers. Never `len(rows)`."""
    return len(units_of(rows, key))


def assert_aggregation_unit(
    rows: Sequence[Any],
    key: str | Callable[[Any], Any],
    expected: int,
    *,
    unit: str = "unit",
    source: str = "the data",
    also_expect_rows: int | None = None,
) -> int:
    """Assert the data covers exactly `expected` distinct units of aggregation.

        assert_aggregation_unit(rows, "part", 4, unit="part",
                                source="results.csv")

    `also_expect_rows` optionally pins the row count too -- useful, but never a
    substitute: a sweep can lose a unit and keep the row count by running the
    survivors longer, and it can gain rows without gaining a unit.

    Returns the observed unit count.
    """
    found = units_of(rows, key)
    seen = len(found)
    if seen != expected:
        sample = sorted(map(str, found))[:12]
        direction = "short of" if seen < expected else "beyond"
        raise AssertionError(
            f"{source} covers {seen} distinct {unit}(s), expected {expected} "
            f"-- {direction} the intended sweep.\n"
            f"  rows: {len(rows)}   {unit}s seen: {sample}"
            f"{' ...' if len(found) > 12 else ''}\n"
            f"  A partial sweep is a well-formed file of a prefix; the row count and the "
            f"parser both accept it. Counting {unit}s is what catches it, and every "
            f"aggregate below this point is wrong by an unknown factor until it is fixed."
        )
    if also_expect_rows is not None and len(rows) != also_expect_rows:
        raise AssertionError(
            f"{source} has {len(rows)} rows, expected {also_expect_rows} "
            f"(the {unit} count of {expected} is correct, so this is uneven coverage: "
            f"some {unit}s have more rows than others)."
        )
    return seen
