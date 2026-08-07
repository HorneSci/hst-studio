// blocksched_ref.hpp — an OPEN block-scheduled delta implementation.
//
// Released with "Delta-input SpMM: what the motion model decides" as the
// paper's open reference arm. Stdlib only; no build system, no dependencies.
//
// Why this file exists
// --------------------
// The paper's Families section divides delta implementations into two families
// by *what they prepare for*, and then measures one member of each: an open
// column-exact CSR delta and a closed block-scheduled system. Two
// implementations cannot establish a claim about two families — every measured
// difference is confounded with every other engineering difference between one
// open C++ header and one closed runtime, and a reader who cannot run the
// second arm has to take the Families and Merge sections on trust.
//
// This is a second, independent member of the block-scheduled family, written
// against the externally-visible strategy the paper states and nothing else:
//
//   "A block-scheduled implementation prepares per block-column, so it scans
//    padding [...] but survives movement that stays inside the blocks it
//    already covers."
//
// It shares no source with the closed arm, and two of its design choices are
// different on purpose (see "Divergences" below) so that a result which
// reproduces here is a property of the strategy rather than of one codebase.
// It is not tuned to win. If the dichotomy of the Families section shows up in
// this file too, the family abstraction is real; if it does not, that section
// was a statement about one product and the paper has to say so.
//
// The strategy, in full
// --------------------
// Partition the columns of A into tiles of width `tile`. For each column-tile,
// compile a *segment*: the list of output rows that tile feeds, and for each
// row the (local column, value) pairs living in it. A segment depends only on A
// and on the tile index, so it is compiled at most once ever and cached on the
// operator — that is the whole source of this family's cheap re-preparation.
//
// At apply time, given a dirty column set D:
//   1. compute the set of column-tiles CT that D touches;
//   2. compile any tile in CT never seen before (cache miss = re-preparation);
//   3. scatter dx into a tile-local dense scratch;
//   4. for each tile in CT, walk its segment and accumulate into y;
//   5. un-scatter, restoring the scratch to zero.
//
// Step 4 touches every nonzero in every live tile, including the columns of
// that tile which are NOT dirty. Their scratch slots hold zero, so the result
// is exact, but the work is wasted. That waste is the padding the paper prices
// as the ratio of entries needed to entries scanned, and it is why this family
// loses on a frozen set.
//
// Divergences from the closed arm, both deliberate
// ------------------------------------------------
// 1. **Tile-local scratch, not an M-wide one.** Here the scratch is
//    |CT| * tile * B, allocated from a pool, and the zero-fill is O(|D|*B)
//    rather than O(M*B) because the invariant "the scratch is zero on entry and
//    on exit" is maintained by un-scattering exactly what was scattered. There
//    is no M*B fill anywhere in this file, so the session-construction tax the
//    paper's measurement-defect section describes cannot occur in it. This
//    makes the open arm *better* on that axis than the arm it stands in for,
//    which is the right direction for a control: if the dichotomy survives
//    against a block-scheduled arm that does not pay that tax, it is not an
//    artifact of it.
//
// 2. **Segment slots are position-independent.** A segment stores local column
//    indices only, and the walk adds its tile's base offset at apply time, so a
//    compiled segment is valid for any dirty set and any co-resident tile set.
//    The cache therefore never invalidates. This is the strongest form of the
//    family's "survives movement" property and gives the block-scheduled side
//    the benefit of the doubt.
//
// Both variants of the family are here, because the Merge section needs both:
//   - `BSPerTile`   one compiled segment per column-tile (cached, cheap to move)
//   - `BSMerged`    one globally row-merged array (each output row touched once,
//                   re-emitted whenever CT moves)
// `merge_row_counts` reports the structural ratio that section measures, as an
// integer identity read off the built schedules with no timing involved.
//
// Correctness is checked by `blocksched_selftest.cpp`, which recomputes every
// product from scratch against a direct evaluation and returns non-zero on any
// disagreement. Run it before trusting a timing built on this header.
#pragma once

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <stdexcept>
#include <unordered_map>
#include <vector>

