"""Toy operator generators and the column adjacency they induce."""

from __future__ import annotations

import numpy as np
import pytest
import scipy.sparse as sp

from spdelta import PUBLIC, Topology, banded, build, fanout, grid2d, suite
from spdelta.profiles import ToySpec


def test_banded_has_the_requested_diagonals():
    a = banded(50, 5, seed=0)
    assert a.shape == (50, 50)
    # 5 diagonals, two of which are short by 1 and two by 2.
    assert a.nnz == 5 * 50 - 2 * (1 + 2)


def test_banded_rejects_even_bandwidth():
    with pytest.raises(ValueError, match="odd"):
        banded(50, 4, seed=0)


def test_grid2d_degrees_are_the_five_point_stencil():
    a = grid2d(5, seed=0)
    degrees = np.diff(sp.csr_matrix(a).indptr)
    assert degrees.max() == 5  # interior: self plus four neighbours
    assert degrees.min() == 3  # corner: self plus two


def test_fanout_column_counts_are_exact():
    a = fanout(64, 6, seed=3)
    per_col = np.diff(sp.csc_matrix(a).indptr)
    assert set(per_col.tolist()) == {6}


def test_fanout_rejects_more_rows_than_exist():
    with pytest.raises(ValueError, match="exceeds"):
        fanout(8, 9, seed=0)


def test_generators_are_deterministic_from_the_seed():
    assert np.allclose(banded(30, 3, 7).toarray(), banded(30, 3, 7).toarray())
    assert not np.allclose(banded(30, 3, 7).toarray(), banded(30, 3, 8).toarray())


def test_build_rejects_an_unknown_kind():
    with pytest.raises(ValueError, match="unknown operator kind"):
        build(ToySpec(name="x", kind="not-a-generator", n_cols=8, param=1, seed=0))


def test_build_rejects_a_grid_spec_whose_size_does_not_square():
    with pytest.raises(ValueError, match="not"):
        build(ToySpec(name="x", kind="grid2d", n_cols=10, param=4, seed=0))


def test_suite_realises_every_operator_in_the_profile():
    built = suite(PUBLIC)
    assert [name for name, _ in built] == [s.name for s in PUBLIC.operators]
    for _, a in built:
        assert a.nnz > 0


# --------------------------------------------------------------------------
# topology
# --------------------------------------------------------------------------


def test_line_topology_neighbours_and_edges():
    topology = Topology.line(6, radius=2)
    assert sorted(topology.neighbors(3).tolist()) == [1, 2, 4, 5]
    assert sorted(topology.neighbors(0).tolist()) == [1, 2]
    assert sorted(topology.neighbors(5).tolist()) == [3, 4]


def test_line_topology_rejects_radius_zero():
    with pytest.raises(ValueError, match="radius"):
        Topology.line(6, radius=0)


def test_operator_topology_excludes_self_and_matches_shared_rows():
    a = sp.csr_matrix(
        np.array(
            [
                [1.0, 1.0, 0.0],
                [0.0, 1.0, 1.0],
            ]
        )
    )
    topology = Topology.from_operator(a)
    assert sorted(topology.neighbors(0).tolist()) == [1]
    assert sorted(topology.neighbors(1).tolist()) == [0, 2]
    assert 1 not in topology.neighbors(1).tolist()


def test_operator_topology_respects_the_neighbour_cap():
    a = fanout(80, 8, seed=5)
    topology = Topology.from_operator(a, max_neighbors=4, seed=1)
    counts = np.diff(topology.indptr)
    assert counts.max() <= 4
