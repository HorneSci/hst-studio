"""Reference sparse mat-vec and delta-apply, plain CSC. Public domain (CC0 1.0).

This file is the whole point of the golden-vector set: it lets a stranger check
any delta implementation against the shipped `y` without running ours, or any
other, sparse runtime. No dependencies beyond the standard library. No numpy.

THE SUMMATION ORDER IS PART OF THE SPEC.  Both kernels below accumulate in
column-major CSC order: columns ascending, and within a column, row indices
ascending.  Floating-point addition is not associative, so a correct
implementation using a different order will produce a different `y`.  That is
expected, and it is why GRADE-A is a strictness test rather than a correctness
test.  See README.md.

    y  =  A @ x        with  A in CSC, x an (M x B) dense batch
    y +=  A[:, D] @ dx for a dirty column set D and its values dx

Everything a case manifest names -- the preprocessing rule, the x0 generator,
the PRNG -- is implemented here, so the manifest is executable rather than
aspirational.
"""

import struct

# ---------------------------------------------------------------------------
# THE KERNELS.  Everything else in this file is plumbing.
# ---------------------------------------------------------------------------

def spmv(indptr, indices, values, x, n_rows, batch):
    """y = A @ x, CSC order: columns ascending, rows within a column ascending."""
    y = [0.0] * (n_rows * batch)
    for j in range(len(indptr) - 1):                      # columns ascending
        for k in range(indptr[j], indptr[j + 1]):         # rows ascending
            a, i = values[k], indices[k]
            for b in range(batch):
                y[i * batch + b] += a * x[j * batch + b]
    return y


def spmv_delta(indptr, indices, values, dirty, dvals, y, batch):
    """y += A[:, D] @ dx, in place. Same order, restricted to D (ascending)."""
    for t, j in enumerate(dirty):                         # dirty cols ascending
        for k in range(indptr[j], indptr[j + 1]):         # rows ascending
            a, i = values[k], indices[k]
            for b in range(batch):
                y[i * batch + b] += a * dvals[t * batch + b]
    return y

# ---------------------------------------------------------------------------
# PRNG -- SplitMix64. Specified exactly so Python and C agree bit for bit.
# ---------------------------------------------------------------------------

M64 = (1 << 64) - 1

class SplitMix64:
    def __init__(self, seed):
        self.s = seed & M64

    def next(self):
        self.s = (self.s + 0x9E3779B97F4A7C15) & M64
        z = self.s
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & M64
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & M64
        return z ^ (z >> 31)

    def unit(self):
        """[0,1) via the top 53 bits -- the one exact way to do this."""
        return (self.next() >> 11) * (2.0 ** -53)

    def signed(self):
        return 2.0 * self.unit() - 1.0

# ---------------------------------------------------------------------------
# Matrix Market -> CSC, under a named preprocessing rule.
# ---------------------------------------------------------------------------

def read_mm(path):
    """Returns (n_rows, n_cols, entries, symmetric). entries = [(i, j, v)] 0-based."""
    with open(path, "r") as f:
        header = f.readline().split()
        field, symmetry = header[3].lower(), header[4].lower()
        assert symmetry in ("general", "symmetric"), symmetry
        for line in f:
            if not line.startswith("%"):
                n_rows, n_cols, _ = (int(t) for t in line.split())
                break
        entries = []
        for line in f:
            if line.startswith("%") or not line.strip():
                continue
            t = line.split()
            i, j = int(t[0]) - 1, int(t[1]) - 1
            v = float(t[2]) if field != "pattern" else 1.0
            entries.append((i, j, v))
    return n_rows, n_cols, entries, symmetry == "symmetric"