namespace bsref {

// ---------------------------------------------------------------- input

// Compressed-sparse-column view of A. Owned, so the operator outlives whatever
// built it. `ptr` has M+1 entries.
struct CscView {
    int                 N = 0, M = 0;
    std::vector<int>    ptr;
    std::vector<int>    row;
    std::vector<double> val;
};

// ---------------------------------------------------------------- segments

// One compiled column-tile. `rows` are the distinct global output rows this
// tile feeds, strictly increasing. Row i owns entries [start[i], start[i]+len[i])
// of (lc, val), where `lc` is the column's offset *within the tile*.
//
// Nothing here refers to a dirty set or to which other tiles are live, which is
// what lets the operator cache it forever.
struct Segment {
    std::vector<int>     rows;
    std::vector<int32_t> start, len;
    std::vector<uint16_t> lc;
    std::vector<double>  val;
    long nnz = 0;   // entries in this tile == what a walk of it scans
};

// The operator: A, tiled, plus a lazily-filled cache of compiled segments.
//
// `compiles` counts cache misses over the operator's life. It is the
// re-preparation counter the benchmark charges: a step that touches k tiles
// never seen before pays k compiles and nothing else.
class BSOperator {
  public:
    BSOperator(CscView csc, int tile) : A_(std::move(csc)), tile_(tile) {
        if (tile_ <= 0) throw std::invalid_argument("tile must be positive");
        if (tile_ > 65536)
            throw std::invalid_argument("tile > 65536 does not fit uint16_t local columns");
        n_tiles_ = (A_.M + tile_ - 1) / tile_;
        seg_.resize((size_t)n_tiles_);
        have_.assign((size_t)n_tiles_, 0);
    }

    int  tile()    const { return tile_; }
    int  n_tiles() const { return n_tiles_; }
    int  N()       const { return A_.N; }
    int  M()       const { return A_.M; }
    long compiles() const { return compiles_; }
    void reset_compiles() { compiles_ = 0; }
    const CscView& csc() const { return A_; }

    // Compile-on-demand. The only place a segment is ever built.
    const Segment& segment(int ct) {
        if (ct < 0 || ct >= n_tiles_) throw std::out_of_range("column tile out of range");
        if (!have_[(size_t)ct]) {
            seg_[(size_t)ct] = build_segment(ct);
            have_[(size_t)ct] = 1;
            ++compiles_;
        }
        return seg_[(size_t)ct];
    }

    bool cached(int ct) const { return have_[(size_t)ct] != 0; }

    // Column tiles a dirty set touches, sorted and deduplicated.
    static std::vector<int> tiles_of(const int* cols, size_t n, int tile) {
        std::vector<int> ct;
        ct.reserve(n);
        for (size_t i = 0; i < n; ++i) ct.push_back(cols[i] / tile);
        std::sort(ct.begin(), ct.end());
        ct.erase(std::unique(ct.begin(), ct.end()), ct.end());
        return ct;
    }
    std::vector<int> tiles_of(const int* cols, size_t n) const {
        return tiles_of(cols, n, tile_);
    }

    // Entries a per-tile walk would scan for this dirty set, against the
    // entries a column-exact implementation would touch. The reciprocal of the
    // second over the first is the paper's needed-over-scanned ratio.
    // Structural; no timing.
    long scanned_nnz(const std::vector<int>& ct) {
        long s = 0;
        for (int t : ct) s += segment(t).nnz;
        return s;
    }
    long exact_nnz(const int* cols, size_t n) const {
        long s = 0;
        for (size_t i = 0; i < n; ++i) s += A_.ptr[cols[i] + 1] - A_.ptr[cols[i]];
        return s;
    }

