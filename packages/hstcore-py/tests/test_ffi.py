"""The symbol table, and loading."""

from __future__ import annotations

import ctypes.util
import sys

import pytest

import hstcore
from hstcore import _ffi

# Written out again, on purpose, rather than derived from _ffi.SYMBOLS: a test
# that reads the table it is checking cannot catch a name that was mistyped in
# both places. This list is the one in hstcore.h and in exported.linux.map.
#
# ⚠️ That principle is right and it still failed. Until 2026-08-05 this list had
# only twelve of thirteen entries, missing hst_set_input -- because the independent copy
# was written from the same wrong count as the thing it was checking (commit
# 4b1c4bb's "12 total"; the version map lists thirteen). Independence from the
# other TABLE is not independence from the other COUNT.
#
# The umbrella additionally cross-checks this list against oss/hstcore-abi/abi.json
# and against the built library's real exports, which is the check that has a
# source outside anyone's memory. This package keeps its own copy so it remains
# self-contained when published on its own.
ABI = [
    "hst_open",
    "hst_open_batched",
    "hst_apply_delta",
    "hst_apply_shadow",
    "hst_batch",
    "hst_output_dim",
    "hst_input_dim",
    "hst_state",
    "hst_set_state",
    "hst_set_input",
    "hst_recompute_full",
    "hst_close",
    "hst_version",
]


def test_every_abi_symbol_is_bound():
    assert sorted(_ffi.SYMBOLS) == sorted(ABI)
    assert len(_ffi.SYMBOLS) == 13


def test_the_four_the_predecessor_left_out_are_present():
    # These are the reason this package exists as more than a rename: batching
    # is where the ABI says HST beats a plain exact delta, and recompute_full is
    # the from-scratch reference arm.
    for name in ("hst_open_batched", "hst_apply_shadow", "hst_batch", "hst_recompute_full"):
        assert name in _ffi.SYMBOLS


def test_signatures_are_complete():
    for name, (argtypes, restype) in _ffi.SYMBOLS.items():
        assert isinstance(argtypes, list), name
        # hst_version is the only nullary function in the ABI.
        assert (len(argtypes) == 0) == (name == "hst_version"), name
        # hst_close is the only one that returns nothing.
        assert (restype is None) == (name == "hst_close"), name


def test_abi_node_is_recorded():
    assert hstcore.ABI_NODE == "HSTCORE_1.4"


def test_default_library_name_matches_platform():
    name = hstcore.default_library_name()
    if sys.platform == "darwin":
        assert name == "libhstcore.dylib"
    elif sys.platform.startswith("win"):
        assert name == "hstcore.dll"
    else:
        assert name == "libhstcore.so"


def test_missing_library_raises_load_error():
    with pytest.raises(hstcore.HSTLoadError) as exc:
        hstcore.load_library("/nonexistent/libhstcore-does-not-exist.so")
    assert "binding" in str(exc.value)


def test_wrong_library_names_the_missing_symbol():
    libc = ctypes.util.find_library("c")
    if libc is None:
        pytest.skip("no libc path available")
    with pytest.raises(hstcore.HSTLoadError) as exc:
        hstcore.load_library(libc)
    assert "hst_open" in str(exc.value)


def test_load_is_idempotent(stub_path):
    a = hstcore.load_library(str(stub_path))
    b = hstcore.load_library(str(stub_path))
    c = hstcore.load_library()  # no path: takes what is already loaded
    assert a is b is c
    assert hstcore.loaded_path() == str(stub_path)


def test_second_different_path_is_refused(stub_path):
    hstcore.load_library(str(stub_path))
    with pytest.raises(hstcore.HSTLoadError) as exc:
        hstcore.load_library("/some/other/libhstcore.so")
    assert "already loaded" in str(exc.value)


def test_loaded_path_is_none_before_loading():
    assert hstcore.loaded_path() is None


def test_version_comes_from_the_library(stub):
    assert hstcore.version() == "hstcore-stub 0.0.0 (no engine)"
    assert hstcore.__version__ != hstcore.version()
