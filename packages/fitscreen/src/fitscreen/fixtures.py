"""Generate the four calibration event logs whose win/loss outcome is known.

The screen's thresholds are described as calibrated, and the test suite is
what keeps that description true: each fixture here reproduces one of the
four dirty-set patterns the reference tiled kernel was actually run on, at
its real density and clustering, and the outcome of each — a win or a loss
for the delta-aware arm, with an exact column delta as the comparison — is
recorded in the tests as a boolean. If the screen's verdict ever disagrees
with that record, the tests fail rather than the thresholds drifting
silently.

The three tiled patterns win; the scattered one loses. The magnitudes are
machine- and toolchain-specific and are deliberately not restated here —
the classification is what the screen is calibrated to, and the sign is
what has held everywhere it was run.

Tag ids map to tiles as `tag // TILE`, matching the reference tiling, and
the emitted hierarchy file declares that mapping so clustering is computed
exactly rather than from the hash fallback.

    python3 -m fitscreen.fixtures --out-dir fixtures
"""

import argparse
import os
import random

N_TAGS = 60_000
TILE = 32
BATCHES = 40
BATCH_MS = 5_000

# name -> (dirty tiles per batch, scattered tags per batch)
PATTERNS = {
    "one_tile32":    dict(tiles=1, scattered=0),
    "four_tiles32":  dict(tiles=4, scattered=0),
    "eight_tiles32": dict(tiles=8, scattered=0),
    "scattered64":   dict(tiles=0, scattered=64),
}


def emit(name, spec, out_dir, seed=23):
    rng = random.Random(seed)
    n_tiles_total = N_TAGS // TILE
    rows = []
    ts = 0.0
    # Start the tiled patterns at a fixed base and let them DRIFT one tile
    # per batch. Drift is the winning motion model, and it also keeps the
    # fixture from accidentally testing a frozen set.
    base = rng.randrange(0, n_tiles_total - 16)
    for b in range(BATCHES):
        if spec["scattered"]:
            dirty = rng.sample(range(N_TAGS), spec["scattered"])
        else:
            start = (base + b) % (n_tiles_total - spec["tiles"])
            dirty = [t * TILE + k
                     for t in range(start, start + spec["tiles"])
                     for k in range(TILE)]
        # Spread the batch's events across its window.
        for i, tag in enumerate(dirty):
            rows.append((ts + (i / max(1, len(dirty))) * (BATCH_MS / 1000.0), tag))
        ts += BATCH_MS / 1000.0

    path = os.path.join(out_dir, f"{name}.csv")
    with open(path, "w") as f:
        f.write("timestamp,tag_id\n")
        for t, tag in rows:
            f.write(f"{t:.4f},{tag}\n")
    return path


def emit_hierarchy(out_dir):
    path = os.path.join(out_dir, "hierarchy.csv")
    with open(path, "w") as f:
        f.write("tag_id,group_id\n")
        for t in range(N_TAGS):
            f.write(f"{t},{t // TILE}\n")
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out-dir", default="fixtures")
    args = ap.parse_args(argv)
    os.makedirs(args.out_dir, exist_ok=True)
    for name, spec in PATTERNS.items():
        p = emit(name, spec, args.out_dir)
        print(f"wrote {p}")
    print(f"wrote {emit_hierarchy(args.out_dir)}")


if __name__ == "__main__":
    main()