  private:
    Segment build_segment(int ct) const {
        const int c0 = ct * tile_;
        const int c1 = std::min(c0 + tile_, A_.M);
        struct E { int r; uint16_t lc; double v; };
        std::vector<E> es;
        size_t total = 0;
        for (int c = c0; c < c1; ++c) total += (size_t)(A_.ptr[c + 1] - A_.ptr[c]);
        es.reserve(total);
        for (int c = c0; c < c1; ++c)
            for (int p = A_.ptr[c]; p < A_.ptr[c + 1]; ++p)
                es.push_back({A_.row[p], (uint16_t)(c - c0), A_.val[p]});
        // Stable by row so a row's entries stay in column order, which is the
        // layout a hand-written tile kernel would emit.
        std::stable_sort(es.begin(), es.end(),
                         [](const E& a, const E& b) { return a.r < b.r; });

        Segment s;
        s.lc.reserve(es.size());
        s.val.reserve(es.size());
        int cur = -1;
        for (const E& e : es) {
            if (e.r != cur) {
                s.rows.push_back(e.r);
                s.start.push_back((int32_t)s.val.size());
                s.len.push_back(0);
                cur = e.r;
            }
            s.lc.push_back(e.lc);
            s.val.push_back(e.v);
            s.len.back()++;
        }
        s.nnz = (long)s.val.size();
        return s;
    }

    CscView              A_;
    int                  tile_ = 0, n_tiles_ = 0;
    std::vector<Segment> seg_;
    std::vector<uint8_t> have_;
    long                 compiles_ = 0;
};

// ---------------------------------------------------------------- scratch

// Pooled tile-local dx scratch. Sized |CT| * tile * B doubles and reused across
// steps; grows monotonically and is never zero-filled wholesale after the first
// allocation, because the scatter/un-scatter pair maintains the all-zero
// invariant. The pool is what keeps this family from paying a preparation cost
// no baseline pays — the measurement defect the paper's defect section
// describes.
class ScratchPool {
  public:
    double* get(size_t need) {
        if (buf_.size() < need) buf_.resize(need, 0.0);
        return buf_.data();
    }
    size_t capacity() const { return buf_.size(); }
    // Test hook: assert the invariant actually holds.
    bool all_zero(size_t n) const {
        for (size_t i = 0; i < n && i < buf_.size(); ++i)
            if (buf_[i] != 0.0) return false;
        return true;
    }
  private:
    std::vector<double> buf_;
};

// ---------------------------------------------------------------- per-tile arm

// A prepared per-tile session: the live tile set and where each tile's slice of
// the scratch begins. Preparing it costs only the compiles of tiles the
// operator has never seen; everything else is a small vector build.
struct BSPerTile {
    std::vector<int>    ct;        // live column tiles, sorted
    std::vector<size_t> base;      // scratch offset of tile i, in doubles
    int    B = 0, tile = 0;
    size_t scratch_len = 0;
    long   compiles_paid = 0;      // re-preparation charged at this prepare
    long   scanned = 0;            // entries a walk scans

