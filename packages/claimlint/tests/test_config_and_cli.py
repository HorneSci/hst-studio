"""Configuration layering, the private-overlay hook, the CLI, and the worked example.

The public/private split is the subject of most of this module. The rule is
that a private deployment and a public one differ by *data only* -- if any
tuning decision needed a code change, the split would be a fork, and the two
would drift.
"""

from __future__ import annotations

import json
import os

import pytest

from claimlint import Config, ConfigError, load, load_data, run
from claimlint.cli import main
from claimlint.config import OVERLAY_ENV

HERE = os.path.dirname(os.path.abspath(__file__))
EXAMPLE = os.path.join(os.path.dirname(HERE), "examples", "corpus")


# --------------------------------------------------------------------------
# the shipped defaults carry no project vocabulary
# --------------------------------------------------------------------------


def test_the_default_profile_loads_with_no_project_config(tmp_path):
    """Zero config is a supported path: the first run has to be worth reading
    or there is no second one."""
    conf = load(str(tmp_path))
    assert conf.required
    assert conf.compiled_elements
    assert conf.sources[0].startswith("<builtin profile: default")


def test_no_element_regex_hardcodes_a_project_specific_term():
    """MUTATION: add a project's own machine name to the hardware regex.
    -> this fails. The shipped profile must be domain-free; a project's
    vocabulary belongs in its own .claimlint.toml, and anything it does not
    want published belongs in the private overlay.
    """
    conf = load("/nonexistent-root")
    joined = " ".join(conf.elements.values()).lower()
    for token in ("hst", "acme", "nuc11", "i7-1165", "example.com", "prod-", "-internal"):
        assert token not in joined, f"default profile mentions {token!r}"
    # ...and the regexes still match ordinary, domain-free prose, so the test
    # above cannot be satisfied by emptying them.
    generic = "measured against the baseline on a 16-core x86 host, 5 runs, gcc 13"
    for name in conf.required:
        assert conf.compiled_elements[name].search(generic), (
            f"the default {name!r} regex no longer matches a plainly-written claim"
        )


def test_strict_profile_extends_default_rather_than_restating_it():
    default = load("/nonexistent-root", profile="default")
    strict = load("/nonexistent-root", profile="strict")
    assert set(default.required) < set(strict.required)
    assert strict.elements == default.elements, "strict must reuse the regexes, not copy them"
    assert strict.window < default.window


def test_an_unknown_profile_names_the_ones_that_exist():
    with pytest.raises(ConfigError, match="available:"):
        load("/nonexistent-root", profile="nope")


# --------------------------------------------------------------------------
# layering
# --------------------------------------------------------------------------


def write(path, text):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def test_a_project_config_layers_onto_the_profile(tmp_path):
    write(
        tmp_path / ".claimlint.toml",
        '[claimlint]\nwindow = 300\nrequired = ["hardware"]\n'
        '[elements]\nhardware = "widget-bench"\n',
    )
    conf = load(str(tmp_path))
    assert conf.window == 300
    assert conf.required == ["hardware"]
    assert conf.elements["hardware"] == "widget-bench"
    # untouched keys survive from the profile
    assert "baseline" in conf.elements


def test_the_private_overlay_layers_last_and_replaces_one_element(tmp_path):
    """MUTATION: apply the overlay before the project config.
    -> the project's value wins and the overlay silently does nothing, which
    is the worst outcome: a private deployment that believes it is tuned."""
    write(
        tmp_path / ".claimlint.toml",
        '[claimlint]\nrequired = ["hardware"]\nprivate_overlay = "private.toml"\n'
        '[elements]\nhardware = "public-pattern"\n',
    )
    write(tmp_path / "private.toml", '[elements]\nhardware = "private-pattern"\n')
    conf = load(str(tmp_path))
    assert conf.elements["hardware"] == "private-pattern"
    assert conf.overlay_applied.endswith("private.toml")
    assert conf.elements["baseline"], "the overlay must not wipe the other elements"


def test_a_missing_overlay_is_not_an_error(tmp_path):
    """MUTATION: raise when a configured overlay is absent.
    -> the public configuration stops standing on its own, and the split
    becomes a fork that happens to be spelled in TOML."""
    write(
        tmp_path / ".claimlint.toml",
        '[claimlint]\nrequired = ["hardware"]\nprivate_overlay = "absent.toml"\n',
    )
    conf = load(str(tmp_path))
    assert conf.overlay_applied == ""


def test_an_overlay_named_on_the_command_line_must_exist(tmp_path):
    with pytest.raises(ConfigError, match="does not exist"):
        load(str(tmp_path), overlay="absent.toml")


