"""bindnum -- bind the numbers already in your prose to the data behind them.

Literate programming solves the *generative* direction: write a template, and
the build produces the number, so prose and data cannot disagree because only
one of them exists. knitr, Quarto, showyourwork and myst-nb all live there.

bindnum solves the *assertive* direction. Your prose already has numbers in it.
Each one gets bound to a derivation, and the test suite fails when the two
diverge -- in either direction:

    somebody edits a number in prose      -> stated != derived -> fail
    somebody regenerates the source data  -> stated != derived -> fail

The inversion is what makes it adoptable. You do not rewrite the document, do
not move the corpus into notebooks, and do not lose the numbers' formatting or
their sentences. You add one test module.

Five surfaces, each from a distinct failure that a value check cannot see:

    Doc / binds              a stated value, located by (section, label) --
                             never by magnitude
    binds_pair               two near-identical figures that must not be
                             interchangeable; the check runs the swap itself
    assert_reads             structural proof a derivation touched its data;
                             hardcoded literals that are numerically *correct*
                             pass every value check
    assert_unique_reduction  exactly one candidate reduction may reproduce a
                             published table -- none means divergence, many
                             means the table cannot verify its own methodology
    assert_aggregation_unit  count operators, not rows: a truncated sweep is a
                             well-formed file of a prefix

See VACUOUS_TESTS.md for the taxonomy of tests that pass without checking
anything, and bindnum.teeth for the two standing rules against it.
"""

from __future__ import annotations

from .aggregation import aggregation_unit, assert_aggregation_unit, units_of
from .binding import (
    Binding,
    BindingError,
    NonDiscriminatingPair,
    PairBinding,
    bindings,
    binds,
    binds_pair,
    check_all,
    clear_bindings,
)
from .compare import Tolerance, decimals_of, parse_number, values_match
from .doc import AmbiguousLabel, Doc, DocError, SectionNotFound, Stated, ValueNotFound
from .reads import ReadLog, assert_reads, reads_of_script, record_reads, track_reads
from .reduction import (
    AmbiguousReduction,
    CandidateCouldNotRun,
    NoReductionReproduces,
    WrongReductionDeclared,
    assert_unique_reduction,
    reduction_report,
)
from .teeth import assert_corpus_floor, mutation_verified

__version__ = "0.1.0"

__all__ = [
    "__version__",
    # documents and bindings
    "Doc",
    "Stated",
    "binds",
    "binds_pair",
    "bindings",
    "clear_bindings",
    "check_all",
    "Binding",
    "PairBinding",
    # comparison
    "Tolerance",
    "values_match",
    "decimals_of",
    "parse_number",
    # structural checks
    "assert_reads",
    "track_reads",
    "record_reads",
    "reads_of_script",
    "ReadLog",
    "assert_unique_reduction",
    "reduction_report",
    "assert_aggregation_unit",
    "aggregation_unit",
    "units_of",
    # teeth
    "assert_corpus_floor",
    "mutation_verified",
    # errors
    "DocError",
    "ValueNotFound",
    "AmbiguousLabel",
    "SectionNotFound",
    "BindingError",
    "NonDiscriminatingPair",
    "NoReductionReproduces",
    "AmbiguousReduction",
    "CandidateCouldNotRun",
    "WrongReductionDeclared",
]
