#!/usr/bin/env python3
"""Validate the ABI manifest against reality.

Three questions, each of which was answerable "no" somewhere in this estate on
2026-08-05:

  1. Does the built library export exactly what the manifest says?
     A libhstcore.so was sitting at HSTCORE_1.3 while the version map and the
     Python binding both said 1.4. Nothing checked, so nothing complained, and
     a binding written against 1.4 would have failed at load with an error
     nobody enjoys debugging.

  2. Does the version map agree with the manifest?
     The map is what the linker reads. If it and the manifest disagree, the
     manifest is fiction.

  3. Does every binding bind every symbol?
     A binding missing a symbol is not a partial binding; it is a binding whose
     users discover the gap at runtime, in production, on the one call path
     nobody exercised.

  4. Does the library's OWN version string agree with the ABI node?
     A library can pass check 1 (right symbols) and still tell its caller the
     wrong version. That happened on 2026-08-06: hst_version() returned
     "hstcore 1.3.0" while the exports matched HSTCORE_1.4 exactly, and this
     validator passed clean, because nothing here had ever read the string
     hst_version() actually returns -- only what the symbol table exports.

Fails closed on all four. stdlib only.

    python3 validate.py                     # validate everything it can find
    python3 validate.py --library <path>    # check a specific artifact
    python3 validate.py --self-test
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
MANIFEST = HERE / "abi.json"

#: Optional, and deliberately not part of any distribution of this package.
#:
#: This file ships. The build tree it is developed against does not, and naming
#: that tree here would put a private repository's internal layout into every
#: download and tell the reader to `cd` somewhere they do not have. So the
#: development roots live in a sibling JSON file that the release build's
#: explicit staging list does not carry, and their absence is the download
#: case rather than an error:
#:
#:     {"roots": ["<relative-to-repo-root>", ...]}
#:
#: In a download the library sits at `bin/` relative to this package's parent,
#: which is `_library_roots()`'s first and, there, only answer.
DEV_ROOTS = HERE / "dev-roots.json"


def _dev_roots() -> list[Path]:
    if not DEV_ROOTS.is_file():
        return []
    doc = json.loads(DEV_ROOTS.read_text(encoding="utf8"))
    return [REPO / r for r in doc.get("roots", [])]


def _library_roots() -> list[Path]:
    """Where a built library might be, download layout first."""
    return [REPO / "bin", *_dev_roots()]


class Failure(Exception):
    pass


def load_manifest(path: Path = MANIFEST) -> dict:
    doc = json.loads(path.read_text(encoding="utf8"))
    fns = doc["functions"]
    if not fns:
        raise Failure("manifest declares zero functions; every check would be vacuous")
    if len(fns) != doc["symbolCount"]:
        raise Failure(
            f"manifest is internally inconsistent: symbolCount={doc['symbolCount']} "
            f"but {len(fns)} functions are listed"
        )
    return doc


def symbols(doc: dict) -> set[str]:
    return {f["name"] for f in doc["functions"]}


# ---------------------------------------------------------------------------
# 1. the built artifact
# ---------------------------------------------------------------------------

def exported_symbols(lib: Path) -> tuple[set[str], bool]:
    """Exported text symbols. Returns (symbols, exact).

    `exact` is False when we had to fall back to scanning the binary for symbol
    NAMES rather than reading its symbol table -- which happens whenever the
    object format is foreign to the host toolchain, e.g. inspecting a Linux ELF
    from macOS, which is the normal case on this laptop.

    The fallback is deliberately reported as inexact rather than silently
    treated as equivalent: it cannot distinguish an exported symbol from a
    referenced one, so it can confirm presence but not absence-of-extras. A
    weaker check that says so is useful; one that pretends to be strong is not.
    """
    for args in (["nm", "-gU", str(lib)], ["nm", "-gD", str(lib)], ["nm", "-g", str(lib)]):
        try:
            out = subprocess.run(args, capture_output=True, text=True, check=False).stdout
        except FileNotFoundError:
            raise Failure("nm not found; cannot inspect a built library")
        found = {m.group(1) for line in out.splitlines()
                 if (m := re.match(r"^[0-9a-fA-F]*\s*[TtWw]\s+_?(hst_\w+)$", line.strip()))}
        if found:
            return found, True

    # Foreign object format. Scan for the names themselves.
    blob = lib.read_bytes()
    found = {m.decode() for m in re.findall(rb"hst_[a-z_]+", blob)}
    if not found:
        raise Failure(
            f"no hst_* symbols found in {lib} by symbol table or by name scan.\n"
            f"  Either it is not an HST library or it is corrupt."
        )
    return found, False


def check_library(lib: Path, doc: dict) -> list[str]:
    notes = []
    want = symbols(doc)
    got, exact = exported_symbols(lib)

    missing = sorted(want - got)
    if missing:
        raise Failure(
            f"{lib.name} does not export {len(missing)} manifest symbol(s): {missing}\n"
            f"  Either the library is a stale build or the manifest is ahead of it."
        )

    if exact:
        extra = sorted(got - want)
        if extra:
            raise Failure(
                f"{lib.name} exports {len(extra)} symbol(s) not in the manifest: {extra}\n"
                f"  An undocumented export is an ABI commitment nobody agreed to."
            )
        notes.append(f"{lib.name}: all {len(want)} symbols exported, none extra")
    else:
        notes.append(
            f"{lib.name}: all {len(want)} symbols found by NAME SCAN (foreign object "
            f"format on this host) — presence confirmed, extras NOT checked"
        )

    # Version node. Linux carries it in the dynamic symbol table; macOS uses an
    # export list with no node, so its absence there is not a failure.
    nodes = set(re.findall(r"HSTCORE_\d+\.\d+", subprocess.run(
        ["nm", "-gD", str(lib)], capture_output=True, text=True, check=False).stdout))
    if nodes:
        want_node = doc["abiNode"]
        if nodes != {want_node}:
            raise Failure(
                f"{lib.name} exports version node(s) {sorted(nodes)}, manifest says {want_node}.\n"
                f"  This is the STALE BUILD case: rebuild the library from its own\n"
                f"  build tree rather than editing the manifest, unless you actually\n"
                f"  intend an ABI change."
            )
        notes.append(f"{lib.name}: version node {want_node}")
    else:
        notes.append(f"{lib.name}: no version node (expected on macOS export lists)")

    notes.append(check_version_string(lib, doc))
    return notes


# ---------------------------------------------------------------------------
# 4. the library's own version string
# ---------------------------------------------------------------------------

def check_version_string(lib: Path, doc: dict) -> str:
    """hst_version() returns "hstcore X.Y.Z". Its major.minor must agree with
    doc["abiNode"] ("HSTCORE_X.Y").

    A byte scan, not a load: hst_open()/hst_version() cannot be called from
    here, because the whole point of this validator is that it runs on the
    laptop everyone edits from, and a Linux .so cannot be loaded on macOS.
    A `strings`-style scan for the literal works cross-arch and needs nothing
    the rest of this file does not already use.

    This is the exact check that was missing on 2026-08-06: the ABI-node
    check above passed (HSTCORE_1.4, correct exports) while hst_version()
    still returned "hstcore 1.3.0", because nothing had ever read that string.
    """
    blob = lib.read_bytes()
    m = re.search(rb"hstcore (\d+)\.(\d+)\.(\d+)", blob)
    if not m:
        raise Failure(
            f"{lib.name}: no \"hstcore X.Y.Z\" version string found in the binary.\n"
            f"  hst_version() is supposed to return one; either the build dropped "
            f"the string or this is not an HST library."
        )
    found_major, found_minor, found_patch = (g.decode() for g in m.groups())
    found = f"{found_major}.{found_minor}.{found_patch}"

    want_node = doc["abiNode"]
    node_m = re.match(r"HSTCORE_(\d+)\.(\d+)", want_node)
    if not node_m:
        raise Failure(f"abiNode {want_node!r} is not of the form HSTCORE_X.Y")
    want_major, want_minor = node_m.groups()

    if (found_major, found_minor) != (want_major, want_minor):
        raise Failure(
            f"{lib.name} reports version string \"hstcore {found}\", but the ABI "
            f"node is {want_node}.\n"
            f"  hst_version() says {found_major}.{found_minor}.x; the manifest says "
            f"{want_node} -- these must agree on major.minor. This is exactly how "
            f"the library shipped saying \"1.3.0\" while its ABI node was HSTCORE_1.4."
        )
    return f"{lib.name}: version string \"hstcore {found}\" agrees with {want_node}"


# ---------------------------------------------------------------------------
# 2. the version map
# ---------------------------------------------------------------------------

def check_version_map(doc: dict) -> list[str]:
    # The map is a linker input and lives with the sources, so it exists only in
    # a development tree. In a download there is nothing to check and that is
    # the honest answer rather than a failure.
    mp = next((r / doc["versionMap"] for r in _dev_roots()
               if (r / doc["versionMap"]).exists()), None)
    if mp is None:
        return [f"version map absent ({doc['versionMap']}) — no build tree here, skipped"]
    text = mp.read_text(encoding="utf8")

    node = re.match(r"\s*(HSTCORE_\d+\.\d+)\s*\{", text)
    if not node:
        raise Failure(f"{mp} does not open with a HSTCORE_x.y node")
    if node.group(1) != doc["abiNode"]:
        raise Failure(
            f"{mp} declares {node.group(1)}, manifest says {doc['abiNode']}.\n"
            f"  The map is what the linker reads; if they disagree the manifest is fiction."
        )

    listed = set(re.findall(r"^\s*(hst_\w+);", text, re.M))
    want = symbols(doc)
    if listed != want:
        raise Failure(
            f"{mp} and the manifest list different symbols.\n"
            f"  only in map:      {sorted(listed - want)}\n"
            f"  only in manifest: {sorted(want - listed)}"
        )
    return [f"version map: {doc['abiNode']}, {len(listed)} symbols, agrees with manifest"]


# ---------------------------------------------------------------------------
# 3. the bindings
# ---------------------------------------------------------------------------

BINDINGS = {
    "python":  ("hstcore-py",     ["**/*.py"]),
    "rust":    ("hstcore-rs",     ["**/*.rs"]),
    "java":    ("hstcore-java",   ["**/*.java"]),
    "go":      ("hstcore-go",     ["**/*.go"]),
    "dotnet":  ("hstcore-dotnet", ["**/*.cs"]),
    "node":    ("hstcore-node",   ["**/*.mjs", "**/*.js", "**/*.ts"]),
}


def check_bindings(doc: dict) -> list[str]:
    notes = []
    want = symbols(doc)
    root = HERE.parent  # oss/

    for lang, (dirname, globs) in sorted(BINDINGS.items()):
        d = root / dirname
        if not d.is_dir():
            notes.append(f"{lang:8s} — absent, skipped")
            continue

        text = []
        for g in globs:
            for f in d.glob(g):
                if any(part in {"target", "node_modules", ".venv", "build", "obj", "bin",
                                "__pycache__"} for part in f.parts):
                    continue
                try:
                    text.append(f.read_text(encoding="utf8", errors="replace"))
                except OSError:
                    pass
        if not text:
            notes.append(f"{lang:8s} — directory present but no source files matched, skipped")
            continue
        blob = "\n".join(text)

        missing = sorted(s for s in want if s not in blob)
        if missing:
            raise Failure(
                f"{lang} binding ({dirname}) does not reference {len(missing)} symbol(s):\n"
                f"    {missing}\n"
                f"  A partially-bound library fails at runtime on the one path nobody tested."
            )
        notes.append(f"{lang:8s} — all {len(want)} symbols referenced")
    return notes


# ---------------------------------------------------------------------------

def find_libraries() -> list[Path]:
    return [p for base in _library_roots()
            for p in (base / n for n in
                      ("libhstcore.so", "libhstcore.dylib", "hstcore.dll"))
            if p.exists()]


def self_test() -> int:
    """A validator nobody has watched fail is a validator nobody knows works."""
    import tempfile
    ok = True

    doc = load_manifest()

    # (a) a manifest whose count disagrees with its list must fail
    bad = json.loads(MANIFEST.read_text(encoding="utf8"))
    bad["symbolCount"] = 99
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump(bad, fh)
        p = Path(fh.name)
    try:
        load_manifest(p)
        print("  FAIL  an inconsistent symbolCount was accepted")
        ok = False
    except Failure:
        print("  ok    inconsistent symbolCount is rejected")
    finally:
        p.unlink()

    # (b) a manifest with zero functions must fail rather than pass vacuously
    empty = {"symbolCount": 0, "functions": [], "abiNode": "HSTCORE_1.4", "versionMap": "x"}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump(empty, fh)
        p = Path(fh.name)
    try:
        load_manifest(p)
        print("  FAIL  a zero-function manifest was accepted")
        ok = False
    except Failure:
        print("  ok    zero-function manifest fails rather than passing vacuously")
    finally:
        p.unlink()

    # (c) a library missing a symbol must fail
    with tempfile.TemporaryDirectory() as td:
        fake = Path(td) / "libfake.so"
        fake.write_bytes(b"\x00")
        try:
            exported_symbols(fake)
            print("  FAIL  a library with no hst_* symbols was accepted")
            ok = False
        except Failure:
            print("  ok    a library exporting no hst_* symbols is rejected")

    # (d) a library whose version string disagrees with the ABI node must
    # fail. Plants exactly the 2026-08-06 incident: exports/node fine, the
    # STRING says the wrong release.
    with tempfile.TemporaryDirectory() as td:
        fake = Path(td) / "libmismatch.so"
        fake.write_bytes(b"junk before hstcore 1.3.0 junk after")
        try:
            check_version_string(fake, doc)  # doc's abiNode is HSTCORE_1.4
            print("  FAIL  a version string (\"1.3.0\") mismatched with the ABI "
                  f"node ({doc['abiNode']}) was accepted")
            ok = False
        except Failure:
            print("  ok    a version-string/ABI-node mismatch is rejected")

    # (d-2) and a library whose version string DOES agree must pass, so (d)
    # is a real discriminator and not a check that fails on any input.
    with tempfile.TemporaryDirectory() as td:
        fake = Path(td) / "libmatch.so"
        fake.write_bytes(b"junk before hstcore 1.4.0 junk after")
        try:
            check_version_string(fake, doc)
            print("  ok    a version string agreeing with the ABI node is accepted")
        except Failure as e:
            print(f"  FAIL  a matching version string (1.4.0 vs {doc['abiNode']}) "
                  f"was rejected: {e}")
            ok = False

    print()
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--library", type=Path, action="append", default=[])
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        print("\n  validate.py self-test\n")
        return self_test()

    try:
        doc = load_manifest()
        print(f"\n  manifest: {doc['abiNode']}, {doc['symbolCount']} symbols\n")

        notes = check_version_map(doc)

        libs = args.library or find_libraries()
        if not libs:
            notes.append("no built library found — nothing to check against, skipped")
        for lib in libs:
            notes += check_library(lib, doc)

        notes += check_bindings(doc)
    except Failure as e:
        print(f"\n  ABI VALIDATION FAILED\n\n  {e}\n", file=sys.stderr)
        return 1

    for n in notes:
        print(f"  {'--' if 'skipped' in n else 'ok'}    {n}")
    print("\n  ABI consistent\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
