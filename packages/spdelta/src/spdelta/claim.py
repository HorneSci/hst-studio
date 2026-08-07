"""A speedup, welded to the conditions that produced it.

The problem
-----------
A ratio is a float, and a float travels. It gets copied out of a table into a
slide, out of the slide into a deck, out of the deck into a sentence, and every
hop drops a condition. By the end, "3.5x" is being quoted against a different
baseline, at a churn rate nobody measured, on a toolchain that changes the
answer by more than the effect does.

Every part of that has happened. One published ratio was correct arithmetic
against a baseline that did less work than the arm it was compared to. Another
was quoted at a churn rate above anything that had been run. A third moved by
3-7x on a compiler change, which was larger than any algorithmic difference in
the study.

The fix here is blunt: :class:`Claim` carries the number and its conditions in
one frozen object, and **does not implement** ``__float__``. ``float(claim)``
raises ``TypeError``. You cannot extract the number without deciding to, in
code, by name -- at which point the conditions are right there and dropping them
is a choice rather than an accident.

The fields are not decoration. Each one is a condition that has silently changed
under a published number at least once:

``baseline``      what it is faster *than*. Ratios against different rungs of a
                  baseline ladder differ by two orders of magnitude and cannot
                  be chained.
``motion``        which generator moved the dirty set. Two generators sharing
                  the label "jump" differed by up to 1.82x on identical
                  operators.
``rho``           the churn rate this was measured at.
``rho_ceiling``   the largest rate that was actually run. Above it the honest
                  word is "unmeasured", not "weak".
``toolchain``     interpreter, libraries, machine.
``control``       what was held fixed, and what checked the answer.
``n_cells``       how many cells the reduction consumed. A ratio over three
                  cells and a ratio over three hundred print identically.
``reduction``     which of the two defensible reduction shapes was used. They
                  disagree, and the disagreement moves published numbers.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Sequence

from .harness import REDUCTIONS, Row

__all__ = ["Claim"]


@dataclass(frozen=True)
class Claim:
    """A measured ratio and the conditions under which it holds.

    Deliberately not a number. See the module docstring.
    """

    ratio: float
    baseline: str
    motion: str
    rho: float
    rho_ceiling: float
    toolchain: str
    control: str
    n_cells: int
    reduction: str

    def __post_init__(self) -> None:
        if not (self.ratio > 0):
            raise ValueError(f"ratio must be positive, got {self.ratio}")
        if self.n_cells < 1:
            raise ValueError(f"n_cells must be >= 1, got {self.n_cells}")
        if self.rho > self.rho_ceiling:
            raise ValueError(
                f"rho {self.rho} exceeds the measured ceiling {self.rho_ceiling}: "
                "a claim cannot be stated at a rate that was never run"
            )
        if self.reduction not in REDUCTIONS:
            raise ValueError(
                f"unknown reduction {self.reduction!r}; expected one of "
                f"{sorted(REDUCTIONS)}"
            )
        if not self.baseline:
            raise ValueError("baseline must be named; 'faster' alone is not a claim")

    def __float__(self) -> float:
        raise TypeError(
            "float(claim) is refused on purpose (see the module docstring): a "
            "ratio that has been pried loose from its baseline, motion model, "
            "churn rate, toolchain and control is exactly how a number outlives "
            "the conditions that made it true. If you have decided, by name, "
            "that you only need the number -- use claim.ratio. If you want the "
            "number and the conditions, use str(claim) or claim.as_dict()."
        )

    def __str__(self) -> str:
        rate = "frozen (no churn)" if self.rho == 0 else f"rho={self.rho:g}"
        return (
            f"{self.ratio:.3f}x vs {self.baseline}\n"
            f"  motion      {self.motion}\n"
            f"  churn       {rate}, measured ceiling rho<={self.rho_ceiling:g} "
            f"(above it: unmeasured, not weak)\n"
            f"  toolchain   {self.toolchain}\n"
            f"  control     {self.control}\n"
            f"  cells       {self.n_cells}\n"
            f"  reduction   {self.reduction}"
        )

    def as_dict(self) -> dict[str, Any]:
        """The claim as a plain mapping, conditions included.

        The supported way to serialise one. Note there is no way to get the
        ratio out of here without carrying the rest of the dict with it.
        """
        return asdict(self)

    @classmethod
    def from_rows(
        cls,
        rows: Sequence[Row],
        *,
        baseline: str,
        reduction: str,
        value_key: str = "ratio",
    ) -> Claim:
        """Reduce paired rows -- from :func:`spdelta.harness.ratio_rows` -- to a claim.

        ``reduction`` has no default on purpose. Two shapes are in use, both are
        defensible, they disagree, and choosing between them moves the published
        number. A default would be this package quietly making that choice for
        every caller.

        Every condition is read off the rows rather than passed in, so a claim
        cannot describe a run that did not happen. Rows that disagree about the
        motion model, the toolchain or the control are rejected: pooling two
        motion models into one ratio produces a number that describes neither.
        """
        rows = list(rows)
        if not rows:
            raise ValueError("no rows to reduce; an empty claim is not a claim")
        if reduction not in REDUCTIONS:
            raise ValueError(
                f"unknown reduction {reduction!r}; choose one of "
                f"{sorted(REDUCTIONS)} explicitly -- there is no default, "
                "because the choice moves the number"
            )

        def one(field: str) -> Any:
            values = {r[field] for r in rows}
            if len(values) != 1:
                raise ValueError(
                    f"rows disagree on {field!r}: {sorted(map(str, values))}. "
                    "A single claim cannot span two of these; reduce them "
                    "separately and report both"
                )
            return values.pop()

        for field in ("baseline", "arm"):
            if field not in rows[0]:
                raise ValueError(
                    f"rows are missing {field!r}; pass rows from "
                    "spdelta.harness.ratio_rows"
                )
        if one("baseline") != baseline:
            raise ValueError(
                f"rows were paired against {one('baseline')!r}, not {baseline!r}"
            )

        rhos = sorted({float(r["rho"]) for r in rows})
        if len(rhos) != 1:
            raise ValueError(
                f"rows span churn rates {rhos}; a claim states one rate. "
                "Reduce per rate, or state the ceiling and say which rate the "
                "ratio is at"
            )
        ratio = REDUCTIONS[reduction](rows, lambda r: float(r[value_key]))
        n_cells = len({(r["operator"], r["rho"]) for r in rows})
        return cls(
            ratio=float(ratio),
            baseline=baseline,
            motion=one("motion"),
            rho=rhos[0],
            rho_ceiling=rhos[0],
            toolchain=one("toolchain"),
            control=one("control"),
            n_cells=n_cells,
            reduction=reduction,
        )

    def with_ceiling(self, rho_ceiling: float) -> Claim:
        """Restate the measured ceiling.

        Separate from :meth:`from_rows` because the ceiling is a property of the
        whole sweep, not of the subset a single claim was reduced from: a claim
        at rho=0.01 taken from a sweep that also ran 0.25 has a ceiling of 0.25,
        and only the caller knows that.
        """
        if rho_ceiling < self.rho:
            raise ValueError(
                f"ceiling {rho_ceiling} is below this claim's rate {self.rho}"
            )
        return Claim(
            ratio=self.ratio,
            baseline=self.baseline,
            motion=self.motion,
            rho=self.rho,
            rho_ceiling=float(rho_ceiling),
            toolchain=self.toolchain,
            control=self.control,
            n_cells=self.n_cells,
            reduction=self.reduction,
        )
