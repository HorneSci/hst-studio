"""Unique-reduction checking: does the declared method actually decide the table?

A published table of aggregates is produced by *some* reduction -- a mean, a
median, a median-within-group-then-geomean-across-groups, a per-seed geomean
then a median. Documents name one. Analysis scripts often implement another.
When both are floating around, "the number reproduces" is not a check. It is a
coin flip with a documented answer.

`assert_unique_reduction` makes the ambiguity itself the assertion. Run every
plausible reduction against the whole published table and require that
**exactly one** reproduces it:

    none  -> the table and the data have diverged. Somebody edited a cell, or
             regenerated the source, and nothing noticed.
    one   -> the declared method is verified, and the table is evidence of it.
    many  -> the cells do not discriminate. The declared method is unverifiable
             from this table: you could swap it for another and no number would
             move. That is a *finding*, not a pass -- it says the table cannot
             support the methodology sentence written above it.

The third outcome is the one nothing else reports. A single-cell check reduces
to "does 1.42 equal 1.42", which several different reductions will satisfy at
two decimal places; only running the candidates across every cell at once
separates them.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping

from .compare import Tolerance, parse_number, values_match

__all__ = [
    "assert_unique_reduction",
    "reduction_report",
    "NoReductionReproduces",
    "AmbiguousReduction",
    "WrongReductionDeclared",
    "CandidateCouldNotRun",
]


class NoReductionReproduces(AssertionError):
    """The published table matches none of the candidate reductions."""


class AmbiguousReduction(AssertionError):
    """More than one candidate reproduces the table: it does not discriminate."""


class WrongReductionDeclared(AssertionError):
    """Exactly one reduction reproduces the table, and it is not the declared one."""


class CandidateCouldNotRun(AssertionError):
    """A rival that might have won instead raised, so uniqueness was never tested.

    The symmetric twin of `AmbiguousReduction`, and the more dangerous one.
    Ambiguity collapses the verdict toward *many* winners and is reported
    loudly. Broken rivals collapse it toward *one* -- and one winner is the
    strongest pass this module can return. So a table whose rivals all raised
    on an import error, a typo'd column name or an empty group certifies
    clean, having discriminated against nothing.

    This fires only when the error could have changed the verdict: a candidate
    that raised on some cells but *mismatched* one it did run has lost on the
    merits, and is not reported here.
    """


def reduction_report(
    table: Mapping[Any, Any],
    candidates: Mapping[str, Callable[[Any], float]],
    *,
    tol: Tolerance | None = None,
) -> dict[str, dict[Any, bool]]:
    """{reduction name: {cell key: reproduced?}} for every candidate and cell."""
    tol = tol or Tolerance()
    report: dict[str, dict[Any, bool]] = {}
    for name, reduce in candidates.items():
        per_cell: dict[Any, bool] = {}
        for key, published in table.items():
            raw = published if isinstance(published, str) else repr(published)
            try:
                derived = float(reduce(key))
            # NOT "a candidate that cannot run is a candidate that lost" -- that was the
            # old comment here and it is exactly backwards for a uniqueness check. A
            # rival that raised did not lose; it never competed. Recorded as False so
            # the report stays a plain bool table, and separated out in `_errors` so
            # `assert_unique_reduction` can tell "beaten" from "never ran".
            except Exception as exc:
                per_cell[key] = False
                report.setdefault("_errors", {})[(name, key)] = repr(exc)  # type: ignore[index]
                continue
            per_cell[key] = values_match(raw, derived, tol)
        report[name] = per_cell
    return report


def assert_unique_reduction(
    table: Mapping[Any, Any],
    candidates: Mapping[str, Callable[[Any], float]],
    *,
    declared: str | None = None,
    places: int | None = None,
    abs_tol: float | None = None,
    rel_tol: float | None = None,
    what: str = "the published table",
    allow_candidate_errors: bool = False,
) -> str:
    """Require exactly one candidate reduction to reproduce every cell.

    `table` maps a cell key to the published value. Strings are preferred --
    "1.42" carries the precision the document committed to, and the comparison
    is then exact at that precision. Floats work, using their repr.

    `candidates` maps a reduction's name to a callable taking a cell key and
    returning the derived value for that cell.

    A candidate that *raises* is not a candidate that lost. If a rival could
    still have reproduced every cell it managed to run, the check refuses with
    `CandidateCouldNotRun` rather than certifying the survivor: uniqueness
    against a field that never started is not uniqueness. Set
    `allow_candidate_errors=True` only when a rival raising is itself the
    expected, meaningful outcome -- and say why at the call site.

    Returns the winning reduction's name.
    """
    if len(table) < 2:
        raise AssertionError(
            f"assert_unique_reduction needs at least two cells to discriminate between "
            f"reductions; got {len(table)}. With one cell every candidate that happens to "
            f"land on the same value wins, which is the ambiguity this check exists to find."
        )
    if len(candidates) < 2:
        raise AssertionError(
            f"assert_unique_reduction needs at least two candidate reductions; got "
            f"{len(candidates)}. A single candidate always 'wins' and proves nothing."
        )

    tol = Tolerance(places=places, abs_tol=abs_tol, rel_tol=rel_tol)
    report = reduction_report(table, candidates, tol=tol)
    errors = report.pop("_errors", {})

    winners = [name for name, cells in report.items() if all(cells.values())]
    summary = "\n".join(
        f"    {name}: reproduces {sum(cells.values())}/{len(cells)} cells"
        + ("" if all(cells.values()) else f"; first miss {_first_miss(cells, table)}")
        for name, cells in report.items()
    )
    tail = f"\n    errors: {errors}" if errors else ""

    # A rival that raised did not lose -- it never competed. Distinguish the two:
    # a candidate that raised on some cells but MISMATCHED one it did run was
    # beaten on the merits and its error is irrelevant. A candidate that raised
    # on some cells and matched every cell it managed might have reproduced the
    # whole table, so every verdict below -- unique winner OR no winner -- is a
    # statement about a field that never started.
    if errors and not allow_candidate_errors:
        errored_cells: dict[str, set[Any]] = {}
        for name, key in errors:
            errored_cells.setdefault(name, set()).add(key)
        unproven = sorted(
            name
            for name, cells in errored_cells.items()
            if all(ok for key, ok in report[name].items() if key not in cells)
        )
        if unproven:
            raise CandidateCouldNotRun(
                f"{len(unproven)} candidate reduction(s) raised on cells they might have "
                f"reproduced, so uniqueness against {what} was never tested: {unproven}\n"
                f"{summary}{tail}\n"
                f"  Each of these matched every cell it managed to run. Had it run the "
                f"rest it might have reproduced the table too, which would make this "
                f"check ambiguous rather than clean. Fix the candidate -- an import "
                f"error, a wrong column name and an empty group all land here -- or "
                f"pass allow_candidate_errors=True if a rival raising is itself the "
                f"meaningful result, and say why at the call site."
            )

    if not winners:
        raise NoReductionReproduces(
            f"no candidate reduction reproduces {what}:\n{summary}{tail}\n"
            f"  The table and the source data have diverged. Either a cell was edited by "
            f"hand, or the data was regenerated and the table was not."
        )
    if len(winners) > 1:
        raise AmbiguousReduction(
            f"{len(winners)} reductions reproduce {what}: {winners}\n{summary}{tail}\n"
            f"  These cells do not discriminate, so the declared method is unverifiable "
            f"from this table -- you could swap it for another and no published number "
            f"would move. State more digits, or publish cells where the methods differ."
        )
    winner = winners[0]
    if declared is not None and winner != declared:
        raise WrongReductionDeclared(
            f"{what} declares the {declared!r} reduction but is reproduced only by "
            f"{winner!r}:\n{summary}{tail}\n"
            f"  The prose and the arithmetic disagree about how the table was made."
        )
    return winner


def _first_miss(cells: Mapping[Any, bool], table: Mapping[Any, Any]) -> str:
    for key, ok in cells.items():
        if not ok:
            return f"{key!r} (published {table[key]!r})"
    return "-"


def as_float(value: Any) -> float:
    """Convenience: published cells written as prose strings ('1.42x')."""
    return parse_number(str(value).rstrip("x×X "))
