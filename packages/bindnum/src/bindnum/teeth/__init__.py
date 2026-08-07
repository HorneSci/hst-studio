"""pytest-teeth -- the two standing rules, made executable.

Shipped inside `bindnum` rather than as a fourth package to install: it is a
pytest plugin registered under the entry-point name `pytest-teeth`, and it is
about forty lines of load-bearing code. Import it from `bindnum.teeth`.

Rule 1: **every module ends in a coverage floor.**
    An assertion that iterates a corpus passes trivially when the corpus is
    empty. The corpus builder -- a glob, a `git ls-files`, a directory walk --
    is the least-tested line in the file and the one most likely to silently
    return nothing. `assert_corpus_floor` is the last test in the module and
    fails when the corpus collapses, so a green module always means documents
    were actually read.

Rule 2: **mutation-test every assertion before commit.**
    Break the thing on purpose, watch the test fail, put it back, watch it
    pass. An assertion nobody has ever seen fail is a hypothesis. Mark the ones
    you have done with `@mutation_verified(...)`, and run `pytest
    --mutation-todo` to list the ones you have not.
"""

from __future__ import annotations

from typing import Any, Sized

__all__ = ["assert_corpus_floor", "mutation_verified", "MUTATION_MARKER"]

MUTATION_MARKER = "mutation_verified"


def assert_corpus_floor(
    corpus: Sized | int,
    minimum: int,
    *,
    what: str = "corpus",
    built_by: str = "",
    was: str = "",
) -> int:
    """Fail when the corpus every other assertion iterates has collapsed.

        def test_the_corpus_is_not_empty():
            assert_corpus_floor(findings_files(), 20,
                                what="tracked findings documents",
                                built_by="git ls-files '*FINDINGS*.md'",
                                was="25 on 2026-08-04")

    Put it last in the module, and set `minimum` a little below the current
    count -- high enough that a collapse fails, low enough that deleting one
    stale document does not.
    """
    size = corpus if isinstance(corpus, int) else len(corpus)
    if size < minimum:
        detail = f" (built by: {built_by})" if built_by else ""
        history = f" It was {was}." if was else ""
        raise AssertionError(
            f"only {size} {what} found, floor is {minimum}{detail}.{history}\n"
            f"  The corpus builder has collapsed. A collapsed corpus passes every "
            f"assertion in this module without reading anything -- one bad pathspec is "
            f"all it takes, and nothing else in the file will complain."
        )
    return size


def mutation_verified(date: str, mutation: str, *, result: str = "fails as expected") -> Any:
    """Mark a test as having had a recorded mutation run.

        @mutation_verified("2026-08-04",
                           "changed results.csv row 3 press_ms 41.0 -> 61.0")
        def test_headline_ratio_binds():
            ...

    The arguments are the ledger. Write the mutation you actually performed,
    specifically enough that the next person can repeat it. `pytest
    --mutation-todo` lists every test lacking this marker.
    """
    import pytest  # local: bindnum's non-pytest surface stays stdlib-only

    return pytest.mark.mutation_verified(date=date, mutation=mutation, result=result)
