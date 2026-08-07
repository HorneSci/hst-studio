"""A DIFFERENT but equally correct summation order, used two ways.

1. To calibrate the GRADE-B bound. The bound is not a guess: it is the observed
   disagreement between two legitimate orders on that exact case, times a
   margin. A tolerance derived from the data it will judge.

2. To demonstrate, rather than assert, that GRADE-A is a strictness test. Run
   the f64 GRADE-A cases through this order and they fail; run the integer
   cases through it and they pass. That contrast is the whole argument for why
   the integer cases are the strongest object in the set.

Public domain (CC0 1.0).
"""


def spmv_row_order(indptr, indices, values, x, n_rows, batch):
    """y = A @ x accumulated ROW-major: for each row, over its entries.

    Mathematically identical to the CSC-order kernel in reference_spmv.py.
    In f64 it is not bit-identical, because addition is not associative.
    """
    rows = [[] for _ in range(n_rows)]
    for j in range(len(indptr) - 1):
        for k in range(indptr[j], indptr[j + 1]):
            rows[indices[k]].append((j, values[k]))
    y = [0.0] * (n_rows * batch)
    for i in range(n_rows):
        for b in range(batch):
            acc = 0.0
            for (j, a) in rows[i]:                    # columns ascending within a row
                acc += a * x[j * batch + b]
            y[i * batch + b] = acc
    return y


def spmv_delta_row_order(indptr, indices, values, dirty, dvals, y, batch):
    """y += A[:, D] @ dx, accumulated row-major over the dirty columns."""
    pos = {j: t for t, j in enumerate(dirty)}
    n_rows = len(y) // batch
    rows = [[] for _ in range(n_rows)]
    for j in dirty:
        for k in range(indptr[j], indptr[j + 1]):
            rows[indices[k]].append((pos[j], values[k]))
    for i in range(n_rows):
        for b in range(batch):
            acc = 0.0
            for (t, a) in rows[i]:
                acc += a * dvals[t * batch + b]
            y[i * batch + b] += acc
    return y


def _same_length(a, b, what):
    """Refuse to compare vectors of different length.

    Both comparisons below used `zip(a, b)`, which stops at the SHORTER
    sequence. So a truncated or zero-length vector compared as identical over
    however many elements survived, and scored perfectly:

        rel_l2([], good)        -> 0.0     bit_diffs([], good)        -> 0
        rel_l2(good[:1], good)  -> 0.0     bit_diffs(good[:1], good)  -> 0

    A verifier reported PASS on both. Zeroing a case's y.f64.bin, or truncating
    it, produced "y bitdiff 0, rel_l2 0.000e+00" -- the strongest possible
    statement of correctness, made over no data at all.

    Length is not a tolerance question, so this raises rather than returning a
    large error: two vectors of different length are not a bad match, they are
    not a comparison.
    """
    if len(a) != len(b):
        raise ValueError(
            f"{what}: length mismatch, {len(a)} vs {len(b)}. A truncated or "
            f"empty vector is not a close match -- it is a file that did not "
            f"survive, and comparing what remains would report success over "
            f"the part that happens to still be there."
        )


def rel_l2(a, b):
    a, b = list(a), list(b)
    _same_length(a, b, "rel_l2")
    num = sum((x - y) * (x - y) for x, y in zip(a, b))
    den = sum(y * y for y in b)
    return (num / den) ** 0.5 if den > 0 else num ** 0.5


def bit_diffs(a, b):
    import struct
    a, b = list(a), list(b)
    _same_length(a, b, "bit_diffs")
    return sum(1 for x, y in zip(a, b)
               if struct.pack("<d", x) != struct.pack("<d", y))