    // Distinct output rows a walk touches, counting a row once per tile that
    // feeds it. The per-tile side of the Merge section's row-count identity.
    long row_touches = 0;
};

inline BSPerTile bs_prepare(BSOperator& op, const int* cols, size_t n, int B) {
    BSPerTile s;
    s.B = B;
    s.tile = op.tile();
    s.ct = op.tiles_of(cols, n);
    const long before = op.compiles();
    s.base.resize(s.ct.size());
    size_t off = 0;
    for (size_t i = 0; i < s.ct.size(); ++i) {
        s.base[i] = off;
        off += (size_t)op.tile() * (size_t)B;
        const Segment& g = op.segment(s.ct[i]);
        s.scanned += g.nnz;
        s.row_touches += (long)g.rows.size();
    }
    s.scratch_len = off;
    s.compiles_paid = op.compiles() - before;
    return s;
}

// y += alpha * A[:, D] @ dx, computed by walking every live tile in full.
//
// `dx` is the caller's compact (n x B) block, `cols` its columns in the same
// order. Scatter and un-scatter are inside this call because they are what the
// caller actually pays; charging them elsewhere is the paper's measurement
// defect.
template <int B>
inline void bs_apply_w(BSOperator& op, const BSPerTile& s, const int* cols,
                            size_t n, const double* dx, double* Y, double alpha,
                            ScratchPool& pool) {
    double* scratch = pool.get(s.scratch_len);
    const int tile = s.tile;

    // scatter: column c lives in tile c/tile at local offset c%tile. Its slot
    // is found by binary search over the live tile list, which is short.
    for (size_t i = 0; i < n; ++i) {
        const int c = cols[i];
        const int t = c / tile;
        const size_t k = (size_t)(std::lower_bound(s.ct.begin(), s.ct.end(), t) - s.ct.begin());
        double* d = scratch + s.base[k] + (size_t)(c % tile) * B;
        const double* src = dx + i * (size_t)B;
        for (int b = 0; b < B; ++b) d[b] = src[b];
    }

    for (size_t i = 0; i < s.ct.size(); ++i) {
        const Segment& g = op.segment(s.ct[i]);
        const double* base = scratch + s.base[i];
        const int32_t* st = g.start.data();
        const int32_t* ln = g.len.data();
        const uint16_t* lc = g.lc.data();
        const double* vv = g.val.data();
        const int* rows = g.rows.data();
        const size_t nr = g.rows.size();
        double part[B];
        for (size_t r = 0; r < nr; ++r) {
            for (int b = 0; b < B; ++b) part[b] = 0.0;
            const int32_t e0 = st[r], e1 = st[r] + ln[r];
            for (int32_t p = e0; p < e1; ++p) {
                const double av = vv[p];
                const double* d = base + (size_t)lc[p] * B;
                for (int b = 0; b < B; ++b) part[b] += av * d[b];
            }
            double* y = Y + (size_t)rows[r] * B;
            for (int b = 0; b < B; ++b) y[b] += alpha * part[b];
        }
    }

    // un-scatter: restore the all-zero invariant, O(|D|*B).
    for (size_t i = 0; i < n; ++i) {
        const int c = cols[i];
        const int t = c / tile;
        const size_t k = (size_t)(std::lower_bound(s.ct.begin(), s.ct.end(), t) - s.ct.begin());
        double* d = scratch + s.base[k] + (size_t)(c % tile) * B;
        for (int b = 0; b < B; ++b) d[b] = 0.0;
    }
}

inline void bs_apply_dynamic(BSOperator& op, const BSPerTile& s, const int* cols,
                             size_t n, const double* dx, int B, double* Y,
                             double alpha, ScratchPool& pool) {
    double* scratch = pool.get(s.scratch_len);
    const int tile = s.tile;
    for (size_t i = 0; i < n; ++i) {
        const int c = cols[i];
        const size_t k = (size_t)(std::lower_bound(s.ct.begin(), s.ct.end(), c / tile) - s.ct.begin());
        double* d = scratch + s.base[k] + (size_t)(c % tile) * B;
        for (int b = 0; b < B; ++b) d[b] = dx[i * (size_t)B + b];
    }
    std::vector<double> part((size_t)B);
    for (size_t i = 0; i < s.ct.size(); ++i) {
        const Segment& g = op.segment(s.ct[i]);
        const double* base = scratch + s.base[i];
        for (size_t r = 0; r < g.rows.size(); ++r) {
            std::fill(part.begin(), part.end(), 0.0);
            const int32_t e0 = g.start[r], e1 = g.start[r] + g.len[r];
            for (int32_t p = e0; p < e1; ++p) {
                const double av = g.val[p];
                const double* d = base + (size_t)g.lc[p] * B;
                for (int b = 0; b < B; ++b) part[b] += av * d[b];
            }
            double* y = Y + (size_t)g.rows[r] * B;
            for (int b = 0; b < B; ++b) y[b] += alpha * part[b];
        }
    }
    for (size_t i = 0; i < n; ++i) {
        const int c = cols[i];
        const size_t k = (size_t)(std::lower_bound(s.ct.begin(), s.ct.end(), c / tile) - s.ct.begin());
        double* d = scratch + s.base[k] + (size_t)(c % tile) * B;
        for (int b = 0; b < B; ++b) d[b] = 0.0;
    }
}

inline void bs_apply(BSOperator& op, const BSPerTile& s, const int* cols, size_t n,
                     const double* dx, int B, double* Y, double alpha,
                     ScratchPool& pool) {
    switch (B) {
        case 1:  bs_apply_w<1>(op, s, cols, n, dx, Y, alpha, pool);  break;
        case 2:  bs_apply_w<2>(op, s, cols, n, dx, Y, alpha, pool);  break;
        case 4:  bs_apply_w<4>(op, s, cols, n, dx, Y, alpha, pool);  break;
        case 8:  bs_apply_w<8>(op, s, cols, n, dx, Y, alpha, pool);  break;
        case 16: bs_apply_w<16>(op, s, cols, n, dx, Y, alpha, pool); break;
        default: bs_apply_dynamic(op, s, cols, n, dx, B, Y, alpha, pool);
    }
}

// ---------------------------------------------------------------- merged arm

// The same tiles, emitted as ONE array in which each distinct output row appears
// exactly once and accumulates from every live tile that feeds it. Cheaper to
// walk (one read-modify-write of y per row instead of one per feeding tile),
// and it must be re-emitted from scratch whenever the live tile set moves —
// which is the trade the Merge section measures.
struct BSMerged {
    std::vector<int>     rows;          // distinct output rows, sorted
    std::vector<int32_t> start, len;
    // Scratch offset of each entry, already multiplied by B. uint32_t rather
    // than size_t: the scratch is |CT| * tile * B doubles, so 8-byte offsets
    // would quadruple this array's memory traffic against the per-tile arm's
    // 2-byte local columns. An earlier version using size_t offsets ran
    // several times SLOWER than the per-tile form on a frozen set, where it
    // touches strictly fewer output rows and should have been ahead: the index
    // width alone was deciding the Merge section's comparison. No figure is
    // quoted for it here, because it was one uncontrolled diagnostic rather
    // than a measurement carrying its machine, compiler and motion model.
    // Read it as a warning about index width, not as a result. `bs_merge`
    // checks the bound rather than assuming it.
    std::vector<uint32_t> off;
    std::vector<double>  val;
    std::vector<int>     ct;
    std::vector<size_t>  base;
    int    B = 0, tile = 0;
    size_t scratch_len = 0;
    long   compiles_paid = 0;
    long   scanned = 0;
    long   row_touches = 0;             // == rows.size(); the merged side of
                                        // the row-count identity
};

inline BSMerged bs_merge(BSOperator& op, const int* cols, size_t n, int B) {
    BSMerged m;
    m.B = B;
    m.tile = op.tile();
    m.ct = op.tiles_of(cols, n);
    const long before = op.compiles();
    m.base.resize(m.ct.size());
    size_t off = 0;
    for (size_t i = 0; i < m.ct.size(); ++i) {
        m.base[i] = off;
        off += (size_t)op.tile() * (size_t)B;
        op.segment(m.ct[i]);
    }
    m.scratch_len = off;
    if (off > (size_t)UINT32_MAX)
        throw std::overflow_error("merged arm: scratch exceeds a uint32 offset");

    struct E { int r; uint32_t off; double v; };
    std::vector<E> es;
    for (size_t i = 0; i < m.ct.size(); ++i) {
        const Segment& g = op.segment(m.ct[i]);
        m.scanned += g.nnz;
        es.reserve(es.size() + (size_t)g.nnz);
        for (size_t r = 0; r < g.rows.size(); ++r) {
            const int32_t e0 = g.start[r], e1 = g.start[r] + g.len[r];
            for (int32_t p = e0; p < e1; ++p)
                es.push_back({g.rows[r],
                              (uint32_t)(m.base[i] + (size_t)g.lc[p] * B),
                              g.val[p]});
        }
    }
    std::stable_sort(es.begin(), es.end(),
                     [](const E& a, const E& b) { return a.r < b.r; });

    m.off.reserve(es.size());
    m.val.reserve(es.size());
    int cur = -1;
    for (const E& e : es) {
        if (e.r != cur) {
            m.rows.push_back(e.r);
            m.start.push_back((int32_t)m.val.size());
            m.len.push_back(0);
            cur = e.r;
        }
        m.off.push_back(e.off);
        m.val.push_back(e.v);
        m.len.back()++;
    }
    m.row_touches = (long)m.rows.size();
    m.compiles_paid = op.compiles() - before;
    return m;
}

template <int B>
inline void bs_merged_apply_w(const BSMerged& m, const int* cols, size_t n,
                                   const double* dx, double* Y, double alpha,
                                   ScratchPool& pool) {
    double* scratch = pool.get(m.scratch_len);
    const int tile = m.tile;
    for (size_t i = 0; i < n; ++i) {
        const int c = cols[i];
        const size_t k = (size_t)(std::lower_bound(m.ct.begin(), m.ct.end(), c / tile) - m.ct.begin());
        double* d = scratch + m.base[k] + (size_t)(c % tile) * B;
        const double* src = dx + i * (size_t)B;
        for (int b = 0; b < B; ++b) d[b] = src[b];
    }
    const int32_t* st = m.start.data();
    const int32_t* ln = m.len.data();
    const uint32_t* of = m.off.data();
    const double* vv = m.val.data();
    const int* rows = m.rows.data();
    double part[B];
    for (size_t r = 0; r < m.rows.size(); ++r) {
        for (int b = 0; b < B; ++b) part[b] = 0.0;
        const int32_t e0 = st[r], e1 = st[r] + ln[r];
        for (int32_t p = e0; p < e1; ++p) {
            const double av = vv[p];
            const double* d = scratch + of[p];
            for (int b = 0; b < B; ++b) part[b] += av * d[b];
        }
        double* y = Y + (size_t)rows[r] * B;
        for (int b = 0; b < B; ++b) y[b] += alpha * part[b];
    }
    for (size_t i = 0; i < n; ++i) {
        const int c = cols[i];
        const size_t k = (size_t)(std::lower_bound(m.ct.begin(), m.ct.end(), c / tile) - m.ct.begin());
        double* d = scratch + m.base[k] + (size_t)(c % tile) * B;
        for (int b = 0; b < B; ++b) d[b] = 0.0;
    }
}

inline void bs_merged_apply(const BSMerged& m, const int* cols, size_t n,
                            const double* dx, int B, double* Y, double alpha,
                            ScratchPool& pool) {
    switch (B) {
        case 1:  bs_merged_apply_w<1>(m, cols, n, dx, Y, alpha, pool);  break;
        case 2:  bs_merged_apply_w<2>(m, cols, n, dx, Y, alpha, pool);  break;
        case 4:  bs_merged_apply_w<4>(m, cols, n, dx, Y, alpha, pool);  break;
        case 8:  bs_merged_apply_w<8>(m, cols, n, dx, Y, alpha, pool);  break;
        case 16: bs_merged_apply_w<16>(m, cols, n, dx, Y, alpha, pool); break;
        default: throw std::invalid_argument("merged arm: unsupported B");
    }
}

// The Merge section's quantity, as an integer identity rather than a timing:
// how many distinct
// output-row touches the per-tile emission costs, over how many the merged one
// costs. Invariant in B.
struct MergeCounts { long per_tile = 0; long merged = 0; };

inline MergeCounts merge_row_counts(BSOperator& op, const int* cols, size_t n) {
    MergeCounts c;
    const std::vector<int> ct = op.tiles_of(cols, n);
    std::vector<int> all;
    for (int t : ct) {
        const Segment& g = op.segment(t);
        c.per_tile += (long)g.rows.size();
        all.insert(all.end(), g.rows.begin(), g.rows.end());
    }
    std::sort(all.begin(), all.end());
    all.erase(std::unique(all.begin(), all.end()), all.end());
    c.merged = (long)all.size();
    return c;
}

}  // namespace bsref
