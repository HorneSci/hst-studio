"""fitscreen — find the places in your system where delta-aware recompute could pay.

This is the candidate finder. It reads an exported event log — a stream of
"this state changed at this time" records — and reports whether that workload
has the *shape* that benefits from delta-aware sparse recomputation: sparse
updates, spatially clustered, over a state large enough to be worth skipping.

It is a screen, not a benchmark. It contains no runtime code, measures no
speed, phones nothing home. You run it, you read the report, you keep both.
A NOT-A-FIT verdict is a real answer: it saves you the weeks of integration
work that a mis-fit deployment costs before it fails.

LIMITATION — this screen is topology-blind. It sees a tag/tile trace, not
your operator's actual structure, so it cannot tell a dirty set that drifts
along a fixed topology (the profile that wins) from one that merely occupies
a bounded subset with no relationship to any topology. Tile-clustered share
is the closest proxy it has; it can suggest topology, never confirm it.

The screen covers the two conditions of the six-condition fit envelope that
are visible in an event log (a sparse delta, and locality by proxy). The
other four live in your code, not in a trace — run `--conditions` for the
full checklist and the kill-order questions.

Input formats (auto-detected by extension):
  .csv    columns: timestamp,tag_id[,value]   (header required, extra cols ok)
  .jsonl  one JSON object per line with keys: timestamp (s or ms epoch, or
          ISO-8601), tag_id (string or int); other keys ignored

Optional hierarchy file (--hierarchy): CSV with columns tag_id,group_id.
Without it, clustering is estimated by hashing tag_id into tiles. That
estimate can err in EITHER direction — on the shipped samples it reads low on
the clustered one and HIGH on the scattered one — so supply the real
tag->group mapping before trusting a verdict anywhere near the clustering
gate.

Usage:
  python3 -m fitscreen events.csv --batch-ms 5000 --hierarchy tags.csv
  python3 -m fitscreen --conditions
"""

import argparse
import csv
import json
import math
import sys
import zlib
from collections import Counter

from fitscreen.conditions import CALIBRATION_NOTE, NOT_MEASURED, conditions_text

__all__ = ["TH", "TILE", "analyze", "verdict", "main"]

TILE = 32  # tags per tile when no hierarchy is supplied

# Thresholds. Every one of these is a claim, and each carries its reason here.
#
# CALIBRATION — read this before trusting a verdict. These gates were
# calibrated on four synthetic dirty-set patterns whose win/loss outcome is
# known from wall-clock runs of the reference tiled kernel, where the
# comparison arm was an exact column delta: a competitor that already skips
# every clean column and pays only for the dirty ones. That is deliberately
# the hardest comparison, so this screen is the conservative one. If the
# pipeline you would be replacing recomputes the full product every cycle,
# the bar for a win sits far lower than these gates assume, and a failed
# screen here is a reason to go measure, not a reason to stop. A gate
# calibrated for one comparison must never be reused to decide a different
# one — that substitution has burned this project before, in both directions.
#
# Two gates used to live here and were REMOVED. Neither may return:
#
# 1. A batch-to-batch overlap ("pattern stability") gate, requiring a floor
#    on how much of one batch's dirty set repeats in the next. Retracted:
#    the binding fit condition is locality, not repetition. A dirty set that
#    moves every batch but stays local to a fixed structure is the WINNING
#    case, and it has low step-to-step overlap by construction — the gate was
#    systematically demoting the best-qualified workloads. It was dropped,
#    not softened: this tool is topology-blind, so it cannot honestly tell
#    drift from teleporting and must not pretend to.
#
# 2. A delta-density WIN threshold (a lower bound on "sparse enough to
#    win"). Removed: checked on the four calibration patterns, it passed all
#    four — including the one that loses — and density is *unordered* with
#    respect to the outcome there: the losing pattern sits between two
#    winning ones, so no threshold separates them, and retightening rejects
#    a winner while still admitting the loser. Clustering splits the same
#    four cleanly with a wide margin, so clustering carries the verdict.
#    Density survives as an upper bound only, which is sound for a different
#    reason: past a certain dirty fraction there is nothing left to skip.
TH = {
    "min_states": 10_000,       # below this, dense recompute is already cheap
    "dirty_frac_dead": 0.25,    # upper bound ONLY: past this, the delta is
                                # dense and there is nothing left to skip.
                                # Sparser is NOT by itself better (see above).
    "clustered_win": 0.60,      # the gate that carries the verdict: this
                                # share of dirty tags must land in repeat
                                # tiles within a batch
    "min_batch": 2,             # updates/batch where batching starts to pay
}


