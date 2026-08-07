"""Registry isolation.

`binds` writes to a process-global registry, which is the right ergonomics for
a numbers module (declare bindings at import, parametrize over them) and the
wrong ergonomics for testing the library itself. This fixture snapshots and
restores it so bindnum's own tests can register freely without deleting the
worked example's four bindings out from under it.
"""

from __future__ import annotations

import pytest

from bindnum import binding as binding_module


@pytest.fixture(autouse=True)
def isolated_registry():
    saved = list(binding_module._REGISTRY)
    binding_module._REGISTRY.clear()
    try:
        yield binding_module._REGISTRY
    finally:
        binding_module._REGISTRY[:] = saved
