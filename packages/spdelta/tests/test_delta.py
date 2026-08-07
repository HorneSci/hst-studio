"""The two encodings, and the type error that replaced a silent wrong answer."""

from __future__ import annotations

import numpy as np
import pytest

from spdelta import (
    CompactDelta,
    GlobalDelta,
    GlobalScatter,
    require_compact,
    require_global,
)


def make_compact(cols=(1, 5, 9), batch=2, seed=0) -> CompactDelta:
    rng = np.random.default_rng(seed)
    cols_arr = np.asarray(cols, dtype=np.int32)
    return CompactDelta(cols_arr, rng.standard_normal((cols_arr.size, batch)))


# --------------------------------------------------------------------------
# construction and validation
# --------------------------------------------------------------------------


def test_compact_reports_shape():
    d = make_compact()
    assert d.n_dirty == 3
    assert d.batch == 2


def test_compact_rejects_float32_vals():
    with pytest.raises(TypeError, match="float64"):
        CompactDelta(np.array([0, 1], dtype=np.int32), np.zeros((2, 1), dtype=np.float32))


def test_compact_rejects_one_dimensional_vals():
    with pytest.raises(ValueError, match="2-D"):
        CompactDelta(np.array([0, 1], dtype=np.int32), np.zeros(2))


def test_compact_rejects_duplicate_columns():
    with pytest.raises(ValueError, match="duplicates"):
        CompactDelta(np.array([3, 3], dtype=np.int32), np.zeros((2, 1)))


def test_compact_rejects_non_integer_cols():
    with pytest.raises(TypeError, match="integer"):
        CompactDelta(np.array([0.0, 1.0]), np.zeros((2, 1)))


def test_compact_rejects_row_count_mismatch():
    with pytest.raises(ValueError, match="expected 2"):
        CompactDelta(np.array([0, 1], dtype=np.int32), np.zeros((3, 1)))


def test_compact_rejects_negative_columns():
    with pytest.raises(ValueError, match="non-negative"):
        CompactDelta(np.array([-1, 2], dtype=np.int32), np.zeros((2, 1)))


def test_global_rejects_out_of_range_column():
    with pytest.raises(ValueError, match="out of range"):
        GlobalDelta(np.zeros((4, 1)), np.array([9], dtype=np.int32))


# --------------------------------------------------------------------------
# the round trip
# --------------------------------------------------------------------------


def test_round_trip_preserves_values():
    d = make_compact()
    back = d.to_global(20).to_compact()
    assert np.array_equal(back.cols, d.cols)
    assert np.allclose(back.vals, d.vals)


def test_to_global_zeroes_every_non_dirty_column():
    d = make_compact()
    g = d.to_global(20)
    g.check_clean()
    mask = np.ones(20, dtype=bool)
    mask[d.cols] = False
    assert not g.buf[mask].any()


def test_to_global_rejects_column_past_the_end():
    d = make_compact(cols=(1, 5, 9))
    with pytest.raises(ValueError, match="out of range"):
        d.to_global(5)


def test_copies_do_not_alias():
    d = make_compact()
    twin = d.copy()
    twin.vals[0, 0] += 1.0
    assert d.vals[0, 0] != twin.vals[0, 0]

    g = d.to_global(20)
    g_twin = g.copy()
    g_twin.buf[0, 0] += 1.0
    assert g.buf[0, 0] != g_twin.buf[0, 0]


# --------------------------------------------------------------------------
# the type error
# --------------------------------------------------------------------------


def test_require_compact_rejects_global():
    g = make_compact().to_global(20)
    with pytest.raises(TypeError, match="position within the dirty set"):
        require_compact(g)


def test_require_global_rejects_compact():
    with pytest.raises(TypeError, match="indexed by column"):
        require_global(make_compact())


def test_require_functions_pass_the_right_type_through():
    d = make_compact()
    assert require_compact(d) is d
    g = d.to_global(20)
    assert require_global(g) is g


# --------------------------------------------------------------------------
# the stale-buffer bug
# --------------------------------------------------------------------------


def test_scatter_rezeroes_columns_written_last_step():
    scatter = GlobalScatter(32, 1, verify=True)
    first = CompactDelta(np.array([0, 1, 2], dtype=np.int32), np.ones((3, 1)))
    scatter.scatter(first)
    second = CompactDelta(np.array([10, 11], dtype=np.int32), np.full((2, 1), 5.0))
    g = scatter.scatter(second)
    # The columns written last step must be zero now. This is the stale-buffer defect.
    assert g.buf[0, 0] == 0.0
    assert g.buf[1, 0] == 0.0
    assert g.buf[2, 0] == 0.0
    assert g.buf[10, 0] == 5.0
    g.check_clean()


def test_check_clean_detects_a_stale_entry():
    d = make_compact(cols=(1, 2))
    g = d.to_global(16)
    g.buf[7, 0] = 1e-30  # a leftover, tiny but real
    with pytest.raises(ValueError, match="not re-zeroed"):
        g.check_clean()


def test_check_clean_has_no_tolerance():
    """A stale value is a full-magnitude number; a tolerance would only hide it."""
    g = make_compact(cols=(1, 2)).to_global(16)
    g.buf[7, 0] = np.nextafter(0.0, 1.0)
    with pytest.raises(ValueError):
        g.check_clean()


def test_scatter_rejects_a_batch_mismatch():
    scatter = GlobalScatter(16, 2)
    with pytest.raises(ValueError, match="batch"):
        scatter.scatter(make_compact(batch=3))


def test_scatter_rejects_a_global_delta():
    scatter = GlobalScatter(32, 2)
    with pytest.raises(TypeError):
        scatter.scatter(make_compact().to_global(32))


def test_scatter_counts_its_scatters():
    scatter = GlobalScatter(32, 2)
    scatter.scatter(make_compact())
    scatter.scatter(make_compact(cols=(2, 4, 6)))
    assert scatter.scatters == 2
