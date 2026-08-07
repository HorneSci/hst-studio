"""How a stated value is compared to a derived one.

The default rule is *exact to the precision the document states*. A document
saying "1.31" is asserting two decimal places, so a derivation of 1.31419...
agrees with it and a derivation of 1.32 does not. Inferring the tolerance from
the prose is the whole point of the assertive direction: the writer already
chose how precise the claim was, and the binding should hold them to exactly
that, not to a tolerance the test author picked later.

Overrides exist (`places`, `abs_tol`, `rel_tol`) for the cases where the stated
text does not carry its own precision -- ranges, percentages rounded elsewhere,
values written in exponent form.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

__all__ = ["Tolerance", "parse_number", "decimals_of", "values_match", "describe"]

_EXPONENT = re.compile(r"[eE][-+]?\d+")
_MANTISSA_DECIMALS = re.compile(r"\.(\d+)")


def parse_number(raw: str) -> float:
    """Parse a number as written in prose: commas, unicode minus, stray spaces."""
    cleaned = (
        str(raw)
        .strip()
        .replace(",", "")
        .replace("−", "-")
        .replace("–", "-")
        .replace(" ", "")
        .replace(" ", "")
    )
    return float(cleaned)


def decimals_of(raw: str) -> int:
    """Decimal places the written form commits to.

    "1.31" -> 2, "23" -> 0, "1.60e-15" -> 2 (mantissa decimals only; the
    exponent is handled separately by `values_match`).
    """
    mantissa = _EXPONENT.sub("", str(raw))
    found = _MANTISSA_DECIMALS.search(mantissa)
    return len(found.group(1)) if found else 0


def _exponent_of(raw: str) -> int:
    found = _EXPONENT.search(str(raw))
    return int(found.group(0)[1:]) if found else 0


@dataclass(frozen=True)
class Tolerance:
    """An explicit comparison rule, or the inferred one when all fields are None."""

    places: int | None = None
    abs_tol: float | None = None
    rel_tol: float | None = None

    @property
    def is_inferred(self) -> bool:
        return self.places is None and self.abs_tol is None and self.rel_tol is None

    def describe(self, stated_raw: str) -> str:
        if self.abs_tol is not None:
            return f"|difference| <= {self.abs_tol:g}"
        if self.rel_tol is not None:
            return f"relative difference <= {self.rel_tol:g}"
        places = self.places if self.places is not None else decimals_of(stated_raw)
        return f"equal at {places} decimal place(s) (inferred from {stated_raw!r})"


def values_match(stated_raw: str, derived: float, tol: Tolerance | None = None) -> bool:
    """True when `derived` agrees with the value as the document wrote it."""
    tol = tol or Tolerance()
    stated = parse_number(stated_raw)

    if tol.abs_tol is not None:
        return abs(derived - stated) <= tol.abs_tol
    if tol.rel_tol is not None:
        return math.isclose(derived, stated, rel_tol=tol.rel_tol, abs_tol=0.0)

    places = tol.places if tol.places is not None else decimals_of(stated_raw)

    if _EXPONENT.search(str(stated_raw)) and tol.places is None:
        # Exponent form: the mantissa's decimals set the significant figures,
        # so the tolerance is relative, not absolute.
        span = 0.5 * 10 ** (_exponent_of(stated_raw) - places)
        return abs(derived - stated) <= span

    return round(derived, places) == round(stated, places)


def describe(stated_raw: str, derived: float, tol: Tolerance | None = None) -> str:
    tol = tol or Tolerance()
    return (
        f"document states {stated_raw!r} ({parse_number(stated_raw)!r}); "
        f"derivation gives {derived!r}; rule: {tol.describe(stated_raw)}"
    )
