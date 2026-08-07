"""Toy sparse operators, and the column-adjacency they induce.

Everything here is generated from a seed written in this repository. No operator
in this package came from a measurement, a customer, or a corpus. That is a
constraint, not an apology: the point of the package is the *method*, and a
method that only works on one matrix collection is not a method.

The generators are chosen to span the property that decides which arm of a
delta-updated matvec wins -- how the dirty set's columns are laid out relative
to the operator's rows:

* :func:`banded` -- a dirty set that is an interval touches a compact, almost
  contiguous set of rows.
* :func:`grid2d` -- a 5-point stencil, where an interval of column indices is
  local in one axis and strided in the other.
* :func:`fanout` -- uniformly random columns, so a dirty set of any shape
  touches rows scattered across the whole range. This is the adversarial case
  and it is in the default list on purpose.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import scipy.sparse as sp
from numpy.typing import NDArray

from .profiles import Profile, ToySpec, active

__all__ = [
    "banded",
    "grid2d",
    "fanout",
    "build",
    "suite",
    "Topology",
]


def banded(n_cols: int, bandwidth: int, seed: int) -> sp.csr_matrix:
    """A square banded operator with ``bandwidth`` diagonals, odd and centred."""
    if bandwidth < 1 or bandwidth % 2 == 0:
        raise ValueError(f"bandwidth must be a positive odd integer, got {bandwidth}")
    if n_cols < bandwidth:
        raise ValueError(f"n_cols {n_cols} must be at least bandwidth {bandwidth}")
    rng = np.random.default_rng(seed)
    half = bandwidth // 2
    offsets = list(range(-half, half + 1))
    diagonals = [rng.standard_normal(n_cols) for _ in offsets]
    mat = sp.diags(diagonals, offsets, shape=(n_cols, n_cols), format="csr")
    return sp.csr_matrix(mat, dtype=np.float64)


def grid2d(side: int, seed: int) -> sp.csr_matrix:
    """A 5-point stencil on a ``side x side`` grid, flattened row-major."""
    if side < 2:
        raise ValueError(f"side must be at least 2, got {side}")
    rng = np.random.default_rng(seed)
    n = side * side
    rows: list[int] = []
    cols: list[int] = []
    for node in range(n):
        r, c = divmod(node, side)
        rows.append(node)
        cols.append(node)
        if r > 0:
            rows.append(node)
            cols.append(node - side)
        if r < side - 1:
            rows.append(node)
            cols.append(node + side)
        if c > 0:
            rows.append(node)
            cols.append(node - 1)
        if c < side - 1:
            rows.append(node)
            cols.append(node + 1)
    data = rng.standard_normal(len(rows))
    mat = sp.coo_matrix((data, (rows, cols)), shape=(n, n), dtype=np.float64)
    return sp.csr_matrix(mat)


def fanout(n_cols: int, per_col: int, seed: int) -> sp.csr_matrix:
    """A square operator with exactly ``per_col`` uniformly random rows per column.

    Built column-wise so the *column* nonzero count is exact, because the
    column is the unit a delta touches and the unit the nnz-matched jump control
    bands on. A row-wise generator would give a ragged column distribution and
    make the control's bands noisy for no reason.
    """
    if per_col < 1:
        raise ValueError(f"per_col must be >= 1, got {per_col}")
    if per_col > n_cols:
        raise ValueError(f"per_col {per_col} exceeds n_cols {n_cols}")
    rng = np.random.default_rng(seed)
    rows = np.empty(n_cols * per_col, dtype=np.int32)
    for j in range(n_cols):
        rows[j * per_col : (j + 1) * per_col] = rng.choice(
            n_cols, size=per_col, replace=False
        )
    cols = np.repeat(np.arange(n_cols, dtype=np.int32), per_col)
    data = rng.standard_normal(rows.size)
    mat = sp.coo_matrix((data, (rows, cols)), shape=(n_cols, n_cols), dtype=np.float64)
    return sp.csr_matrix(mat)


def build(spec: ToySpec) -> sp.csr_matrix:
    """Realise a :class:`~spdelta.profiles.ToySpec`."""
    if spec.kind == "banded":
        return banded(spec.n_cols, spec.param, spec.seed)
    if spec.kind == "grid2d":
        if spec.param * spec.param != spec.n_cols:
            raise ValueError(
                f"grid2d spec {spec.name!r}: n_cols {spec.n_cols} is not "
                f"param^2 = {spec.param * spec.param}"
            )
        return grid2d(spec.param, spec.seed)
    if spec.kind == "fanout":
        return fanout(spec.n_cols, spec.param, spec.seed)
    raise ValueError(f"unknown operator kind {spec.kind!r}")


def suite(profile: Profile | None = None) -> list[tuple[str, sp.csr_matrix]]:
    """``(name, matrix)`` for every operator in the active profile."""
    profile = profile or active()
    return [(spec.name, build(spec)) for spec in profile.operators]


@dataclass(frozen=True)
class Topology:
    """Which columns count as neighbours of which, in CSR-of-neighbours form.

    Local drift needs a notion of "nearby column" and there is no universal one.
    Two are provided and they answer different questions:

    * :meth:`line` -- neighbours are index-adjacent. Cheap, and the right model
      when column order carries the geometry (a banded operator, a 1-D mesh, a
      time-ordered state).
    * :meth:`from_operator` -- neighbours are columns that share a row. This is
      the structural definition and the one that matches a dirty set spreading
      along an operator's own connectivity, but it costs a pattern product to
      compute and can densify badly on a high-fanout operator, so it is capped.
    """

    n_cols: int
    indptr: NDArray[np.int64]
    indices: NDArray[np.int32]
    name: str

    def neighbors(self, col: int) -> NDArray[np.int32]:
        """The neighbour list of ``col``; possibly empty."""
        return self.indices[self.indptr[col] : self.indptr[col + 1]]

    @classmethod
    def line(cls, n_cols: int, radius: int = 1) -> Topology:
        """Neighbours are the ``2*radius`` index-adjacent columns."""
        if radius < 1:
            raise ValueError(f"radius must be >= 1, got {radius}")
        offsets = np.array(
            [d for d in range(-radius, radius + 1) if d != 0], dtype=np.int64
        )
        base = np.arange(n_cols, dtype=np.int64)[:, None] + offsets[None, :]
        keep = (base >= 0) & (base < n_cols)
        counts = keep.sum(axis=1)
        indptr = np.zeros(n_cols + 1, dtype=np.int64)
        np.cumsum(counts, out=indptr[1:])
        return cls(
            n_cols=n_cols,
            indptr=indptr,
            indices=base[keep].astype(np.int32),
            name=f"line(radius={radius})",
        )

    @classmethod
    def from_operator(
        cls, a: sp.spmatrix, *, max_neighbors: int = 32, seed: int = 0
    ) -> Topology:
        """Neighbours are columns sharing at least one row with this one.

        Capped at ``max_neighbors`` per column, sampled deterministically from
        the seed. The cap exists because the pattern product on a high-fanout
        operator is dense enough to dominate the whole run, and because a drift
        model that can reach anywhere in one hop is not a drift model.
        """
        csc = sp.csc_matrix(a)
        pattern = csc.astype(bool).astype(np.int8)
        adjacency = sp.csr_matrix((pattern.T @ pattern).astype(bool))
        adjacency.setdiag(False)
        adjacency.eliminate_zeros()
        rng = np.random.default_rng(seed)
        n_cols = adjacency.shape[0]
        indptr = np.zeros(n_cols + 1, dtype=np.int64)
        chunks: list[NDArray[np.int32]] = []
        for j in range(n_cols):
            near = adjacency.indices[adjacency.indptr[j] : adjacency.indptr[j + 1]]
            if near.size > max_neighbors:
                near = rng.choice(near, size=max_neighbors, replace=False)
                near = np.sort(near)
            chunks.append(near.astype(np.int32))
            indptr[j + 1] = indptr[j] + near.size
        indices = (
            np.concatenate(chunks) if chunks else np.empty(0, dtype=np.int32)
        ).astype(np.int32)
        return cls(
            n_cols=n_cols,
            indptr=indptr,
            indices=indices,
            name=f"operator(max_neighbors={max_neighbors})",
        )
