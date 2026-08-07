"""ctypes declarations for the HST-core Embedded ABI.

The surface is ``hstcore.h``: thirteen ``extern "C"`` functions over an opaque
handle, exported under ABI node ``HSTCORE_1.4``. Nothing in this module knows
anything about the library's inside — every handle is a ``void *``, and the
only types crossing the boundary are ``int32``, ``double`` and ``char *``.

The binding is ``ctypes`` on purpose: no compile step, no wheel per Python
version, no ABI of its own to keep in step with a library the customer receives
separately and may replace between releases.
"""

from __future__ import annotations

import ctypes
import sys
import threading
from typing import Any, Optional

from ._errors import HSTLoadError

__all__ = ["ABI_NODE", "SYMBOLS", "default_library_name", "load_library", "loaded_path"]

#: The versioned symbol node the library exports (see ``exported.linux.map``).
ABI_NODE = "HSTCORE_1.4"

_c = ctypes
_i32 = _c.c_int32
_i32p = _c.POINTER(_c.c_int32)
_f64p = _c.POINTER(_c.c_double)
_vp = _c.c_void_p
_cp = _c.c_char_p

#: ``{symbol: (argtypes, restype)}`` for every function in ``hstcore.h``.
#:
#: All THIRTEEN are bound.
#:
#: ⚠️ This said "all twelve" until 2026-08-05 and bound twelve, missing
#: ``hst_set_input``. The count came from commit 4b1c4bb's message ("12 total"),
#: which is wrong -- ``embedded/exported.linux.map``, the file the linker
#: actually reads, lists thirteen. So this package fixed its predecessor's
#: eight-of-twelve gap and shipped twelve-of-thirteen, announcing completeness
#: against a denominator nobody had counted.
#:
#: The omission was not harmless. ``hst_set_state`` MUST be paired with
#: ``hst_set_input`` or ``hst_recompute_full`` refuses with -5 forever; a Python
#: caller who primed the output state had no way to prime the matching input,
#: and therefore no way to use the reference arm this package exists to expose.
#:
#: Caught by ``oss/hstcore-abi/validate.py``, which is now the authority on this
#: list. Do not add a symbol here without adding it to ``abi.json``.
SYMBOLS: dict[str, tuple[list[Any], Any]] = {
    "hst_open": ([_cp, _cp, _cp, _c.c_size_t], _vp),
    "hst_open_batched": ([_cp, _cp, _i32, _cp, _c.c_size_t], _vp),
    "hst_apply_delta": ([_vp, _i32p, _f64p, _i32, _f64p], _c.c_int),
    "hst_apply_shadow": ([_vp, _i32p, _f64p, _i32, _f64p], _c.c_int),
    "hst_batch": ([_vp], _i32),
    "hst_output_dim": ([_vp], _i32),
    "hst_input_dim": ([_vp], _i32),
    "hst_state": ([_vp], _f64p),
    "hst_set_state": ([_vp, _f64p, _i32], _c.c_int),
    "hst_set_input": ([_vp, _f64p, _i32], _c.c_int),
    "hst_recompute_full": ([_vp, _f64p], _c.c_int),
    "hst_close": ([_vp], None),
    "hst_version": ([], _cp),
}


def default_library_name() -> str:
    """Platform-conventional file name of the shipped library."""
    if sys.platform == "darwin":
        return "libhstcore.dylib"
    if sys.platform.startswith("win"):
        return "hstcore.dll"
    return "libhstcore.so"


class _Api:
    """A loaded library with all thirteen symbols bound and typed."""

    def __init__(self, path: str) -> None:
        try:
            dll = _c.CDLL(path)
        except OSError as exc:
            raise HSTLoadError(
                f"could not load {path!r}: {exc}. This package is only the binding; "
                f"it ships no library. In an HST Studio download the library is in "
                f"bin/ (libhstcore.so or libhstcore.dylib) -- pass its path as "
                f"lib_path, since bin/ is not on the loader's default search path."
            ) from exc
        for name, (argtypes, restype) in SYMBOLS.items():
            try:
                fn = getattr(dll, name)
            except AttributeError as exc:
                raise HSTLoadError(
                    f"{path!r} does not export {name!r}; expected the complete "
                    f"{ABI_NODE} surface ({len(SYMBOLS)} symbols)."
                ) from exc
            fn.argtypes = argtypes
            fn.restype = restype
            setattr(self, name, fn)
        self.path = path
        self.dll = dll


_LOCK = threading.Lock()
_API: Optional[_Api] = None


def load_library(path: Optional[str] = None) -> _Api:
    """Load ``libhstcore`` for this process. Idempotent.

    One library per process, held forever: the handles it hands out outlive any
    individual call, and unloading underneath them would invalidate them. The
    first call decides the path; later calls either agree (and get the same
    object back) or raise :class:`~hstcore.HSTLoadError`.

    ``path=None`` means the platform default name, resolved by the dynamic
    loader's usual search (``DYLD_LIBRARY_PATH`` / ``LD_LIBRARY_PATH`` /
    rpath). Pass an absolute path when you know where the library is.
    """
    global _API
    with _LOCK:
        if _API is not None:
            if path is not None and str(path) != _API.path:
                raise HSTLoadError(
                    f"library already loaded from {_API.path!r}; refusing to also "
                    f"load {str(path)!r}. One library per process."
                )
            return _API
        _API = _Api(str(path) if path is not None else default_library_name())
        return _API


def loaded_path() -> Optional[str]:
    """Path of the loaded library, or ``None`` if none is loaded yet."""
    return _API.path if _API is not None else None


def _reset_for_tests() -> None:
    """Drop the process-wide library reference.

    Test-only. Any live context created from the previous library keeps working
    (it holds its own reference), which is why this is not a public API.
    """
    global _API
    with _LOCK:
        _API = None
