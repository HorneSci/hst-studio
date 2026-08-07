"""The screen's verdict must agree with the calibration record — and the two
retracted gates must stay retracted.

The thresholds in ``fitscreen.TH`` are described as calibrated, and this file
is what keeps that description true. Ground truth is the recorded outcome of
the four calibration patterns (an exact column delta as the comparison arm):
the three tile-local patterns are wins, the scattered one is a loss. The
magnitudes behind that record are machine- and toolchain-specific and are not
restated here; what these tests assert is the CLASSIFICATION, whose sign has
held on every machine it was run on. If a future re-run ever flips a sign,
``EXPECTED`` below is what has to change, and that would be a real calibration
change rather than a toolchain difference.

Two gates were removed from the screen and neither may return, under any
name:

* a batch-to-batch overlap ("pattern stability") gate — retracted because
  locality, not repetition, is the binding condition, and the
  drifting-but-local case it penalized is the best-qualified workload;
* a delta-density WIN threshold — removed because on the calibration set it
  passed every pattern including the losing one, and density is unordered
  with respect to the outcome there (the loser sits between two winners), so
  no threshold separates them.

The stability gate is guarded three ways — the threshold dict, the verdict
surface, and behaviourally — because the name-based guards can be defeated by
a rename and a rename is exactly how such a rule has survived retraction
before. Each guard was verified against a mutant the previous one misses.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
SRC = PKG / "src"
EXAMPLES = PKG / "examples"

# pattern -> does the delta-aware arm win on this shape, per the calibration
# record (exact column delta as the comparison arm)
EXPECTED = {
    "one_tile32": True,
    "four_tiles32": True,
    "eight_tiles32": True,
    "scattered64": False,
}


def _env():
    e = dict(os.environ)
    e["PYTHONPATH"] = str(SRC) + (
        os.pathsep + e["PYTHONPATH"] if e.get("PYTHONPATH") else "")
    return e


def _fixtures(tmp):
    subprocess.run([sys.executable, "-m", "fitscreen.fixtures", "--out-dir", tmp],
                   check=True, capture_output=True, env=_env())
    return os.path.join(tmp, "hierarchy.csv")


def _probe(events, hierarchy=None, extra=()):
    cmd = [sys.executable, "-m", "fitscreen", str(events), "--json", *extra]
    if hierarchy:
        cmd[3:3] = ["--hierarchy", str(hierarchy)]
    out = subprocess.run(cmd, check=True, capture_output=True, text=True,
                         env=_env())
    return json.loads(out.stdout)


def _probe_text(events, hierarchy=None, batch_ms=None, env=None):
    cmd = [sys.executable, "-m", "fitscreen", str(events)]
    if hierarchy:
        cmd += ["--hierarchy", str(hierarchy)]
    if batch_ms is not None:
        cmd += ["--batch-ms", str(batch_ms)]
    return subprocess.run(cmd, check=True, capture_output=True, text=True,
                          env=env or _env()).stdout


def _write_events(tmp, name, rows):
    """rows: iterable of (timestamp, tag_id). Minimal timestamp,tag_id CSV."""
    path = os.path.join(tmp, name)
    with open(path, "w", newline="") as fh:
        fh.write("timestamp,tag_id\n")
        for ts, tag in rows:
            fh.write(f"{ts:.4f},{tag}\n")
    return path


def test_verdict_matches_calibration_record():
    with tempfile.TemporaryDirectory() as tmp:
        hier = _fixtures(tmp)
        for name, should_win in EXPECTED.items():
            r = _probe(os.path.join(tmp, f"{name}.csv"), hier)
            passed = {c["name"]: c["pass"] for c in r["checks"]}
            all_pass = all(passed.values())
            assert all_pass == should_win, (
                f"{name}: screen says {'FIT' if all_pass else 'NOT FIT'} but the "
                f"calibration record has it as "
                f"{'a win' if should_win else 'a loss'}; checks={passed}")


def test_density_alone_cannot_separate_wins_from_losses():
    """The reason the density win-gate was removed, asserted rather than recited.

    ``scattered64`` loses and its density sits BETWEEN two patterns that win,
    so no threshold on density can classify all three correctly. If this ever
    stops being true the calibration set changed and the gate deserves
    reconsidering.
    """
    with tempfile.TemporaryDirectory() as tmp:
        hier = _fixtures(tmp)
        d = {n: _probe(os.path.join(tmp, f"{n}.csv"), hier)["median_dirty_frac"]
             for n in EXPECTED}
        assert d["one_tile32"] < d["scattered64"] < d["four_tiles32"], (
            f"density ordering changed: {d}")
        # And the obvious "just retighten it" fix would reject a recorded
        # winner while still admitting the recorded loser.
        retightened = 0.004  # the tempting tighter bound
        assert d["eight_tiles32"] > retightened, (
            "eight_tiles32 no longer exceeds the tighter bound")
        assert d["scattered64"] < retightened, (
            "scattered64 no longer sits under the tighter bound")


def test_clustering_separates_them_with_margin():
    """Clustering carries the verdict, so it must not sit on a knife edge."""
    with tempfile.TemporaryDirectory() as tmp:
        hier = _fixtures(tmp)
        c = {n: _probe(os.path.join(tmp, f"{n}.csv"), hier)["median_clustered_frac"]
             for n in EXPECTED}
        winners = [c[n] for n, w in EXPECTED.items() if w]
        losers = [c[n] for n, w in EXPECTED.items() if not w]
        assert min(winners) - max(losers) > 0.5, (
            f"clustering separation collapsed to under half: {c}")


def test_no_density_win_threshold_remains():
    """A guard against the constant coming back by way of a well-meaning tidy-up.

    Checks the live threshold dict rather than the file text, so the guard
    cannot be defeated by moving a comment around.
    """
    import fitscreen
    assert "dirty_frac_win" not in fitscreen.TH, (
        "dirty_frac_win reintroduced as a live threshold — on the calibration "
        "set it passes every pattern including the losing one")
    assert "dirty_frac_dead" in fitscreen.TH, (
        "the density upper bound went missing; it is the half that is sound")


# Names the retracted stability rule has gone by. A list and not a single
# string, because the rule has previously survived a full retraction pass by
# living under a field name that also described something correct. Grep every
# name it goes by, not the one you remember.
_RETRACTED_STABILITY_NAMES = (
    "jaccard", "stability", "stable", "overlap", "repeat_frac",
    "pattern_stability", "dirty_set_overlap", "dirtysetoverlap",
    "step_to_step", "consecutive",
)


def test_no_pattern_stability_gate_remains():
    """The other removed gate. Sibling of ``test_no_density_win_threshold_remains``.

    A batch-to-batch overlap gate used to require a floor on how much of one
    batch's dirty set repeats in the next. Retracted: the binding fit
    condition is localized *drift*, not step-to-step repetition, and the
    winning case has low raw overlap by construction — so the gate rejected
    precisely the workloads the method is best at.
    """
    import fitscreen
    live = {k.lower() for k in fitscreen.TH}
    for key in live:
        for banned in _RETRACTED_STABILITY_NAMES:
            assert banned not in key, (
                f"threshold {key!r} looks like the retracted pattern-stability "
                f"gate (matched {banned!r}). Step-to-step overlap is NOT a fit "
                f"condition — localized drift is. A dirty set that moves every "
                f"batch but stays local is the winning case.")


def test_no_stability_check_reaches_the_verdict():
    """Stronger than the dict guard: nothing named for stability may gate a verdict.

    The dict guard only covers a constant living in ``TH``. A gate
    reintroduced as a hardcoded comparison inside ``verdict()`` would slip
    past it entirely — and an inlined constant in a function nobody greps is
    precisely how a retracted rule survives. So assert on the screen's actual
    output surface.
    """
    with tempfile.TemporaryDirectory() as tmp:
        hier = _fixtures(tmp)
        r = _probe(os.path.join(tmp, "one_tile32.csv"), hier)
        for check in r["checks"]:
            name = check["name"].lower()
            for banned in _RETRACTED_STABILITY_NAMES:
                assert banned not in name, (
                    f"verdict check {check['name']!r} matched retracted term "
                    f"{banned!r}; step-to-step stability must not gate a fit "
                    f"verdict")


def test_a_drifting_workload_is_not_penalised():
    """The behavioural guard, and the one that would survive a rename.

    Both guards above are name-based, and a rule renamed past them is how the
    rule survived retraction before. This one asserts on outcome instead:
    ``one_tile32`` is a recorded win. Relabel its tiles every batch so that
    consecutive dirty sets are disjoint — maximum churn by the retracted
    metric — while keeping each batch just as clustered. The verdict must not
    move. If it does, something is scoring step-to-step overlap again,
    whatever it calls itself.
    """
    import csv as _csv
    with tempfile.TemporaryDirectory() as tmp:
        hier = _fixtures(tmp)
        src = os.path.join(tmp, "one_tile32.csv")
        baseline = _probe(src, hier)
        assert all(c["pass"] for c in baseline["checks"]), (
            "fixture precondition failed: one_tile32 should be a FIT")

        with open(src, newline="") as fh:
            rows = list(_csv.reader(fh))
        header, body = rows[0], rows[1:]
        tag_col = header.index("tag_id") if "tag_id" in header else 0
        # Rotate the tag namespace by a whole tile each batch: same
        # clustering, zero overlap with the batch before it.
        tags = sorted({r[tag_col] for r in body})
        n = len(tags)
        index = {t: i for i, t in enumerate(tags)}
        shifted = os.path.join(tmp, "drifting.csv")
        with open(shifted, "w", newline="") as fh:
            w = _csv.writer(fh)
            w.writerow(header)
            for i, r in enumerate(body):
                r = list(r)
                r[tag_col] = tags[(index[r[tag_col]] + (i // 64) * 32) % n]
                w.writerow(r)

        drifted = _probe(shifted, hier)
        before = {c["name"]: c["pass"] for c in baseline["checks"]}
        after = {c["name"]: c["pass"] for c in drifted["checks"]}
        regressed = [k for k in before if before[k] and not after.get(k, True)]
        assert not regressed, (
            f"drifting the dirty set flipped {regressed} from pass to fail. "
            f"Drift is the WINNING case, not a disqualifier — the screen is "
            f"scoring step-to-step overlap somewhere. before={before} "
            f"after={after}")


def test_the_no_hierarchy_fallback_is_deterministic():
    """A fit verdict that changes between runs is not a verdict.

    The fallback tiling must not use Python's ``hash()``, which is randomized
    per process — the same events file then scores differently on every run,
    and a trace landing near the clustering gate changes verdict between runs
    of the same command on the same input. This path is the one a stranger
    hits first, because they rarely have a hierarchy file to hand.
    """
    src = EXAMPLES / "sample_clustered.csv"
    assert src.exists(), "the bundled sample is gone; this proves nothing"
    runs = set()
    for seed in (1, 2, 3, 4):
        out = subprocess.run(
            [sys.executable, "-m", "fitscreen", str(src), "--json"],
            check=True, capture_output=True, text=True,
            # a different hash seed per run is exactly what used to break it
            env={**_env(), "PYTHONHASHSEED": str(seed)})
        runs.add(json.loads(out.stdout)["median_clustered_frac"])
    assert len(runs) == 1, (
        f"no-hierarchy clustering varies across processes: {sorted(runs)}. "
        f"Use a stable hash (crc32), not Python's randomized hash().")


def test_the_fallback_is_not_described_as_only_pessimistic():
    """It reads HIGH on the scattered sample, which is the unsafe direction.

    The hash fallback errs in either direction: low on the clustered sample,
    HIGH on the scattered one — and reading high on a scattered trace is what
    admits a non-fit. The docs and the runtime NOTE both say "either
    direction"; this pins the sample pair that demonstrates it.
    """
    hashed = _probe(EXAMPLES / "sample_scattered.csv")["median_clustered_frac"]
    truth = _probe(EXAMPLES / "sample_scattered.csv",
                   hierarchy=EXAMPLES / "sample_hierarchy.csv")["median_clustered_frac"]
    assert hashed > truth, (
        f"the scattered sample no longer demonstrates the optimistic "
        f"direction (hashed={hashed}, truth={truth}); if this changed, "
        f"re-check the wording of the no-hierarchy NOTE, which says 'either "
        f"direction'")


# --------------------------------------------------------------------------
# The verdict surface. --json returns before verdict text is printed, so
# these run the screen for real and assert on stdout.
# --------------------------------------------------------------------------

def test_scattered_fixture_prints_not_a_fit_not_marginal():
    """A clustering-only failure must yield NOT A FIT, never MARGINAL.

    ``scattered64`` fails only Update clustering; State size, Delta density
    and Batching all pass. Under a retracted "any check passed" rule this
    reached MARGINAL — a conversation the calibration record says will fail.
    """
    with tempfile.TemporaryDirectory() as tmp:
        hier = _fixtures(tmp)
        out = _probe_text(os.path.join(tmp, "scattered64.csv"), hier)
        assert "NOT A FIT" in out, f"expected NOT A FIT verdict, got:\n{out}"
        assert "MARGINAL" not in out, (
            f"a clustering-only failure reached MARGINAL — the retracted "
            f"any-check-passed rule is back:\n{out}")
        assert "STRONG FIT" not in out


def test_clustered_fixture_prints_strong_fit():
    """A fixture that passes every check must say STRONG FIT."""
    with tempfile.TemporaryDirectory() as tmp:
        hier = _fixtures(tmp)
        out = _probe_text(os.path.join(tmp, "one_tile32.csv"), hier)
        assert "STRONG FIT" in out, f"expected STRONG FIT verdict, got:\n{out}"
        assert "NOT A FIT" not in out
        assert "MARGINAL" not in out


def test_margin_is_reachable_when_clustering_passes_but_state_size_fails():
    """MARGINAL still exists — it is gated OUT only by a clustering failure.

    Contrast with the scattered case above: here clustering passes (an
    explicit hierarchy puts every dirty tag in the same group) but the
    declared tag universe is far below ``min_states``, and only a sixth of
    it goes dirty per batch (under the dead ceiling). Exactly one check
    fails, and it is not clustering. This must reach MARGINAL, not
    NOT A FIT — confirming the decisive-clustering override is keyed on
    clustering specifically, not on "any check failed".
    """
    with tempfile.TemporaryDirectory() as tmp:
        hier_path = os.path.join(tmp, "hier.csv")
        with open(hier_path, "w") as fh:
            fh.write("tag_id,group_id\n")
            for tag in range(200):
                fh.write(f"{tag},single-tile\n")  # every tag in one group

        rows = []
        ts = 0.0
        for _ in range(6):
            for tag in range(32):
                rows.append((ts, tag))
            ts += 5.0
        path = _write_events(tmp, "tiny_but_clustered.csv", rows)
        r = _probe(path, hier_path)
        passed = {c["name"]: c["pass"] for c in r["checks"]}
        assert passed == {
            "State size": False, "Delta density": True,
            "Update clustering": True, "Batching": True,
        }, f"fixture precondition failed — expected only State size to fail: {passed}"

        out = _probe_text(path, hier_path)
        assert "MARGINAL" in out, f"expected MARGINAL verdict, got:\n{out}"
        assert "STRONG FIT" not in out
        assert "NOT A FIT" not in out


def test_state_size_check_fails_below_min_states():
    """The min_states gate, exercised on its losing side.

    A tiny log with few distinct tags, split so the dirty fraction stays
    under the dead ceiling — only State size is expected to fail.
    """
    with tempfile.TemporaryDirectory() as tmp:
        rows = []
        ts = 0.0
        for b in range(5):
            for tag in range(b * 10, b * 10 + 10):
                rows.append((ts, tag))
            ts += 5.0
        path = _write_events(tmp, "below_min_states.csv", rows)
        r = _probe(path)
        assert r["distinct_tags"] == 50
        passed = {c["name"]: c["pass"] for c in r["checks"]}
        assert passed["State size"] is False, (
            f"State size should fail with so few distinct tags: {passed}")
        assert passed["Delta density"] is True, (
            f"fixture precondition failed — expected only State size to "
            f"fail, but Delta density also failed: {passed}")


def test_batching_check_fails_below_min_batch():
    """The min_batch gate, exercised on its losing side.

    Space events more than one batch window apart so every batch holds
    exactly one event — a median batch size below the gate.
    """
    with tempfile.TemporaryDirectory() as tmp:
        rows = [(i * 2.0, f"tag{i}") for i in range(6)]
        path = _write_events(tmp, "below_min_batch.csv", rows)
        r = _probe(path, extra=("--batch-ms", "90"))
        assert r["median_batch_size"] == 1
        passed = {c["name"]: c["pass"] for c in r["checks"]}
        assert passed["Batching"] is False, (
            f"Batching should fail with a median batch size of one: {passed}")


# --------------------------------------------------------------------------
# The calibration statement and the checklist. A threshold is only honest
# with its comparison attached, so the screen must SAY which comparison its
# gates were calibrated against, on both output surfaces.
# --------------------------------------------------------------------------

def test_report_names_its_calibration_baseline():
    out = _probe_text(EXAMPLES / "sample_clustered.csv",
                      hierarchy=EXAMPLES / "sample_hierarchy.csv")
    assert "CALIBRATION" in out and "exact column-delta baseline" in out, (
        f"the text report no longer names the comparison its gates were "
        f"calibrated against:\n{out}")
    r = _probe(EXAMPLES / "sample_clustered.csv",
               hierarchy=EXAMPLES / "sample_hierarchy.csv")
    assert "exact column-delta baseline" in r.get("calibration", ""), (
        "the JSON surface lost its calibration statement")
    assert "matvec, not solve" in r.get("not_measured", []), (
        "the JSON surface no longer says which conditions it cannot measure")


def test_conditions_checklist_names_all_six():
    out = subprocess.run(
        [sys.executable, "-m", "fitscreen", "--conditions"],
        check=True, capture_output=True, text=True, env=_env()).stdout
    for phrase in (
        "FIXED, VALUED SPARSE OPERATOR",
        "DECOMPOSABLE AGGREGATE",
        "SPARSE DELTA IN THE OPERATOR'S DIMENSION",
        "LOCALIZED UPDATES",
        "IN-PROCESS CALL PATH",
        "MATVEC, NOT SOLVE",
        "time-stepping loop, or the",   # the kill-order question
        "CALIBRATION",
    ):
        assert phrase in out, f"--conditions lost {phrase!r}:\n{out}"


# --------------------------------------------------------------------------
# the stranger's terminal
# --------------------------------------------------------------------------

_LOCALES = ("en_US.UTF-8", "en_US.US-ASCII", "en_US.ISO8859-1")


def test_the_screen_prints_a_verdict_under_a_non_utf8_terminal():
    """A stranger in a bare container must get a verdict, not a traceback.

    The report uses em dashes. Under a non-UTF-8 locale Python picks the
    locale's codec for stdout and the FIRST print raises UnicodeEncodeError:
    zero bytes of verdict, a stack trace, on the tool a stranger runs against
    their own trace. ``LANG`` unset in a slim image is a normal place to run
    a screening tool, not an exotic one.

    Must be a SUBPROCESS: the stream encoding is chosen when the interpreter
    starts, so an in-process test cannot reproduce it.
    """
    sample = EXAMPLES / "sample_clustered.csv"
    assert sample.exists(), "the bundled sample is gone; this proves nothing"

    checked = 0
    for loc in _LOCALES:
        env = {**_env(), "LC_ALL": loc}
        proc = subprocess.run(
            [sys.executable, "-m", "fitscreen", str(sample)],
            capture_output=True, text=True, env=env)
        assert "UnicodeEncodeError" not in proc.stderr, (
            f"the screen crashed on output encoding under LC_ALL={loc}:\n"
            f"{proc.stderr[-500:]}")
        assert proc.returncode == 0, f"LC_ALL={loc} exit {proc.returncode}"
        assert "workload shape report" in proc.stdout, (
            f"LC_ALL={loc}: no report on stdout. A stranger sees nothing.")
        # The verdict is the product, so require the whole report, not a line.
        assert len(proc.stdout.splitlines()) >= 10, (
            f"LC_ALL={loc}: only {len(proc.stdout.splitlines())} lines of "
            f"output — the report was truncated, not printed.")
        checked += 1

    assert checked == len(_LOCALES) >= 3, (
        f"only {checked} locales exercised; an empty list would make this "
        f"pass having run nothing.")


def test_the_json_surface_also_survives_a_non_utf8_terminal():
    """--json is what a script consumes, so it must parse, not just not crash."""
    proc = subprocess.run(
        [sys.executable, "-m", "fitscreen",
         str(EXAMPLES / "sample_clustered.csv"), "--json"],
        capture_output=True, text=True,
        env={**_env(), "LC_ALL": "en_US.US-ASCII"})
    assert proc.returncode == 0, proc.stderr[-400:]
    payload = json.loads(proc.stdout)  # raises if the codec mangled it
    assert payload, "--json produced an empty document under an ASCII locale"