def _stable_tile(tag, n_tiles):
    """Deterministic tag->tile fallback when no hierarchy is supplied.

    Not Python's hash(): that is randomized per process, so the same events
    file scored differently on every run, and a trace landing near the
    clustering gate changed verdict between runs of the same command on the
    same input. A fit verdict that is not reproducible is not a verdict.
    crc32 is stable across processes, platforms and Python versions.

    Still only a *proxy* for the real tag->group mapping — it assigns tiles
    arbitrarily rather than by topology — which is why --hierarchy is
    strongly preferred and why the runtime NOTE says so.
    """
    return zlib.crc32(str(tag).encode("utf-8")) % n_tiles


def parse_ts(v):
    try:
        f = float(v)
        return f / 1000.0 if f > 1e11 else f  # ms epoch, or s epoch
    except (TypeError, ValueError):
        from datetime import datetime
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()


def read_events(path):
    if path.endswith(".jsonl"):
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                o = json.loads(line)
                yield parse_ts(o["timestamp"]), str(o["tag_id"])
    else:
        with open(path, newline="") as fh:
            rd = csv.DictReader(fh)
            cols = {c.lower(): c for c in rd.fieldnames or []}
            tcol, gcol = cols.get("timestamp"), cols.get("tag_id")
            if not tcol or not gcol:
                sys.exit("CSV needs 'timestamp' and 'tag_id' columns")
            for row in rd:
                yield parse_ts(row[tcol]), str(row[gcol])


def read_hierarchy(path):
    mapping = {}
    with open(path, newline="") as fh:
        rd = csv.DictReader(fh)
        cols = {c.lower(): c for c in rd.fieldnames or []}
        tcol, gcol = cols.get("tag_id"), cols.get("group_id")
        if not tcol or not gcol:
            sys.exit("hierarchy CSV needs 'tag_id' and 'group_id' columns")
        for row in rd:
            mapping[str(row[tcol])] = str(row[gcol])
    return mapping