def test_the_environment_variable_selects_an_overlay(tmp_path, monkeypatch):
    write(tmp_path / "env.toml", '[claimlint]\nwindow = 42\n')
    monkeypatch.setenv(OVERLAY_ENV, str(tmp_path / "env.toml"))
    assert load(str(tmp_path)).window == 42
    monkeypatch.delenv(OVERLAY_ENV)
    assert load(str(tmp_path)).window != 42


def test_no_overlay_can_be_forced_off(tmp_path, monkeypatch):
    write(tmp_path / "env.toml", '[claimlint]\nwindow = 42\n')
    monkeypatch.setenv(OVERLAY_ENV, str(tmp_path / "env.toml"))
    assert load(str(tmp_path), use_overlay=False).window != 42


def test_allowlist_entries_merge_by_path_not_wholesale(tmp_path):
    write(
        tmp_path / ".claimlint.toml",
        '[claimlint]\nrequired = ["hardware"]\nprivate_overlay = "p.toml"\n'
        '[allowlist."a.md"]\nmissing = ["hardware"]\nreason = "GAP - a"\n',
    )
    write(
        tmp_path / "p.toml",
        '[allowlist."b.md"]\nmissing = ["hardware"]\nreason = "GAP - b"\n',
    )
    conf = load(str(tmp_path))
    assert set(conf.allowlist) == {"a.md", "b.md"}


# --------------------------------------------------------------------------
# validation refuses configurations that cannot fail
# --------------------------------------------------------------------------


def test_an_empty_required_list_is_refused():
    """MUTATION: drop the check.
    -> every document passes and the tool reports a clean corpus while
    checking nothing."""
    with pytest.raises(ConfigError, match="would report a clean corpus"):
        load_data({"claimlint": {"required": []}, "elements": {"a": "x"}}).validate()


def test_a_required_element_with_no_regex_is_refused():
    with pytest.raises(ConfigError, match="no regex"):
        load_data({"claimlint": {"required": ["ghost"]}, "elements": {"a": "x"}}).validate()


def test_an_invalid_regex_is_refused():
    with pytest.raises(ConfigError, match="invalid regex"):
        load_data({"claimlint": {"required": ["a"]}, "elements": {"a": "([unclosed"}}).validate()


def test_an_unknown_corpus_builder_is_refused():
    conf = Config(required=["a"], elements={"a": "x"}, corpus="magic")
    with pytest.raises(ConfigError, match="must be 'auto'"):
        conf.validate()


# --------------------------------------------------------------------------
# the worked example, end to end
# --------------------------------------------------------------------------


def test_the_example_corpus_passes_its_own_ratchet():
    result = run(EXAMPLE)
    assert result.corpus.builder == "filesystem walk"
    assert len(result.corpus) >= 6
    assert result.ratchet is not None and result.ratchet.ok, result.ratchet.messages()
    assert not result.floor_failures


def test_the_example_corpus_still_finds_the_claims_it_is_built_around():
    """MUTATION: any of the three scanner decisions.
    -> these counts move. The example exists so a change to the scanner has
    somewhere concrete to show up."""
    result = run(EXAMPLE)
    by_path = {os.path.basename(r.path): r for r in result.reports}
    assert len(by_path["COMPLETE.md"].claims) == 2
    assert by_path["COMPLETE.md"].clean
    assert by_path["FALSE_POSITIVE_BAIT.md"].claims == [], (
        "hex literals and dimension notation are being reported as ratios"
    )
    assert by_path["NO_RATIOS.md"].claims == []
    assert by_path["MISSING_TWO.md"].missing == {
        "baseline", "hardware", "sample_size", "toolchain"
    }
    assert "toolchain" in by_path["FILENAME_NOT_PROSE.md"].missing, (
        "a compiler named only in a link target and a code span is satisfying "
        "the toolchain requirement"
    )
    assert by_path["WINDOW_NOT_FILE.md"].missing == {"hardware", "toolchain"}, (
        "the far-away 'x86 server' is counting; the check is not windowed"
    )


def test_breaking_a_single_document_breaks_the_ratchet(tmp_path):
    """The example is only worth having if it fails when it should."""
    import shutil

    work = tmp_path / "corpus"
    shutil.copytree(EXAMPLE, work)
    # copytree propagates the SOURCE's mode bits, so on a read-only checkout --
    # a Nix store, an immutable mount, a restored CI cache -- the copy is
    # read-only too and the write_text below dies with PermissionError. The
    # test is about editing a document, not about inheriting permissions.
    for path in work.rglob("*"):
        path.chmod(path.stat().st_mode | 0o200)
    complete = work / "COMPLETE.md"
    complete.write_text(
        complete.read_text(encoding="utf-8").replace("clang 18 at\n-O2", "the usual build"),
        encoding="utf-8",
    )
    result = run(str(work))
    assert not result.ratchet.ok
    assert "COMPLETE.md" in result.ratchet.new_incomplete


