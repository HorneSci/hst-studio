"""Python bindings for the HST-core Embedded ABI (``libhstcore``).

This package is **only the binding**. The engine is ``libhstcore``, a shared
library this package does not contain; nothing here computes anything. In an
HST Studio download the library is already in ``bin/`` (``libhstcore.so`` /
``libhstcore.dylib``), Apache-2.0, unmetered, and needs no key, token or
account. A separate, metered build of the same library also exists as its own
artifact. Without any library loaded, every call raises
:class:`HSTLoadError`, and that is the expected outcome if you arrived here by
accident.

This docstring called the library "commercial, closed-source ... under a
signed license" until 2026-08-06, which was true of the metered build and
false of the community one shipped beside it in this same tree.

    >>> import hstcore
    >>> hstcore.load_library("/opt/hst/libhstcore.so")   # doctest: +SKIP
    >>> hstcore.version()                                # doctest: +SKIP
    'hstcore 1.4.0'

See ``README.md`` for what the library does, who it is for, and what to use
instead if you want an open sparse-delta baseline to measure against.
"""

from __future__ import annotations

from ._context import HSTContext
from ._errors import (
    HSTArgumentError,
    HSTBufferError,
    HSTClosedError,
    HSTError,
    HSTInternalError,
    HSTLicenseError,
    HSTLoadError,
    HSTModeError,
    HSTQuotaError,
    HSTShadowNotGrantedError,
    HSTStateExpiredError,
)
from ._ffi import ABI_NODE, default_library_name, load_library, loaded_path
from ._state import StateView

__version__ = "0.1.0"

__all__ = [
    "ABI_NODE",
    "HSTContext",
    "StateView",
    "load_library",
    "loaded_path",
    "default_library_name",
    "version",
    "__version__",
    "HSTError",
    "HSTLoadError",
    "HSTLicenseError",
    "HSTArgumentError",
    "HSTBufferError",
    "HSTInternalError",
    "HSTQuotaError",
    "HSTShadowNotGrantedError",
    "HSTModeError",
    "HSTClosedError",
    "HSTStateExpiredError",
]


def version() -> str:
    """Version string reported by the loaded library, e.g. ``'hstcore 1.4.0'``.

    This is the *library's* version, not this package's — see
    :data:`hstcore.__version__` for that. They move independently, which is the
    point of binding through ``ctypes``.
    """
    return load_library().hst_version().decode("utf-8", "replace")