def analyze(events, batch_s, tag_to_group):
    tags = set()
    batches = []          # list of dirty-tag sets per batch window
    cur, cur_end = set(), None
    t0 = t1 = None
    n = 0
    for ts, tag in events:
        n += 1
        tags.add(tag)
        t0 = ts if t0 is None else min(t0, ts)
        t1 = ts if t1 is None else max(t1, ts)
        if cur_end is None:
            cur_end = ts + batch_s
        while ts >= cur_end:
            batches.append(cur)
            cur = set()
            cur_end += batch_s
        cur.add(tag)
    if cur:
        batches.append(cur)
    if n == 0:
        sys.exit("no events parsed")

    _ntiles = max(1, math.ceil(len(tags) / TILE))
    tile_of = (lambda t: tag_to_group.get(t, t)) if tag_to_group else \
              (lambda t: _stable_tile(t, _ntiles))

    # state size = full tag universe when the hierarchy declares it
    total = max(len(tags), len(tag_to_group)) if tag_to_group else len(tags)
    dirty_fracs = [len(b) / total for b in batches if b]
    batch_sizes = [len(b) for b in batches if b]

    # clustering: fraction of dirty tags per batch sharing a tile with
    # another dirty tag in the same batch
    clustered = []
    for b in batches:
        if len(b) < 2:
            continue
        cnt = Counter(tile_of(t) for t in b)
        clustered.append(sum(c for c in cnt.values() if c > 1) / len(b))

    med = lambda xs: sorted(xs)[len(xs) // 2] if xs else 0.0
    return {
        "events": n,
        "distinct_tags": total,
        "duration_s": (t1 - t0) if t1 is not None else 0.0,
        "event_rate": n / (t1 - t0) if t1 is not None and t1 > t0 else float("nan"),
        "batches": len(batches),
        "median_batch_size": med(batch_sizes),
        "median_dirty_frac": med(dirty_fracs),
        "median_clustered_frac": med(clustered),
    }


def verdict(r):
    checks = [
        ("State size", r["distinct_tags"] >= TH["min_states"], None,
         f'{r["distinct_tags"]:,} distinct tags (need >= {TH["min_states"]:,})'),
        # Upper bound only. A sparse delta is necessary but nowhere near
        # sufficient, and this check has no lower edge on purpose — see the
        # removed-gates note above TH.
        ("Delta density", r["median_dirty_frac"] <= TH["dirty_frac_dead"], None,
         f'{r["median_dirty_frac"]:.2%} of state dirty per batch '
         f'(dead past {TH["dirty_frac_dead"]:.0%}; sparser is not by itself better)'),
        # The gate that carries the verdict — see the calibration note.
        ("Update clustering", r["median_clustered_frac"] >= TH["clustered_win"], None,
         f'{r["median_clustered_frac"]:.0%} of dirty tags tile-clustered '
         f'(gate {TH["clustered_win"]:.0%})'),
        ("Batching", r["median_batch_size"] >= TH["min_batch"], None,
         f'{r["median_batch_size"]} updates per batch window '
         f'(need >= {TH["min_batch"]})'),
    ]
    return checks


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="fitscreen",
        description=__doc__.splitlines()[0])
    ap.add_argument("events", nargs="?",
                    help="event log (.csv or .jsonl)")
    ap.add_argument("--batch-ms", type=int, default=5000,
                    help="batch window in ms — set to your emit cadence (default 5000)")
    ap.add_argument("--hierarchy", help="tag_id,group_id CSV (recommended)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--conditions", action="store_true",
                    help="print the six-condition fit screen and the "
                         "kill-order questions, then exit")
    args = ap.parse_args(argv)

    if args.conditions:
        print(conditions_text())
        return
    if not args.events:
        ap.error("an event log is required (or use --conditions)")

    mapping = read_hierarchy(args.hierarchy) if args.hierarchy else None
    r = analyze(read_events(args.events), args.batch_ms / 1000.0, mapping)
    checks = verdict(r)

    if args.json:
        r["checks"] = [{"name": n, "pass": bool(p), "detail": d}
                       for n, p, _, d in checks]
        r["calibration"] = CALIBRATION_NOTE
        r["not_measured"] = list(NOT_MEASURED)
        print(json.dumps(r, indent=2))
        return

    print("fitscreen — workload shape report")
    print("=" * 54)
    print(f'  events            {r["events"]:,}')
    print(f'  distinct tags     {r["distinct_tags"]:,}')
    print(f'  duration          {r["duration_s"]:.1f} s '
          f'({r["event_rate"]:,.0f} ev/s)')
    print(f'  batch window      {args.batch_ms} ms  ({r["batches"]} batches)')
    if not mapping:
        print("  NOTE: no --hierarchy supplied; clustering estimated by "
              "hashed tiles.")
        print("        This estimate can err in EITHER direction, not just "
              "low: on the shipped")
        print("        samples it reads low on the clustered trace but HIGH "
              "on the scattered")
        print("        one -- and reading high on a scattered trace is the "
              "direction that")
        print("        admits a non-fit. Supply --hierarchy before trusting "
              "a verdict near")
        print("        the clustering gate.")
    print("  NOTE: this screen is topology-blind — it cannot tell a dirty "
          "set that drifts along a fixed topology from one that jumps "
          "randomly. A dropped 'pattern stability' check used to penalize "
          "drifting-but-local workloads for not repeating batch-to-batch; "
          "that rule was wrong and has been removed, not replaced (no honest "
          "overlap threshold exists for a tool that cannot see topology).")
    print()
    win = True
    clustering_ok = True
    for name, p, soft_ok, detail in checks:
        mark = "PASS" if p else ("WARN" if soft_ok else "FAIL")
        win &= p
        if name == "Update clustering":
            clustering_ok = p
        print(f"  [{mark}]  {name:<18} {detail}")
    print()
    print(f"  {CALIBRATION_NOTE}")
    print()
    # A clustering failure is decisive, not merely one vote of four. It is
    # the only check with real separation behind it on the calibration set:
    # it splits the winning patterns from the losing one cleanly, where
    # density passes all of them. Routing a clustering failure to MARGINAL —
    # which an "any check passed" rule used to do — sends a lead into an
    # integration the calibration data says will fail.
    if not clustering_ok:
        win = False
    if win:
        print("Verdict: STRONG FIT — this workload has the shape where "
              "delta-aware recomputation wins. Next step: attach the delta "
              "arm beside your current path and measure BOTH on your own "
              "hardware — the spdelta package ships the harness, with a "
              "from-scratch oracle asserted on every arm.")
    elif clustering_ok and any(p for _, p, _, _ in checks):
        print("Verdict: MARGINAL — some parameters fit. Worth re-screening "
              "a different hot path or batch cadence before running a "
              "measurement.")
    else:
        print("Verdict: NOT A FIT — on this data, delta-aware recomputation "
              "would not beat a well-tuned exact-delta baseline. That is a "
              "real answer, and having it now is the cheap outcome. (If your "
              "incumbent recomputes in full each cycle, see the calibration "
              "note: the comparison this screen assumes is stricter than "
              "yours, so a measurement can still be worth it.)")


def _force_utf8_output() -> None:
    """Print the verdict even when the terminal's codec cannot hold it.

    This report uses em dashes and the multiplication sign. Under a non-UTF-8
    locale — LANG unset in a slim container, a Windows console, any Latin-1
    box — Python picks the locale's codec for stdout and the FIRST print
    raises UnicodeEncodeError: a traceback and zero bytes of verdict, on the
    tool a stranger runs first, in the environment (a bare container) it is
    most likely to be run in.

    errors="replace" rather than strict: a mangled dash in one label is
    always better than no report. The verdict is the product; the typography
    is not.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue  # a pipe or a StringIO in a test harness; nothing to do
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass  # already detached or not reconfigurable; printing still works
