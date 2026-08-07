"""Bindings: a derivation, a site in a document, and the assertion between them.

The split this package generalizes is deliberate and worth restating, because
it is the thing that makes the assertive direction survive contact with a real
corpus:

    derive_<topic>.py   pure functions, committed data -> value.
                        NO expected values anywhere in the file.
    test_<topic>.py     asserts the DOCUMENT's stated value equals the derived
                        one.

Keeping the expected values out of the derivation module is what gives the
suite two independent failure directions:

    somebody edits a number in prose   -> stated != derived -> fail
    somebody regenerates a source file -> stated != derived -> fail

A derivation module that carried its own expected values would only ever catch
the first, and would catch it by comparing the document to a second, staler
transcription of the same document. That is `assertion-against-a-transcription`
in VACUOUS_TESTS.md, and it is the most common way a numbers suite comes out
green while meaning nothing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Iterable, Sequence

from .compare import Tolerance, describe, values_match
from .doc import Doc, Stated

__all__ = [
    "Binding",
    "PairBinding",
    "BindingError",
    "NonDiscriminatingPair",
    "binds",
    "binds_pair",
    "bindings",
    "clear_bindings",
    "check_all",
]


class BindingError(AssertionError):
    """A stated value and its derivation disagree."""


class NonDiscriminatingPair(AssertionError):
    """A pair binding cannot tell an arm swap from a correct assignment.

    Raised when the two derived values are close enough that assigning them the
    other way round would also pass. The binding is then vacuous: it asserts
    only that two numbers exist, not that either is beside the right label.
    """


_REGISTRY: list["Binding | PairBinding"] = []


def bindings() -> list["Binding | PairBinding"]:
    """Every binding registered so far, in declaration order."""
    return list(_REGISTRY)


def clear_bindings() -> None:
    """Empty the registry. For tests of bindnum itself, and for REPL use."""
    _REGISTRY.clear()


# --------------------------------------------------------------------------
# single bindings
# --------------------------------------------------------------------------


@dataclass
class Binding:
    """One derivation bound to one stated value."""

    name: str
    doc: Doc
    label: str
    fn: Callable[[], float]
    section: str | None = None
    occurrence: int | None = None
    pattern: str | re.Pattern[str] | None = None
    tol: Tolerance = field(default_factory=Tolerance)
    note: str = ""

    def stated(self) -> Stated:
        return self.doc.stated(
            self.label,
            section=self.section,
            occurrence=self.occurrence,
            pattern=self.pattern,
        )

    def derived(self) -> float:
        return float(self.fn())

    def check(self) -> Stated:
        """Raise `BindingError` if the document and the data disagree."""
        stated = self.stated()
        derived = self.derived()
        if not values_match(stated.raw, derived, self.tol):
            raise BindingError(
                f"{self.name}: {stated.where()} disagrees with its derivation\n"
                f"  {describe(stated.raw, derived, self.tol)}\n"
                f"  line: {stated.line}\n"
                f"  {self.note or 'Either the prose moved or the source data did. Both are real.'}"
            )
        return stated

    def __str__(self) -> str:  # pragma: no cover - convenience
        return f"{self.name} -> {self.doc.path}[{self.section or '*'}:{self.label}]"


def binds(
    doc: Doc,
    *,
    label: str,
    section: str | None = None,
    occurrence: int | None = None,
    pattern: str | re.Pattern[str] | None = None,
    places: int | None = None,
    abs_tol: float | None = None,
    rel_tol: float | None = None,
    name: str | None = None,
    note: str = "",
) -> Callable[[Callable[[], float]], Callable[[], float]]:
    """Register `fn` as the derivation of the value stated at (section, label).

    The decorated function is returned unchanged, so a derivation stays an
    ordinary callable you can use elsewhere.

        DOC = Doc("RESULTS.md")

        @binds(DOC, section="Headline", label="median press ratio")
        def median_press_ratio() -> float:
            return reduce_over_parts(read_rows(RESULTS_CSV))

    Comparison defaults to *exact at the precision the document states*.
    """

    def decorate(fn: Callable[[], float]) -> Callable[[], float]:
        _REGISTRY.append(
            Binding(
                name=name or fn.__name__,
                doc=doc,
                label=label,
                fn=fn,
                section=section,
                occurrence=occurrence,
                pattern=pattern,
                tol=Tolerance(places=places, abs_tol=abs_tol, rel_tol=rel_tol),
                note=note,
            )
        )
        return fn

    return decorate


# --------------------------------------------------------------------------
# pair bindings
# --------------------------------------------------------------------------


@dataclass
class PairBinding:
    """Two stated values whose derivations must not be interchangeable.

    Three-significant-figure ratios near 1 collide constantly, so a pair of
    figures like "1.02x quiet / 0.98x loud" is exactly the shape where a
    magnitude-driven check has nothing to say. The failure being caught here is
    not a typo. It is an **arm swap**: the right two numbers, attached to the
    wrong two labels -- in the document, or in the test that binds it.

    `check()` therefore runs the swap itself and requires it to fail. If the
    cross-assignment also passes, the binding proves nothing and raises
    `NonDiscriminatingPair` rather than going green.
    """

    name: str
    doc: Doc
    first: dict
    second: dict
    fn: Callable[[], Sequence[float]]
    tol: Tolerance = field(default_factory=Tolerance)
    window: float | None = None
    note: str = ""

    def _stated(self, spec: dict) -> Stated:
        return self.doc.stated(
            spec["label"],
            section=spec.get("section"),
            occurrence=spec.get("occurrence"),
            pattern=spec.get("pattern"),
        )

    def stated(self) -> tuple[Stated, Stated]:
        return self._stated(self.first), self._stated(self.second)

    def derived(self) -> tuple[float, float]:
        values = tuple(self.fn())
        if len(values) != 2:
            raise BindingError(
                f"{self.name}: a pair derivation must return exactly two values, got {len(values)}"
            )
        return float(values[0]), float(values[1])

    def check(self) -> tuple[Stated, Stated]:
        a_stated, b_stated = self.stated()
        a_derived, b_derived = self.derived()

        direct = values_match(a_stated.raw, a_derived, self.tol) and values_match(
            b_stated.raw, b_derived, self.tol
        )
        if not direct:
            raise BindingError(
                f"{self.name}: pair disagrees with its derivations\n"
                f"  first  {a_stated.where()}: {describe(a_stated.raw, a_derived, self.tol)}\n"
                f"  second {b_stated.where()}: {describe(b_stated.raw, b_derived, self.tol)}\n"
                f"  {self.note or 'Check for a swap before assuming a typo.'}"
            )

        swapped = values_match(a_stated.raw, b_derived, self.tol) and values_match(
            b_stated.raw, a_derived, self.tol
        )
        if swapped:
            raise NonDiscriminatingPair(
                f"{self.name}: the pair also passes with the two derivations swapped, "
                f"so it cannot detect an arm swap.\n"
                f"  first  {a_stated.where()} states {a_stated.raw!r} ({a_stated.label!r})\n"
                f"  second {b_stated.where()} states {b_stated.raw!r} ({b_stated.label!r})\n"
                f"  derived: {a_derived!r} and {b_derived!r}\n"
                f"  These two figures do not discriminate at the precision the document "
                f"states. Either state more digits, or bind something that differs."
            )

        if self.window is not None and abs(a_derived - b_derived) < self.window:
            raise NonDiscriminatingPair(
                f"{self.name}: derived values {a_derived!r} and {b_derived!r} differ by "
                f"{abs(a_derived - b_derived):g}, under the required window {self.window:g}. "
                f"A reader could not tell these apart, so neither can this binding."
            )
        return a_stated, b_stated

    def __str__(self) -> str:  # pragma: no cover - convenience
        return f"{self.name} -> pair({self.first['label']!r}, {self.second['label']!r})"


def binds_pair(
    doc: Doc,
    *,
    first: dict,
    second: dict,
    window: float | None = None,
    places: int | None = None,
    abs_tol: float | None = None,
    rel_tol: float | None = None,
    name: str | None = None,
    note: str = "",
) -> Callable[[Callable[[], Sequence[float]]], Callable[[], Sequence[float]]]:
    """Bind two stated values to one derivation returning both, in order.

        @binds_pair(DOC,
                    first=dict(section="Arms", label="quiet arm"),
                    second=dict(section="Arms", label="loud arm"),
                    window=0.02)
        def arm_ratios() -> tuple[float, float]:
            return quiet_ratio(), loud_ratio()

    `first` and `second` are label specs: `label`, and optionally `section`,
    `occurrence`, `pattern`. `window` is the minimum separation the two derived
    values must show for the binding to mean anything.
    """

    def decorate(fn: Callable[[], Sequence[float]]) -> Callable[[], Sequence[float]]:
        _REGISTRY.append(
            PairBinding(
                name=name or fn.__name__,
                doc=doc,
                first=first,
                second=second,
                fn=fn,
                tol=Tolerance(places=places, abs_tol=abs_tol, rel_tol=rel_tol),
                window=window,
                note=note,
            )
        )
        return fn

    return decorate


# --------------------------------------------------------------------------
# running them
# --------------------------------------------------------------------------


def check_all(subset: Iterable["Binding | PairBinding"] | None = None) -> int:
    """Check every registered binding; raise on the first disagreement.

    Prefer parametrizing over `bindings()` in pytest so each binding is its own
    test id and one failure does not hide the rest. This exists for scripts and
    for the single-test case.
    """
    todo = list(subset) if subset is not None else bindings()
    if not todo:
        raise AssertionError(
            "no bindings registered -- the module holding them was never imported, "
            "which is corpus vacuity (VACUOUS_TESTS.md #7): every assertion over an "
            "empty registry passes."
        )
    for binding in todo:
        binding.check()
    return len(todo)