# --------------------------------------------------------------------------
# the CLI
# --------------------------------------------------------------------------


def test_cli_exits_zero_on_the_example_with_the_ratchet(capsys):
    assert main([EXAMPLE, "--ratchet"]) == 0
    assert "documents (filesystem walk)" in capsys.readouterr().out


def test_cli_exits_nonzero_without_the_ratchet_because_gaps_exist(capsys):
    """Without the allowlist applied, the same corpus is not clean -- that
    difference is the ratchet doing its job, and it should be visible."""
    assert main([EXAMPLE]) == 1
    assert "missing toolchain" in capsys.readouterr().out


def test_cli_json_is_machine_readable(capsys):
    main([EXAMPLE, "--ratchet", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["corpus"]["size"] >= 6
    assert any(d["path"].endswith("MISSING_TWO.md") for d in payload["documents"])


def test_cli_stanza_is_paste_ready_and_does_not_pass_on_its_own(capsys):
    """MUTATION: emit `reason = "n/a - generated"` instead of a TODO.
    -> pasting the stanza produces a green run with nobody having said why,
    which is the allowlist failure mode in one step."""
    main([EXAMPLE, "--stanza"])
    stanza = capsys.readouterr().out
    assert '[allowlist."MISSING_TWO.md"]' in stanza
    assert "TODO" in stanza


# --------------------------------------------------------------------------
# the front door: a run that read nothing, or exempted nothing, is not a pass
# --------------------------------------------------------------------------


def test_a_pathspec_that_does_not_exist_is_an_error_not_a_clean_corpus(capsys):
    """MUTATION: drop the isdir() guard in cli.main.
    -> `claimlint /nonexistent` reports `0 documents ... ` and exits 0. Green on
    a typo, in the tool whose own README names corpus vacuity as the risk."""
    assert main(["/nonexistent/path/for/claimlint"]) == 2
    err = capsys.readouterr().err
    assert "/nonexistent/path/for/claimlint" in err
    assert "does not exist" in err


def test_a_path_that_is_a_file_not_a_directory_is_an_error(capsys, tmp_path):
    doc = tmp_path / "README.md"
    write(doc, "measured 6.94x\n")
    assert main([str(doc)]) == 2
    assert "is not a directory" in capsys.readouterr().err


def test_a_corpus_of_zero_documents_is_an_error(capsys, tmp_path):
    """MUTATION: allow the empty corpus through.
    -> a directory with no matching documents exits 0, and 'clean' is a claim
    about nothing. The floors cannot cover this: they default to 0, so a
    zero-config user gets none of that protection."""
    (tmp_path / "src").mkdir()
    write(tmp_path / "src" / "main.py", "print('no documents here')\n")
    assert main([str(tmp_path)]) == 2
    err = capsys.readouterr().err
    assert "0 documents" in err
    # the message must name the two knobs that actually fix it
    assert "claimlint.include" in err
    assert "--allow-empty-corpus" in err


def test_an_empty_corpus_can_be_accepted_explicitly(capsys, tmp_path):
    assert main([str(tmp_path), "--allow-empty-corpus"]) == 0


def test_the_generated_stanza_does_not_pass_the_ratchet(capsys, tmp_path):
    """The two-command green build, end to end.

    `--stanza >> .claimlint.toml` then `--ratchet` used to exit 0 with every
    generated reason left verbatim -- in the tool whose README says "Step 4 is
    the work, and it is deliberately not automated". This asserts the README's
    sentence as behaviour, not as intention.

    MUTATION: delete the is_placeholder_reason() call in run_ratchet.
    -> this test goes green at exit 0 and the tool ships a one-command bypass.
    """
    write(tmp_path / "A.md", "# A\n\nOur kernel is 6.94x faster.\n")
    write(tmp_path / "B.md", "# B\n\nWe measured 3.5x here.\n")

    main([str(tmp_path), "--stanza"])
    stanza = capsys.readouterr().out
    # exactly what a user does: append the generated stanza and re-run
    write(tmp_path / ".claimlint.toml", stanza)

    assert main([str(tmp_path), "--ratchet"]) == 1
    out = capsys.readouterr().out
    assert "placeholder" in out
    assert "writing the reason is the work" in out.lower()


def test_a_real_reason_on_the_same_entries_does_pass(capsys, tmp_path):
    """The other half of the mutation: the check must not reject good reasons."""
    write(tmp_path / "A.md", "# A\n\nOur kernel is 6.94x faster.\n")
    write(
        tmp_path / ".claimlint.toml",
        '[allowlist."A.md"]\n'
        'missing = ["baseline", "hardware", "sample_size"]\n'
        'reason = "GAP - inherited note, kept as the specimen for the scanner"\n',
    )
    assert main([str(tmp_path), "--ratchet"]) == 0


def test_a_hand_written_todo_reason_is_refused_too(capsys, tmp_path):
    """The placeholder check is on the non-answer, not on one literal string."""
    write(tmp_path / "A.md", "# A\n\nOur kernel is 6.94x faster.\n")
    write(
        tmp_path / ".claimlint.toml",
        '[allowlist."A.md"]\n'
        'missing = ["baseline", "hardware", "sample_size"]\n'
        'reason = "GAP - FIXME work out why later"\n',
    )
    assert main([str(tmp_path), "--ratchet"]) == 1
    assert "placeholder" in capsys.readouterr().out


def test_an_unknown_config_key_is_refused_with_a_suggestion(capsys, tmp_path):
    """MUTATION: ignore unknown keys, as before.
    -> `requird` silently disables an element check forever. For a tool whose
    thesis is that a check which stops checking is worse than no check, an
    inert key is the worst possible silence."""
    write(tmp_path / ".claimlint.toml", '[claimlint]\nrequird = ["baseline"]\n')
    assert main([str(tmp_path)]) == 2
    err = capsys.readouterr().err
    assert "claimlint.requird" in err
    assert "did you mean 'required'?" in err


def test_an_unknown_table_and_an_unknown_floor_are_refused(tmp_path):
    write(tmp_path / ".claimlint.toml", "[flooors]\nfiles = 3\n")
    with pytest.raises(ConfigError) as exc:
        load(str(tmp_path))
    assert "[flooors]" in str(exc.value)

    write(tmp_path / ".claimlint.toml", "[floors]\nclaim_bearing_file = 3\n")
    with pytest.raises(ConfigError) as exc:
        load(str(tmp_path))
    assert "floors.claim_bearing_file" in str(exc.value)


def test_an_unknown_allowlist_entry_key_is_refused(tmp_path):
    write(
        tmp_path / ".claimlint.toml",
        '[allowlist."A.md"]\nmissing = ["baseline"]\nreason = "GAP - x"\nrationale = "y"\n',
    )
    with pytest.raises(ConfigError) as exc:
        load(str(tmp_path))
    assert 'allowlist."A.md".rationale' in str(exc.value)


def test_the_shipped_profiles_use_no_key_the_loader_would_ignore(tmp_path):
    """The unknown-key check has to hold for our own files first."""
    for name in ("default", "strict"):
        assert load(str(tmp_path), profile=name).required


def test_ratchet_output_distinguishes_new_from_allowlisted(capsys):
    """MUTATION: print every document identically, as before.
    -> a reader cannot tell an exempted finding from a new one by looking; only
    a trailing `, ratchet ok` on the summary line says which, and it says it
    about the run, not about the document."""
    main([EXAMPLE, "--ratchet"])
    out = capsys.readouterr().out
    assert "allowlisted MISSING_TWO.md" in out
    assert "allowed toolchain" in out
    assert "NEW " not in out

    main([EXAMPLE])  # no ratchet: no allowlist is applied, so nothing is marked
    plain = capsys.readouterr().out
    assert "allowlisted" not in plain
    assert "missing toolchain" in plain


def test_cli_show_config_names_every_layer(capsys):
    main([EXAMPLE, "--show-config"])
    out = capsys.readouterr().out
    assert "<builtin profile: default>" in out
    assert ".claimlint.toml" in out
    assert "private overlay applied: (none)" in out


def test_cli_reports_a_bad_config_without_a_traceback(capsys, tmp_path):
    write(tmp_path / ".claimlint.toml", "this is not toml {{{")
    assert main([str(tmp_path)]) == 2
    assert "not valid TOML" in capsys.readouterr().err


# --------------------------------------------------------------------------
# unreadable is a third state, and it must reach the exit code
# --------------------------------------------------------------------------


def _corpus_with_unreadable(tmp_path):
    """One good document, one UTF-16 document, one with no read permission."""
    (tmp_path / "good.md").write_text(
        "# R\n\nHST is 4.5x faster than the delta baseline on an M1 Max, n=30.\n"
    )
    (tmp_path / "utf16.md").write_bytes(
        "# R\n\nHST is 17.6x faster.\n".encode("utf-16")
    )
    noperm = tmp_path / "noperm.md"
    noperm.write_text("# R\n\nratio 7.4x here\n")
    noperm.chmod(0o000)
    return noperm


def test_a_document_that_could_not_be_read_is_not_a_document_that_passed(tmp_path, capsys):
    """Regression for the silent-shrink bug found 2026-08-04.

    `FileReport.error` was a real third state and `FileReport.clean` was
    correctly false for it -- but `Result.incomplete` filters on `r.missing`,
    which is empty for a report that never got as far as scanning. So the
    invariant held at the level nobody consulted, and the exit code, which is
    the level CI reads, was 0 over a corpus that had silently shrunk.

    VACUOUS_TESTS.md #8 cites this package as the exemplar of the fix. It was
    the exemplar one layer down from where it counted.
    """
    noperm = _corpus_with_unreadable(tmp_path)
    if os.access(noperm, os.R_OK):  # root, or a filesystem that ignores the mode
        pytest.skip("cannot make a file unreadable here, so the premise does not hold")
    try:
        assert main([str(tmp_path)]) == 2
        err = capsys.readouterr().err
        assert "could not be read" in err
        assert "utf16.md" in err and "noperm.md" in err
        assert "--allow-unreadable" in err  # the message names its own escape hatch

        # The escape hatch is honoured, and the readable document is still judged.
        assert main([str(tmp_path), "--allow-unreadable"]) == 1

        # --json and --stanza take the same gate: a stanza built from a corpus
        # that was only partly read is an allowlist missing entries.
        assert main([str(tmp_path), "--json"]) == 2
        assert main([str(tmp_path), "--stanza"]) == 2
    finally:
        noperm.chmod(0o644)


def test_a_fully_readable_corpus_is_unaffected_by_the_unreadable_gate(tmp_path):
    """The control. Without it, a gate that always fired would pass the test above.

    This is VACUOUS_TESTS.md #9: an expected-failure test needs a companion
    that must SUCCEED through the same harness, or a broken harness makes
    everything fail and the file passes proving nothing.
    """
    (tmp_path / "good.md").write_text(
        "# R\n\nHST is 4.5x faster compared to the delta baseline, "
        "on an Apple M1 Max CPU, median of n=30 runs.\n"
    )
    assert main([str(tmp_path)]) == 0
    assert main([str(tmp_path), "--json"]) == 0


# --------------------------------------------------------------------------
# a document's identity must not depend on the operating system
# --------------------------------------------------------------------------


def test_the_walk_builder_records_forward_slashes_even_on_a_backslash_host(
    tmp_path, monkeypatch
):
    """MUTATION: drop the `.replace(os.sep, "/")` in `_walked_files` and this fails.

    `git ls-files` emits "/" on every platform. The walk builder used the host
    separator, so on Windows the same corpus produced a different set of
    document IDs -- and the allowlist and the ratchet are keyed on that ID.
    The observed result (2026-08-07, first CI run to gate the release tree off
    Linux) was every allowlisted document reported as an unallowlisted
    violation AND every allowlist entry reported as stale, on a corpus where
    nothing had moved. Both halves are the same bug seen from two sides.

    A posix CI runner cannot reproduce a backslash host, so the host is
    simulated here rather than assumed: without this, the fix would be
    verified only by the Windows job, and a regression would be invisible to
    everyone running the suite locally.
    """
    from claimlint import corpus as corpus_mod

    nested = tmp_path / "docs" / "deep"
    nested.mkdir(parents=True)
    (nested / "claim.md").write_text("# c\n")

    real_relpath = os.path.relpath
    monkeypatch.setattr(
        corpus_mod.os.path,
        "relpath",
        lambda p, start: real_relpath(p, start).replace("/", "\\"),
    )
    monkeypatch.setattr(corpus_mod.os, "sep", "\\")

    found = corpus_mod._walked_files(str(tmp_path))
    assert found == ["docs/deep/claim.md"]

    # And the corpus that discover() hands downstream carries the same IDs,
    # because normalising inside the builder and then losing it in discover()
    # would look identical in the unit test above.
    got = corpus_mod.discover(
        str(tmp_path), ["**/*.md"], [], prefer_git=False
    )
    assert got.builder == "filesystem walk"
    assert got.paths == ["docs/deep/claim.md"]
