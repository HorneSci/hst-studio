#!/usr/bin/env python3
"""Export the paper's result CSVs under an allowlist policy.

The paper's Artifact section commits to releasing "the complete result CSVs for
every sweep in this paper". The working copies of those files carry the internal
arm vocabulary -- profile-versioned column names, the routing gate's padding
ratio, tile-structure counts, and a free-text `router_decisions` column whose
embedded JSON names an internal arm three times per decision object. None of it
is visible in any rendered figure or table; the leak is entirely in the raw
artifact.

So the release copies are EXPORTED, not renamed in place: the working CSVs and
every harness that reads them are left alone.

Public and private are two PROFILES of this one script, driven by
`release.config.json`. There is no second codebase and no fork. `--profile
private` keeps everything and turns the gate off; it exists so the internal
superset is reproducible from the same pipeline.

    python3 tools/export_csvs.py                     # public, into data/
    python3 tools/export_csvs.py --profile private --output-dir /tmp/full
    python3 tools/export_csvs.py --check             # gate only, no write

Exit code is non-zero if any exported header would still carry a forbidden token
or a kernel-denylist token. That is the gate; it is not advisory.
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import re
import sys

from gate_env import outside_umbrella, EXIT_OUTSIDE_UMBRELLA

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def load_config(path):
    with open(path) as fh:
        return json.load(fh)


def load_denylist(path):
    """The kernel identifier denylist. Plain substring, case-insensitive, no
    word boundaries -- the matching contract is stated in the file itself and
    must not be tightened here."""
    tokens = []
    with open(path) as fh:
        for line in fh:
            line = line.rstrip("\n")
            if line.strip() and not line.startswith("#"):
                tokens.append(line.strip())
    return tokens


def denylist_hits(text, tokens):
    low = text.lower()
    return [t for t in tokens if t.lower() in low]


class Policy:
    """One profile, compiled once."""

    def __init__(self, spec):
        self.freetext = set(spec.get("drop_freetext", []))
        self.rename = [(re.compile(p), r) for p, r in spec.get("column_rename", [])]
        self.deny = [re.compile(p) for p in spec.get("column_deny", [])]
        self.values = dict(spec.get("value_rename", {}))
        self.forbid = list(spec.get("forbid", []))
        self.enforce = spec.get("enforce_denylist", True)

    def rename_column(self, name):
        out = name
        for pat, repl in self.rename:
            out = pat.sub(repl, out)
        return out

    def denied(self, name):
        return any(p.search(name) for p in self.deny)

    def rewrite_value(self, v):
        return self.values.get(v, v)


def export_one(src, dst, policy, tokens):
    """Returns (kept, dropped, renamed, violations)."""
    with open(src, newline="") as fh:
        reader = csv.reader(fh)
        try:
            header = next(reader)
        except StopIteration:
            return [], [], {}, []
        rows = list(reader)

    kept_idx, kept, dropped, renamed = [], [], [], {}
    for i, col in enumerate(header):
        if col in policy.freetext:
            dropped.append((col, "free text"))
            continue
        new = policy.rename_column(col)
        if policy.denied(new):
            dropped.append((col, "denied"))
            continue
        if new != col:
            renamed[col] = new
        kept_idx.append(i)
        kept.append(new)

    if len(set(kept)) != len(kept):
        dupes = sorted({c for c in kept if kept.count(c) > 1})
        raise SystemExit(
            f"{os.path.basename(src)}: renaming collided on {dupes}. "
            "Resolve it with an explicit rule in release.config.json rather "
            "than letting one column silently overwrite another."
        )

    out_rows = []
    for r in rows:
        out_rows.append([policy.rewrite_value(r[i]) if i < len(r) else "" for i in kept_idx])

    violations = []
    header_text = ",".join(kept)
    for tok in policy.forbid:
        if tok.lower() in header_text.lower():
            violations.append(("forbidden", tok))
    if policy.enforce:
        # header AND values: `router_arm` carried the internal arm name as data,
        # which a header-only check would never have seen.
        body = header_text + "\n" + "\n".join(
            ",".join(r) for r in out_rows[: min(len(out_rows), 5000)]
        )
        for tok in denylist_hits(body, tokens):
            violations.append(("denylist", tok))

    if dst is not None:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(kept)
            w.writerows(out_rows)

    return kept, dropped, renamed, violations


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=os.path.join(ROOT, "release.config.json"))
    ap.add_argument("--profile", default="public")
    ap.add_argument("--source-dir", default=None)
    ap.add_argument("--output-dir", default=None)
    ap.add_argument("--check", action="store_true",
                    help="run the gate and report, write nothing")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    cfgdir = os.path.dirname(os.path.abspath(args.config))
    if args.profile not in cfg["profiles"]:
        raise SystemExit(f"unknown profile {args.profile!r}; "
                         f"have {sorted(cfg['profiles'])}")
    policy = Policy(cfg["profiles"][args.profile])

    # What `data/` IS, in this copy. Both messages below used to end "the data/
    # already in this artifact is that check's output" unconditionally -- true
    # only of a copy that has one. The community tier ships none (issue #67:
    # the CSVs are measured data nobody cleared for publication), so the
    # sentence pointed at a directory the reader could see was not there and
    # made the whole message read as a bug.
    have_data = bool(glob.glob(os.path.join(cfgdir, "data", "*.csv")))
    data_note = ("the data/ already in this artifact is that export's output"
                 if have_data else
                 "this tier of the release ships no data/ at all -- the result "
                 "CSVs are withheld, so there is nothing here for this stage to "
                 "have produced")

    denylist_path = os.path.join(cfgdir, cfg["denylist_path"])
    if outside_umbrella(cfg["denylist_path"], denylist_path, ROOT):
        print(f"skipped: this stage regenerates data/ from the private source "
              f"tree and gates it against the kernel-identifier denylist "
              f"({cfg['denylist_path']}) -- both live in the umbrella repo "
              f"this artifact was staged from, not in this artifact. This is "
              f"a pre-distribution check that runs there only; {data_note}. "
              f"See tools/gate_env.py.")
        return EXIT_OUTSIDE_UMBRELLA
    tokens = load_denylist(denylist_path)

    src_dir = args.source_dir or os.path.join(cfgdir, cfg["source_dir"])
    out_dir = args.output_dir or os.path.join(cfgdir, cfg["output_dir"])

    # A profile whose gate is off must never write into the public output dir.
    #
    # Since 2026-08-07 the public-profile export in data/ is TRACKED (issue #67,
    # resolved by publishing the gated export), so `--profile private` without
    # --output-dir would overwrite the tracked public CSVs with the ungated
    # superset -- and the next `git add`/commit would publish exactly the
    # columns the policy exists to withhold. The docstring has always shown
    # private with an explicit --output-dir; this makes that the rule rather
    # than a convention.
    if not args.check and not policy.enforce:
        pub_dir = os.path.realpath(os.path.join(cfgdir, cfg["output_dir"]))
        if os.path.realpath(out_dir) == pub_dir:
            raise SystemExit(
                f"refusing: profile {args.profile!r} has the gate off and would "
                f"write into the public output dir {pub_dir}, which is tracked "
                f"public data. Pass --output-dir somewhere else, e.g. "
                f"--output-dir /tmp/full."
            )

    if args.source_dir is None and outside_umbrella(cfg["source_dir"], src_dir, ROOT):
        print(f"skipped: this stage regenerates data/ from the private source "
              f"tree ({cfg['source_dir']}), which lives outside this artifact "
              f"in the umbrella repo -- a pre-distribution check that runs "
              f"there only. Pass --source-dir to point at a real source tree "
              f"if you have one; otherwise {data_note}. See tools/gate_env.py.")
        return EXIT_OUTSIDE_UMBRELLA

    total_violations = []
    missing = []
    colmap = []
    n_files = n_dropped = 0

    for name in cfg["csv_allowlist"]:
        src = os.path.join(src_dir, name)
        if not os.path.exists(src):
            missing.append(name)
            continue
        dst = None if args.check else os.path.join(out_dir, name)
        kept, dropped, renamed, viol = export_one(src, dst, policy, tokens)
        n_files += 1
        n_dropped += len(dropped)
        for old, new in sorted(renamed.items()):
            colmap.append((name, old, new, "renamed"))
        for col, why in dropped:
            colmap.append((name, col, "", why))
        if not args.quiet:
            print(f"{name:42s} kept {len(kept):3d}  dropped {len(dropped):3d}"
                  f"  renamed {len(renamed):3d}")
        for kind, tok in viol:
            total_violations.append((name, kind, tok))

    if not args.check:
        with open(os.path.join(out_dir, "COLUMN_MAP.csv"), "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["csv", "original_column", "released_as", "action"])
            w.writerows(colmap)

    print(f"\nprofile={args.profile}  files={n_files}  columns dropped={n_dropped}")
    if missing:
        print(f"MISSING from {src_dir}: {', '.join(missing)}")
    if total_violations:
        print("\nGATE FAILED:")
        for name, kind, tok in total_violations:
            print(f"  {name}: {kind} token {tok!r} survives the export")
        return 1
    print("gate clean: no forbidden and no kernel-denylist token in any export")
    return 0 if not missing else 2


if __name__ == "__main__":
    sys.exit(main())