def build_csc(path, rule):
    """Apply a named preprocessing rule and return (indptr, indices, values, N, M).

    Structural expansion, shared by every rule: a `symmetric` file stores one
    triangle, so each off-diagonal (i,j) contributes both (i,j) and (j,i); a
    diagonal entry contributes once.  Duplicate coordinates are rejected, not
    silently summed or dropped -- no operator in the published set has any.

    Value rules:
      pattern_int_v1  -- discard stored values; A[i,j] = 1 + ((i + 3j) mod 5),
                         i and j zero-based. Small exact integers in 1..5.
      values_f64_v1   -- use the stored value; a `pattern` file gives 1.0.
    """
    n_rows, n_cols, entries, sym = read_mm(path)
    seen, expanded = set(), []
    for (i, j, v) in entries:
        for (r, c) in (((i, j),) if (not sym or i == j) else ((i, j), (j, i))):
            assert (r, c) not in seen, f"duplicate coordinate ({r},{c}) in {path}"
            seen.add((r, c))
            expanded.append((r, c, v))
    cols = [[] for _ in range(n_cols)]
    for (i, j, v) in expanded:
        cols[j].append((i, (1 + ((i + 3 * j) % 5)) if rule == "pattern_int_v1" else v))
    indptr, indices, values = [0], [], []
    for j in range(n_cols):
        for (i, v) in sorted(cols[j]):                    # rows ascending
            indices.append(i)
            values.append(float(v))
        indptr.append(len(indices))
    return indptr, indices, values, n_rows, n_cols


def gen_x0(rule, seed, n_cols, batch):
    """x0 generators. Named in the manifest; implemented here so it is checkable."""
    if rule == "x0_int_v1":                               # integers 1..9
        return [float(1 + ((j + 7 * b) % 9))
                for j in range(n_cols) for b in range(batch)]
    if rule == "x0_f64_v1":                               # SplitMix64, [-1,1)
        rng = SplitMix64(seed)
        return [rng.signed() for _ in range(n_cols * batch)]
    raise ValueError(rule)

# ---------------------------------------------------------------------------
# dx.bin -- the published delta schedule. Format documented in README.md.
# ---------------------------------------------------------------------------

DX_MAGIC = b"GVDX0001"

def read_dx(path):
    with open(path, "rb") as f:
        blob = f.read()
    assert blob[:8] == DX_MAGIC, "not a golden-vector delta file"
    ver, steps, n_cols, batch, dtype, _rsv = struct.unpack_from("<6I", blob, 8)
    assert ver == 1 and dtype == 0, (ver, dtype)
    off, sched = 32, []
    for _ in range(steps):
        (k,) = struct.unpack_from("<I", blob, off); off += 4
        dirty = list(struct.unpack_from(f"<{k}I", blob, off)); off += 4 * k
        n = k * batch
        vals = list(struct.unpack_from(f"<{n}d", blob, off)); off += 8 * n
        sched.append((dirty, vals))
    assert off == len(blob), "trailing bytes in delta file"
    return steps, n_cols, batch, sched


def write_f64(path, vec):
    with open(path, "wb") as f:
        f.write(struct.pack(f"<{len(vec)}d", *vec))


def read_f64(path):
    blob = open(path, "rb").read()
    return list(struct.unpack(f"<{len(blob) // 8}d", blob))


def replay(csc_path_or_tuple, rule, x0_rule, x0_seed, dx_path, batch):
    """Regenerate (y0, [y after each step]) from the operator and the schedule."""
    indptr, indices, values, N, M = (
        build_csc(csc_path_or_tuple, rule)
        if isinstance(csc_path_or_tuple, str) else csc_path_or_tuple)
    x0 = gen_x0(x0_rule, x0_seed, M, batch)
    y0 = spmv(indptr, indices, values, x0, N, batch)
    steps, dx_cols, dx_batch, sched = read_dx(dx_path)
    assert dx_cols == M and dx_batch == batch, (dx_cols, M, dx_batch, batch)
    y, out = list(y0), []
    for (dirty, dvals) in sched:
        spmv_delta(indptr, indices, values, dirty, dvals, y, batch)
        out.extend(y)
    return y0, out
