"""Test fixtures, including the recording ABI stub.

Two kinds of test live here:

* tests that need no library at all — argument checking, the state-view guard,
  the shadow/production separation, the return-code map. Those are the majority.
* tests that need *a* library exporting the thirteen ABI symbols, to prove the
  binding calls the right one with the right pointers. Those use the stub in
  ``tests/stub/hst_stub.c``, which computes nothing.

No test in this repository needs, or can substitute for, the licensed
``libhstcore``. What that leaves untested is listed in ``README.md``.
"""

from __future__ import annotations

import ctypes
import os
import pathlib
import shutil
import subprocess
import sys

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import hstcore  # noqa: E402
from hstcore import _ffi  # noqa: E402

STUB_SRC = pathlib.Path(__file__).resolve().parent / "stub" / "hst_stub.c"

# Slot ids, mirroring the enum in hst_stub.c.
OPEN, OPEN_BATCHED, APPLY, SHADOW, BATCH, STATE, SET_STATE, RECOMPUTE, CLOSE = range(9)


def _suffix() -> str:
    if sys.platform == "darwin":
        return ".dylib"
    if sys.platform.startswith("win"):
        return ".dll"
    return ".so"


class Stub:
    """Handle on the compiled stub: counters, recorded pointers, forced codes."""

    def __init__(self, dll: ctypes.CDLL) -> None:
        self.dll = dll
        dll.hst_stub_count.argtypes = [ctypes.c_int]
        dll.hst_stub_count.restype = ctypes.c_long
        dll.hst_stub_set_rc.argtypes = [ctypes.c_int, ctypes.c_int]
        dll.hst_stub_set_dims.argtypes = [ctypes.c_int32, ctypes.c_int32]
        dll.hst_stub_set_batch_report.argtypes = [ctypes.c_int32]
        dll.hst_stub_set_open_fail.argtypes = [ctypes.c_int, ctypes.c_char_p]
        for name in ("hst_stub_last_cols", "hst_stub_last_vals", "hst_stub_last_y_out"):
            getattr(dll, name).restype = ctypes.c_uint64
        dll.hst_stub_last_n.restype = ctypes.c_int32
        dll.hst_stub_last_set_len.restype = ctypes.c_int32
        dll.hst_stub_reset()

    def count(self, which: int) -> int:
        return int(self.dll.hst_stub_count(which))

    def force(self, which: int, rc: int) -> None:
        self.dll.hst_stub_set_rc(which, rc)

    def dims(self, n: int, m: int) -> None:
        self.dll.hst_stub_set_dims(n, m)

    def report_batch(self, b: int) -> None:
        self.dll.hst_stub_set_batch_report(b)

    def fail_open(self, why: bytes | None) -> None:
        self.dll.hst_stub_set_open_fail(1 if why is not None else 0, why)

    @property
    def last_cols(self) -> int:
        return int(self.dll.hst_stub_last_cols())

    @property
    def last_vals(self) -> int:
        return int(self.dll.hst_stub_last_vals())

    @property
    def last_y_out(self) -> int:
        return int(self.dll.hst_stub_last_y_out())

    @property
    def last_n(self) -> int:
        return int(self.dll.hst_stub_last_n())

    @property
    def last_set_len(self) -> int:
        return int(self.dll.hst_stub_last_set_len())


@pytest.fixture(scope="session")
def stub_path(tmp_path_factory: pytest.TempPathFactory) -> pathlib.Path:
    cc = os.environ.get("CC") or shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
    if cc is None:
        pytest.skip("no C compiler on PATH; cannot build the ABI stub")
    out = tmp_path_factory.mktemp("stub") / ("libhst_stub" + _suffix())
    subprocess.run(
        [cc, "-shared", "-fPIC", "-O0", "-o", str(out), str(STUB_SRC)],
        check=True,
        capture_output=True,
    )
    return out


@pytest.fixture()
def stub(stub_path: pathlib.Path) -> Stub:
    """A freshly reset stub, loaded as the process-wide library."""
    _ffi._reset_for_tests()
    api = hstcore.load_library(str(stub_path))
    handle = Stub(api.dll)
    yield handle
    _ffi._reset_for_tests()


@pytest.fixture(autouse=True)
def _no_library_leaks():
    """No test may leave a library loaded for the next one."""
    yield
    _ffi._reset_for_tests()
