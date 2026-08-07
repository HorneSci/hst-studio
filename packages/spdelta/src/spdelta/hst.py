"""The HST arm: attach the runtime to your own operator, and measure it.

Everything else in `spdelta` runs on numpy and scipy alone. This module is the
one place that touches the HST runtime, and it is optional by construction --
importing `spdelta` does not import this, and nothing here is needed to run the
ladder. If the runtime is not present, :func:`locate` says exactly what is
missing and the rest of the package is unaffected.

## What it does

Three pieces have to line up before HST can run on a matrix you brought:

1. **Compile.** `hst_open` takes a compiled artifact, and there is no compile
   entry point among the thirteen exported functions -- so a matrix in memory
   cannot become an operator without `bin/hst-compile`. It reads plain COO JSON
   (n, m, rows, cols, values) and writes the artifact. Nothing about the
   internal layout crosses that boundary in either direction.
2. **Open.** `hstcore-py` opens the artifact. The community library has the
   licence check compiled out (Apache-2.0, unmetered), so `hst_open` succeeds
   with an empty token -- there is nothing to supply and nothing to expire.
   (This said "the community tree bundles a capped, expiring token" until
   2026-08-07, describing a build that was retired on 2026-08-06.) A metered
   build does take a token, and :func:`locate` still finds one -- `HST_LICENSE`
   or an `eval.license` file -- and passes it through when it exists.
3. **Step.** `HstArm` satisfies `spdelta`'s :class:`~spdelta.baselines.Arm`
   protocol, so it drops into :func:`~spdelta.harness.sweep` beside
   `full_matvec`, `masked_row_scan` and `column_delta_csc` and is asserted
   against the same from-scratch oracle after every repeat. There is no path
   here that skips that assertion.

## The tax this arm pays, stated because it points the wrong way for us

`ctx.apply(cols, vals, out=y)` has the library write the **whole** dense output
into `y` -- N x batch doubles every step. `column_delta_csc` writes only the
rows its dirty columns touch. So on a small dirty set the HST arm is charged for
a write the arm it is being compared against does not make, and the measured
ratio **understates** HST. The size of that effect is not guessed at here and
not quoted here either -- a ratio without its baseline, motion model, churn rate,
toolchain and control is not a claim, and this docstring is not the place that
carries those. It has been measured elsewhere and it is large enough to matter.

It is left in rather than optimised away because removing it would mean the two
arms no longer produce their answer the same way, and an arm that is fast
because it wrote less is the failure this whole package exists to prevent. If
you need the kernel-only figure, that is a different measurement and it should
say so on the label.

## Use

    from spdelta import hst

    rt = hst.locate()                       # or hst.locate(lib=..., licence=...)
    rows = sd.sweep(sd.ladder() + [rt.arm()], cells, reference=sd.reference())

or, for the whole thing in one call:

    print(hst.before_after(a))
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Sequence

import numpy as np
import scipy.sparse as sp

__all__ = ["HstRuntime", "HstArm", "HstUnavailable", "locate", "before_after"]


class HstUnavailable(RuntimeError):
    """The runtime is not usable here, and this says which of the three parts
    is missing. Never raised for a reason the caller cannot act on."""


def _search_roots() -> list[Path]:
    """Where a bundled runtime plausibly lives, nearest first.

    An installed `spdelta` sits at `packages/spdelta/src/spdelta/hst.py` inside
    a Studio tree whose `bin/` is four levels up; a source checkout sits
    somewhere else entirely. Both are tried, and neither is required -- the
    environment variables win.
    """
    here = Path(__file__).resolve()
    roots = [p for p in here.parents[:6]]
    roots.append(Path.cwd())
    return roots


def _platform_suffix() -> str:
    """`<uname -s>-<uname -m>`, matching how the tools are staged.

    hst-compile and hst_compare have the same filename on every OS, unlike the
    library, so one tree carries a build per platform and this picks the right
    one. A bare `hst-compile` is still accepted first, for a local build.
    """
    import platform
    system = {"Darwin": "darwin", "Linux": "linux", "Windows": "windows"}.get(
        platform.system(), platform.system().lower())
    machine = {"x86_64": "x86_64", "AMD64": "x86_64", "arm64": "arm64",
               "aarch64": "arm64"}.get(platform.machine(), platform.machine())
    return f"{system}-{machine}"


def _find(name: str, env: str, explicit: Optional[str]) -> Optional[Path]:
    if explicit:
        p = Path(explicit).expanduser()
        return p if p.exists() else None
    from_env = os.environ.get(env)
    if from_env:
        p = Path(from_env).expanduser()
        return p if p.exists() else None
    names = [name, f"{name}.{_platform_suffix()}"]
    for root in _search_roots():
        for n in names:
            for candidate in (root / "bin" / n, root / n):
                if candidate.exists():
                    return candidate
    for n in names:
        on_path = shutil.which(n)
        if on_path:
            return Path(on_path)
    return None


def _library_name() -> str:
    import sys
    if sys.platform == "darwin":
        return "libhstcore.dylib"
    if sys.platform.startswith("win"):
        return "hstcore.dll"
    return "libhstcore.so"


@dataclass(frozen=True)
class HstRuntime:
    """A located runtime: the compiler, the library, and a token."""

    compiler: Path
    library: Path
    licence: str  # "" for the community library, which has no check to satisfy
    tile_size: int = 32

    def arm(self, *, name: str = "hst", tile_size: Optional[int] = None) -> "HstArm":
        return HstArm(self, name=name, tile_size=tile_size or self.tile_size)


def locate(
    *,
    compiler: Optional[str] = None,
    lib: Optional[str] = None,
    licence: Optional[str] = None,
    tile_size: int = 32,
) -> HstRuntime:
    """Find the runtime, or explain precisely what is absent.

    Honours `HST_COMPILE`, `HST_LIB` and `HST_LICENSE`, then looks for a `bin/`
    beside the installed package or in the working directory.
    """
    try:
        import hstcore  # noqa: F401
    except ModuleNotFoundError as exc:
        raise HstUnavailable(
            "the hstcore binding is not installed. In a Studio tree:\n"
            "    pip install ./packages/hstcore-py"
        ) from exc

    comp = _find("hst-compile", "HST_COMPILE", compiler)
    if comp is None:
        raise HstUnavailable(
            "hst-compile not found. It ships in bin/ of a Studio community tree\n"
            "(the runtime is in the standard download); point at it with\n"
            "HST_COMPILE=/path/to/hst-compile. Without it a matrix cannot become\n"
            "an operator: the ABI opens artifacts, and nothing in the thirteen\n"
            "exported functions compiles one."
        )

    library = _find(_library_name(), "HST_LIB", lib)
    if library is None:
        raise HstUnavailable(
            f"{_library_name()} not found. It ships in bin/ of a Studio community\n"
            "tree (the runtime is in the standard download); point at it with\n"
            "HST_LIB=/path/to/library. If a binding loads it and reports missing\n"
            "symbols, run packages/hstcore-abi/validate.py against it -- that is\n"
            "a stale build, not a different ABI."
        )

    token = licence or os.environ.get("HST_LICENSE")
    if token and Path(token).expanduser().exists():
        token = Path(token).expanduser().read_text(encoding="utf-8").strip()
    if not token:
        for root in _search_roots():
            for candidate in (root / "eval.license", root / "bin" / "eval.license"):
                if candidate.exists():
                    token = candidate.read_text(encoding="utf-8").strip()
                    break
            if token:
                break
    # No token is the NORMAL case. The community library is unmetered and
    # Apache-2.0: it opens on an empty string. A token is only meaningful
    # against a metered build, so this passes whatever it found -- including
    # nothing -- and lets the library be the thing that decides. Demanding one
    # here would reintroduce, in Python, exactly the gate the free tier does
    # not have.
    token = token or ""

    return HstRuntime(compiler=comp, library=library, licence=token, tile_size=tile_size)


def compile_operator(rt: HstRuntime, a: sp.spmatrix, out: Path, *, tile_size: int) -> dict:
    """COO JSON in, artifact out. Returns hst-compile's summary line."""
    coo = a.tocoo()
    doc = {
        "operator": {
            "n": int(coo.shape[0]),
            "m": int(coo.shape[1]),
            "rows": coo.row.astype(int).tolist(),
            "cols": coo.col.astype(int).tolist(),
            "values": coo.data.astype(float).tolist(),
        },
        "compile_options": {"tile_size": int(tile_size)},
    }
    src = out.with_suffix(".json")
    src.write_text(json.dumps(doc), encoding="utf-8")
    proc = subprocess.run(
        [str(rt.compiler), str(src), str(out)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise HstUnavailable(f"hst-compile failed:\n{proc.stdout}{proc.stderr}")
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {}


class HstArm:
    """The HST runtime as a `spdelta` arm.

    Batch width is discovered from the first delta, exactly as the pure-Python
    arms discover it, so the session is opened lazily -- `hst_open_batched`
    fixes the width for the life of a context and the workload is what decides
    it, not this class.
    """

    delta_kind = "compact"
    carries_state = True

    def __init__(self, runtime: HstRuntime, *, name: str = "hst", tile_size: int = 32) -> None:
        self.runtime = runtime
        self.name = name
        self.tile_size = tile_size
        self.steps = 0
        self.recompiles = 0
        self._tmp: Optional[tempfile.TemporaryDirectory] = None
        self._artifact: Optional[Path] = None
        self._ctx: Any = None
        self._batch: Optional[int] = None
        self._summary: dict = {}

    def stats(self) -> dict:
        """Per-run counters, same keys as the pure-Python arms plus the two
        that only mean something here."""
        return {
            "steps": self.steps,
            "recompiles": self.recompiles,
            "hst_tile_size": self.tile_size,
            "hst_nnz": self._summary.get("nnz"),
            "hst_compile_ms": self._summary.get("compile_ms"),
        }

    # -- lifecycle ---------------------------------------------------------

    def prepare(self, a: sp.spmatrix, dirty: np.ndarray) -> None:
        """Compile this operator and drop any open session.

        The compile is NOT timed by `sweep`, and that is correct: it is the
        build cost, paid once per operator, and this package prices build and
        execution separately rather than folding one into the other.
        """
        self._close()
        self._tmp = tempfile.TemporaryDirectory(prefix="spdelta-hst-")
        self._artifact = Path(self._tmp.name) / "operator.bin"
        self._summary = compile_operator(
            self.runtime, a, self._artifact, tile_size=self.tile_size)
        self.recompiles += 1
        self.steps = 0
        self._batch = None

    def step(self, d: Any, y: np.ndarray) -> None:
        if self._ctx is None:
            self._open(int(y.shape[1]), y)
        vals = np.ascontiguousarray(d.vals, dtype=np.float64)
        cols = np.ascontiguousarray(d.cols, dtype=np.int32)
        # out=y: the library writes the dense result straight into the caller's
        # buffer. See the module docstring on why this tax is left in.
        self._ctx.apply(cols, vals, out=y)
        self.steps += 1

    def _open(self, batch: int, y0: np.ndarray) -> None:
        import hstcore

        if self._artifact is None:
            raise HstUnavailable("prepare() must run before step()")
        self._ctx = hstcore.HSTContext(
            str(self._artifact), self.runtime.licence,
            batch=batch, lib_path=str(self.runtime.library),
        )
        self._batch = batch
        # Start from the same y every other arm starts from. Without this the
        # arm is computing a correct delta onto the wrong state and the oracle
        # catches it -- which is the point, but it should never get that far.
        self._ctx.set_state(np.ascontiguousarray(y0, dtype=np.float64).reshape(-1))

    def _close(self) -> None:
        if self._ctx is not None:
            self._ctx.close()
            self._ctx = None
        if self._tmp is not None:
            self._tmp.cleanup()
            self._tmp = None
        self._artifact = None

    def __del__(self) -> None:  # pragma: no cover - best effort
        try:
            self._close()
        except Exception:
            pass


def before_after(
    a: sp.spmatrix,
    *,
    rhos: Sequence[float] = (0.0, 0.01, 0.25),
    seeds: Sequence[int] = (17, 18),
    name: str = "your_operator",
    runtime: Optional[HstRuntime] = None,
    spread: int = 3,
):
    """The whole thing in one call: ladder + HST arm, on your operator.

    Returns `(rows, claim)` -- every measured row, and a
    :class:`~spdelta.claim.Claim` whose headline ratio is **HST against
    `column_delta_csc`**, not against full recompute.

    That choice is the difference between a number you can publish and one you
    will have to withdraw. Against a full recompute the same runs read an order
    of magnitude better; against a competent column delta they read what a
    reader who already does a delta would actually get. Both are in `rows`.
    """
    from . import baselines as _b
    from . import harness as _h
    from . import motion as _m

    rt = runtime or locate()
    arms = _b.ladder() + [rt.arm()]
    cells = _h.standard_cells(
        [(name, a)],
        [
            lambda n, m, rho: _m.frozen(),
            lambda n, m, rho: _m.drift(_m.Topology.line(m.shape[1], spread), rho),
            lambda n, m, rho: _m.jump_nnz_matched(m, rho),
        ],
        rhos=tuple(r for r in rhos if r > 0) or (0.01,),
        seeds=tuple(seeds),
    )
    rows = _h.sweep(arms, cells, reference=_b.reference())
    return rows
