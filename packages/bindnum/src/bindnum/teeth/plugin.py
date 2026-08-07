"""The pytest side of pytest-teeth: `--mutation-todo`.

Registered via the `pytest11` entry point in pyproject.toml, so `pytest
--mutation-todo` works once bindnum is installed. Without installation, add

    pytest_plugins = ["bindnum.teeth.plugin"]

to your top-level conftest.py.

The report is deliberately not a failure by default. Mutation coverage is a
discipline you ratchet toward, and a plugin that fails the suite on day one
gets removed on day one. `--mutation-todo-strict` turns it into an exit code
once you are ready for it.
"""

from __future__ import annotations

from . import MUTATION_MARKER


def pytest_addoption(parser) -> None:
    group = parser.getgroup("teeth", "assertions that have been proven to bite")
    group.addoption(
        "--mutation-todo",
        action="store_true",
        default=False,
        help="report tests with no recorded @mutation_verified run",
    )
    group.addoption(
        "--mutation-todo-strict",
        action="store_true",
        default=False,
        help="as --mutation-todo, but exit non-zero when any test is unverified",
    )


def pytest_configure(config) -> None:
    config.addinivalue_line(
        "markers",
        f"{MUTATION_MARKER}(date, mutation, result): records a mutation run that was "
        f"performed against this test and observed to fail.",
    )
    config._teeth_unverified = []  # type: ignore[attr-defined]
    config._teeth_verified = []  # type: ignore[attr-defined]


def pytest_collection_modifyitems(session, config, items) -> None:
    if not (config.getoption("--mutation-todo") or config.getoption("--mutation-todo-strict")):
        return
    for item in items:
        marker = item.get_closest_marker(MUTATION_MARKER)
        if marker is None:
            config._teeth_unverified.append(item.nodeid)  # type: ignore[attr-defined]
        else:
            config._teeth_verified.append(  # type: ignore[attr-defined]
                (item.nodeid, marker.kwargs.get("date", "?"), marker.kwargs.get("mutation", "?"))
            )


def pytest_terminal_summary(terminalreporter, exitstatus, config) -> None:
    if not (config.getoption("--mutation-todo") or config.getoption("--mutation-todo-strict")):
        return
    unverified = getattr(config, "_teeth_unverified", [])
    verified = getattr(config, "_teeth_verified", [])
    total = len(unverified) + len(verified)
    terminalreporter.write_sep("=", "mutation ledger")
    if total:
        terminalreporter.write_line(
            f"{len(verified)}/{total} collected tests carry a recorded mutation run."
        )
    for node in unverified:
        terminalreporter.write_line(f"  TODO  {node}")
    if not unverified and total:
        terminalreporter.write_line("  every collected test has been mutation-tested.")
    if unverified and config.getoption("--mutation-todo-strict"):
        terminalreporter.write_line(
            "  --mutation-todo-strict: an assertion nobody has watched fail is a hypothesis."
        )
        session = getattr(terminalreporter, "_session", None)
        if session is not None:
            session.exitstatus = 1
        config._teeth_failed = True  # type: ignore[attr-defined]


def pytest_sessionfinish(session, exitstatus) -> None:
    if getattr(session.config, "_teeth_failed", False) and session.exitstatus == 0:
        session.exitstatus = 1
