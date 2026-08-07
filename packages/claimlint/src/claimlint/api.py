"""The one-call surface: scan a project, get reports and a ratchet result."""

from __future__ import annotations

from dataclasses import dataclass, field

from .config import Config, load
from .corpus import Corpus, discover
from .ratchet import RatchetResult, check_floors, run_ratchet
from .scan import FileReport, scan_file

__all__ = ["Result", "run"]


@dataclass
class Result:
    config: Config
    corpus: Corpus
    reports: list[FileReport] = field(default_factory=list)
    ratchet: RatchetResult | None = None
    floor_failures: list[str] = field(default_factory=list)

    @property
    def with_claims(self) -> list[FileReport]:
        return [r for r in self.reports if r.has_claims and not r.error]

    @property
    def incomplete(self) -> list[FileReport]:
        return [r for r in self.reports if r.missing]

    @property
    def unreadable(self) -> list[FileReport]:
        """Documents that could not be read at all -- the third state.

        Neither clean nor failing: never examined. `FileReport.error` has
        always recorded this correctly and `FileReport.clean` has always been
        false for it, but nothing above consulted either, so a corpus of
        entirely unreadable documents reported "0 missing at least one
        element" and exited 0. `incomplete` filters on `r.missing`, which is
        empty for a report that never got as far as scanning -- so the
        invariant held at the level nobody read, and the exit code is the
        level CI reads.

        A UTF-16 file with a BOM is ordinary Windows output; a permission bit
        is an ordinary checkout accident. Both are how a corpus silently
        shrinks. See VACUOUS_TESTS.md #8, which cites this class as its
        exemplar -- it was, one layer down, and was not where it counted.
        """
        return [r for r in self.reports if r.error]

    @property
    def rules_ok(self) -> bool:
        """Did the documents that WERE read satisfy the rules?

        Split out from `ok` so that "every document passed" and "every document
        was read" stay separately answerable. Only a caller that has explicitly
        accepted an incompletely-read corpus should ask this one; `ok` is the
        property to assert on, and it requires both.
        """
        ratchet_ok = self.ratchet.ok if self.ratchet is not None else not self.incomplete
        return ratchet_ok and not self.floor_failures

    @property
    def ok(self) -> bool:
        return self.rules_ok and not self.unreadable


def run(
    root: str = ".",
    *,
    config: Config | None = None,
    apply_ratchet: bool = True,
    **load_kwargs,
) -> Result:
    """Scan `root` and return everything a caller could want to assert on."""
    config = config or load(root, **load_kwargs)
    corpus = discover(
        config.root, config.include, config.exclude, prefer_git=config.corpus != "walk"
    )
    elements = config.compiled_elements
    ratio = config.compiled_ratio
    reports = [
        scan_file(
            path,
            required=config.required,
            elements=elements,
            window=config.window,
            ratio=ratio,
            root=config.root,
        )
        for path in corpus.paths
    ]
    result = Result(config=config, corpus=corpus, reports=reports)
    if apply_ratchet:
        result.ratchet = run_ratchet(reports, config)
    result.floor_failures = check_floors(reports, len(corpus), config.floors)
    return result
