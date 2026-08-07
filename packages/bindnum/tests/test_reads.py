"""Read tracking: the structural check a value check cannot replace."""

from __future__ import annotations

import io
import json
import pathlib

import pytest

from bindnum import assert_reads, mutation_verified, reads_of_script, track_reads


@pytest.fixture
def data(tmp_path):
    (tmp_path / "results.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    (tmp_path / "other.json").write_text('{"x": 1}', encoding="utf-8")
    return tmp_path


@mutation_verified(
    "2026-08-04",
    "inverted `_is_read` so only write-mode opens are recorded",
    result="fails naming results.csv; reverted; passes",
)
def test_a_real_read_is_observed(data):
    def derivation() -> int:
        with open(data / "results.csv", encoding="utf-8") as handle:
            return len(handle.read())

    assert assert_reads(derivation, ["results.csv"]) > 0


@mutation_verified(
    "2026-08-04",
    "hardcoded `missing = []` in assert_reads",
    result="this test stops raising; reverted; passes",
)
def test_the_hardcoded_literal_is_caught_although_its_value_is_correct(data):
    """The specimen, in miniature. The number is right; the claim is false."""
    real = 8  # what reading the file would give

    def derivation() -> int:
        return real  # correct value, no read

    with pytest.raises(AssertionError, match="NOTHING was opened for reading"):
        assert_reads(derivation, ["results.csv"])


@mutation_verified(
    "2026-08-04",
    "dropped the io.open patch, leaving only builtins.open",
    result="the pathlib case fails; reverted; passes",
)
def test_pathlib_and_json_reads_are_observed_too(data):
    """`pathlib.Path.open` goes through io.open, not builtins.open."""

    def via_pathlib() -> str:
        return pathlib.Path(data / "results.csv").read_text(encoding="utf-8")

    assert_reads(via_pathlib, ["results.csv"])

    def via_json() -> dict:
        with io.open(data / "other.json", encoding="utf-8") as handle:
            return json.load(handle)

    assert_reads(via_json, ["other.json"])


@mutation_verified(
    "2026-08-04",
    "made `_is_read` return True for every mode",
    result="the forbid assertion fires on a file that was only written; reverted; passes",
)
def test_a_write_is_not_a_read(data, tmp_path):
    def writer() -> None:
        with open(tmp_path / "out.svg", "w", encoding="utf-8") as handle:
            handle.write("<svg/>")

    _result, log = track_reads(writer)
    assert not log.saw("out.svg")


@mutation_verified(
    "2026-08-04",
    "deleted the `banned` block from assert_reads",
    result="this test stops raising; reverted; passes",
)
def test_forbid_catches_a_read_that_should_not_happen(data):
    def derivation() -> None:
        open(data / "other.json", encoding="utf-8").close()

    with pytest.raises(AssertionError, match="forbids"):
        assert_reads(
            lambda: (open(data / "results.csv", encoding="utf-8").close(), derivation()),
            ["results.csv"],
            forbid=["other.json"],
        )


@mutation_verified(
    "2026-08-04",
    "allowed an empty expected_paths list through",
    result="this test stops raising; reverted; passes",
)
def test_assert_reads_refuses_an_empty_expectation():
    """An assertion that cannot fail is worse than an absent one."""
    with pytest.raises(AssertionError, match="cannot fail"):
        assert_reads(lambda: None, [])


@mutation_verified(
    "2026-08-04",
    "removed the finally: block that restores builtins.open",
    result="every later test in the session sees a patched open; reverted; passes",
)
def test_open_is_restored_even_when_the_derivation_raises():
    original = open

    def boom() -> None:
        raise RuntimeError("derivation failed")

    with pytest.raises(RuntimeError):
        track_reads(boom)
    assert open is original


@mutation_verified(
    "2026-08-04",
    "made reads_of_script default to in_scratch_dir=False",
    result="side_effect.txt lands beside the source and this fails; reverted; passes",
)
def test_reads_of_script_runs_from_a_scratch_directory(tmp_path):
    """The first draft of this test asserted the side effect was absent from
    `tmp_path`, and the mutation run showed it green: with the scratch
    directory disabled the file lands in the *caller's* cwd -- the repository
    -- which `tmp_path` knows nothing about. Assert the working directory
    itself, not one place the debris is not."""
    import os

    script = tmp_path / "probe.py"
    script.write_text(
        "import os\n"
        "with open('side_effect.txt', 'w') as h:\n    h.write('x')\n"
        "WHERE = os.getcwd()\n",
        encoding="utf-8",
    )
    before = os.getcwd()
    namespace, _log = reads_of_script(script)
    assert os.getcwd() == before, "reads_of_script did not restore the working directory"
    ran_in = namespace["WHERE"]
    assert ran_in != before, (
        f"the script ran in the caller's own directory ({before}), so its "
        f"side effects land in the repository"
    )
    assert not os.path.exists(ran_in), "the scratch directory was not cleaned up"
    assert not (tmp_path / "side_effect.txt").exists()


@mutation_verified(
    "2026-08-04",
    "changed ReadLog.saw to `normal.endswith(target)` without the os.sep guard",
    result="the bare-suffix `sults.csv` matches and this fails; reverted; passes",
)
def test_matching_is_by_basename_or_suffix(data):
    def derivation() -> None:
        open(data / "results.csv", encoding="utf-8").close()

    _result, log = track_reads(derivation)
    assert log.saw("results.csv")
    assert log.saw(str(data / "results.csv"))
    assert not log.saw("sults.csv"), "suffix matching must respect path separators"
