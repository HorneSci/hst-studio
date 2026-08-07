"""Fetch the SuiteSparse operators the golden-vector cases are built on.

Adapted from an internal fetch helper; the addition here is that every download
is hashed, so a manifest can pin the exact bytes a case was generated from and a
stranger can prove they are looking at the same operator.

We deliberately do NOT redistribute matrix bytes. A case manifest carries the
group, name, URL and sha256; this script turns that provenance back into a local
file. If the archive ever changes upstream, the sha256 mismatch is loud.

Usage:
    python3 fetch_matrices.py                      # all, into ./matrices
    python3 fetch_matrices.py --out DIR name ...   # a subset, elsewhere
    python3 fetch_matrices.py --print-sha256       # emit manifest-ready records

Public domain (CC0 1.0). No warranty.
"""

import argparse
import hashlib
import io
import json
import os
import sys
import tarfile
import urllib.request

BASE = "https://suitesparse-collection-website.herokuapp.com/MM"

# name: (group, file, why this operator is in the set)
MATRICES = {
    "case9":     ("QY",   "case9",     "power flow, tiny -- the smallest honest operator"),
    "bcspwr09":  ("HB",   "bcspwr09",  "power network topology, purely structural"),
    "bcspwr10":  ("HB",   "bcspwr10",  "power network topology, larger sibling"),
    "add32":     ("Hamm", "add32",     "circuit simulation, very sparse"),
    "rajat03":   ("Rajat", "rajat03",  "circuit simulation, irregular structure"),
    "nasa2910":  ("Nasa", "nasa2910",  "structural FEM, small dense blocks"),
    "memplus":   ("Hamm", "memplus",   "circuit simulation, different structure"),
}


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(name, out):
    group, fname, why = MATRICES[name]
    dest = os.path.join(out, f"{fname}.mtx")
    url = f"{BASE}/{group}/{fname}.tar.gz"
    if not os.path.exists(dest):
        print(f"get   {name:12} {url}", file=sys.stderr)
        with urllib.request.urlopen(url, timeout=180) as r:
            blob = r.read()
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tf:
            member = next(m for m in tf.getmembers() if m.name.endswith(".mtx"))
            with tf.extractfile(member) as src, open(dest, "wb") as dst:
                dst.write(src.read())
    return {
        "source": "suitesparse",
        "group": group,
        "name": fname,
        "url": url,
        "mtx_sha256": sha256_file(dest),
        "local_path": dest,
        "note": why,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "matrices"))
    ap.add_argument("--print-sha256", action="store_true")
    ap.add_argument("names", nargs="*")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    recs = {}
    for n in (a.names or list(MATRICES)):
        try:
            recs[n] = fetch(n, a.out)
            print(f"ok    {n:12} {recs[n]['mtx_sha256'][:16]}...  ({recs[n]['note']})")
        except Exception as e:
            print(f"FAIL  {n}: {e}", file=sys.stderr)
    if a.print_sha256:
        json.dump(recs, sys.stdout, indent=2, sort_keys=True)
        print()


if __name__ == "__main__":
    main()
