// blocksched_selftest.cpp — standalone correctness driver for blocksched_ref.hpp.
//
// Stdlib only. No build system, no test framework, no dependencies:
//
//     g++-13 -O3 -std=c++17 -DNDEBUG blocksched_selftest.cpp -o blocksched_selftest
//     ./blocksched_selftest
//
// Every check recomputes the answer FROM SCRATCH — a direct evaluation over the
// CSC columns, touching no segment, no scratch and no cache — and compares. A
// harness with no non-accumulating reference arm cannot tell you that its arms
// saw the right inputs; three defects on one probe in this project produced
// clean, well-formed timings because each arm did the right *amount* of work on
// wrong values. So the reference here is deliberately the dumbest possible
// implementation of the same mathematics.
//
// What is checked
//   1. per-tile emission == direct evaluation, at every B the fixed-width
//      kernels cover (1, 2, 4, 8, 16) and at a B that falls through to the
//      dynamic-width path (3);
//   2. merged emission == direct evaluation, same widths;
//   3. a preparation stays exact for ANY dirty set inside the tiles it was
//      prepared for — the family's defining property, and the one a stale-cache
//      bug would break as a suspiciously good churn number rather than as a
//      wrong answer;
//   4. the scratch is all-zero on entry AND on exit, which is what makes the
//      zero-fill O(|D|*B) instead of O(M*B);
//   5. re-preparation charges only tiles never seen before, and zero on a
//      repeat — the cheap-re-preparation claim, as a counter rather than a
//      timing;
//   6. merge_row_counts against an independent recount over a std::set.
//
// Exit code is the number of failed checks. It is what `main` returns, because
// a check that does not gate the exit code is a check on paper.

#include "blocksched_ref.hpp"

#include <cmath>
#include <cstdio>
#include <random>
#include <set>
#include <vector>

namespace {

int failures = 0;
int checks   = 0;

void check(const char* tag, bool ok, const char* detail = "") {
    ++checks;
    if (!ok) {
        ++failures;
        std::printf("  FAIL  %-52s %s\n", tag, detail);
    } else {
        std::printf("  ok    %-52s %s\n", tag, detail);
    }
}

void check_rel(const char* tag, double rel, double tol = 1e-12) {
    char buf[64];
    std::snprintf(buf, sizeof buf, "rel=%.3e tol=%.0e", rel, tol);
    check(tag, rel <= tol && !std::isnan(rel), buf);
}

// ---- a reproducible random sparse operator, in CSC ------------------------

bsref::CscView make_csc(int N, int M, int nnz_per_col, unsigned seed) {
    std::mt19937 rng(seed);
    std::uniform_int_distribution<int> row(0, N - 1);
    std::uniform_real_distribution<double> v(-1.0, 1.0);

    bsref::CscView A;
    A.N = N;
    A.M = M;
    A.ptr.assign(M + 1, 0);
    for (int c = 0; c < M; ++c) {
        std::set<int> rows;
        while ((int)rows.size() < nnz_per_col) rows.insert(row(rng));
        for (int r : rows) {
            A.row.push_back(r);
            A.val.push_back(v(rng));
        }
        A.ptr[c + 1] = (int)A.row.size();
    }
    return A;
}

// ---- the reference arm: y += alpha * A[:, D] @ dx, from scratch -----------
//
// Walks the CSC columns of D directly. No tiles, no segments, no scratch, no
// cache. `dx` is compact: row i of the (|D| x B) block belongs to cols[i].

std::vector<double> direct(const bsref::CscView& A, const std::vector<int>& cols,
                           const std::vector<double>& dx, int B, double alpha) {
    std::vector<double> Y((size_t)A.N * B, 0.0);
    for (size_t i = 0; i < cols.size(); ++i) {
        const int c = cols[i];
        for (int p = A.ptr[c]; p < A.ptr[c + 1]; ++p)
            for (int b = 0; b < B; ++b)
                Y[(size_t)A.row[p] * B + b] += alpha * A.val[p] * dx[i * (size_t)B + b];
    }
    return Y;
}

double rel_l2(const std::vector<double>& a, const std::vector<double>& b) {
    double num = 0.0, den = 0.0;
    for (size_t i = 0; i < a.size(); ++i) {
        const double d = a[i] - b[i];
        num += d * d;
        den += b[i] * b[i];
    }
    return den > 0.0 ? std::sqrt(num / den) : std::sqrt(num);
}

std::vector<int> dirty_set(int M, size_t n, unsigned seed) {
    std::mt19937 rng(seed);
    std::uniform_int_distribution<int> col(0, M - 1);
    std::set<int> s;
    while (s.size() < n) s.insert(col(rng));
    return std::vector<int>(s.begin(), s.end());
}

std::vector<double> random_dx(size_t n, int B, unsigned seed) {
    std::mt19937 rng(seed);
    std::uniform_real_distribution<double> v(-1.0, 1.0);
    std::vector<double> dx(n * (size_t)B);
    for (double& x : dx) x = v(rng);
    return dx;
}

}  // namespace

int main() {
    const int N = 4096, M = 4096, TILE = 64;
    bsref::CscView A = make_csc(N, M, 12, 20260804u);
    const double alpha = 0.75;

    std::printf("blocksched_ref self-test  N=%d M=%d tile=%d nnz=%zu\n\n",
                N, M, TILE, A.row.size());

    // ---- 1 & 2: both emissions against a from-scratch recompute ----------
    std::printf("exactness against a direct evaluation\n");
    for (int B : {1, 2, 3, 4, 8, 16}) {
        bsref::BSOperator op(A, TILE);
        bsref::ScratchPool pool;
        const std::vector<int> D = dirty_set(M, 256, 7u + (unsigned)B);
        const std::vector<double> dx = random_dx(D.size(), B, 11u + (unsigned)B);
        const std::vector<double> want = direct(A, D, dx, B, alpha);

        std::vector<double> got((size_t)N * B, 0.0);
        bsref::BSPerTile s = bsref::bs_prepare(op, D.data(), D.size(), B);
        bsref::bs_apply(op, s, D.data(), D.size(), dx.data(), B, got.data(), alpha, pool);
        char tag[80];
        std::snprintf(tag, sizeof tag, "per-tile emission, B=%d", B);
        check_rel(tag, rel_l2(got, want));

        // the merged arm has no dynamic-width path, by design
        if (B != 3) {
            std::vector<double> gotm((size_t)N * B, 0.0);
            bsref::BSMerged m = bsref::bs_merge(op, D.data(), D.size(), B);
            bsref::bs_merged_apply(m, D.data(), D.size(), dx.data(), B, gotm.data(),
                                   alpha, pool);
            std::snprintf(tag, sizeof tag, "merged emission,  B=%d", B);
            check_rel(tag, rel_l2(gotm, want));
        }
    }

    // ---- 3: a preparation is valid for any dirty set inside its tiles ----
    std::printf("\nthe family's defining property\n");
    {
        const int B = 8;
        bsref::BSOperator op(A, TILE);
        bsref::ScratchPool pool;

        // prepare for the whole of four tiles, then apply to subsets of them
        std::vector<int> wide;
        for (int t : {3, 11, 40, 57})
            for (int c = t * TILE; c < (t + 1) * TILE; ++c) wide.push_back(c);
        bsref::BSPerTile s = bsref::bs_prepare(op, wide.data(), wide.size(), B);

        double worst = 0.0;
        for (unsigned trial = 0; trial < 8; ++trial) {
            std::mt19937 rng(900u + trial);
            std::vector<int> D;
            for (int c : wide)
                if (rng() % 3 == 0) D.push_back(c);
            if (D.empty()) continue;
            const std::vector<double> dx = random_dx(D.size(), B, 300u + trial);
            const std::vector<double> want = direct(A, D, dx, B, alpha);
            std::vector<double> got((size_t)N * B, 0.0);
            bsref::bs_apply(op, s, D.data(), D.size(), dx.data(), B, got.data(),
                            alpha, pool);
            worst = std::max(worst, rel_l2(got, want));
        }
        check_rel("stale preparation stays exact on moved subsets", worst);
    }

    // ---- 4: the scratch invariant ---------------------------------------
    std::printf("\nthe scratch invariant that keeps the zero-fill O(|D|*B)\n");
    {
        const int B = 8;
        bsref::BSOperator op(A, TILE);
        bsref::ScratchPool pool;
        const std::vector<int> D = dirty_set(M, 300, 42u);
        const std::vector<double> dx = random_dx(D.size(), B, 43u);
        bsref::BSPerTile s = bsref::bs_prepare(op, D.data(), D.size(), B);
        check("scratch all-zero before the first apply", pool.all_zero(s.scratch_len));
        std::vector<double> got((size_t)N * B, 0.0);
        bsref::bs_apply(op, s, D.data(), D.size(), dx.data(), B, got.data(), alpha, pool);
        check("scratch all-zero after apply (un-scatter restored it)",
              pool.all_zero(s.scratch_len));

        // and a second apply must therefore reproduce the first exactly
        std::vector<double> again((size_t)N * B, 0.0);
        bsref::bs_apply(op, s, D.data(), D.size(), dx.data(), B, again.data(), alpha, pool);
        check_rel("second apply reproduces the first bit for bit", rel_l2(again, got), 0.0);
    }

    // ---- 5: re-preparation charges only unseen tiles ---------------------
    std::printf("\nre-preparation, as a counter rather than a timing\n");
    {
        const int B = 8;
        bsref::BSOperator op(A, TILE);
        const std::vector<int> D1 = dirty_set(M, 64, 5u);
        bsref::BSPerTile s1 = bsref::bs_prepare(op, D1.data(), D1.size(), B);
        check("first preparation compiles every tile it touches",
              s1.compiles_paid == (long)s1.ct.size());

        bsref::BSPerTile s2 = bsref::bs_prepare(op, D1.data(), D1.size(), B);
        check("re-preparing the same dirty set compiles nothing",
              s2.compiles_paid == 0);

        // a dirty set inside the same tiles: still nothing to compile
        std::vector<int> inside;
        for (int t : s1.ct) inside.push_back(t * TILE);
        bsref::BSPerTile s3 = bsref::bs_prepare(op, inside.data(), inside.size(), B);
        check("movement inside covered tiles compiles nothing",
              s3.compiles_paid == 0);

        // a genuinely new tile costs exactly one
        const long before = op.compiles();
        int fresh = -1;
        for (int t = 0; t < op.n_tiles(); ++t)
            if (!op.cached(t)) { fresh = t; break; }
        std::vector<int> one{fresh * TILE};
        bsref::bs_prepare(op, one.data(), one.size(), B);
        check("one unseen tile costs exactly one compile",
              op.compiles() - before == 1);
    }

    // ---- 6: the merge identity, recounted independently ------------------
    std::printf("\nthe row-count identity\n");
    {
        bsref::BSOperator op(A, TILE);
        const std::vector<int> D = dirty_set(M, 200, 77u);
        bsref::MergeCounts mc = bsref::merge_row_counts(op, D.data(), D.size());

        // independent recount straight off the CSC: per-tile counts a row once
        // per feeding tile, merged counts it once overall.
        std::set<int> merged;
        long per_tile = 0;
        std::set<int> ct;
        for (int c : D) ct.insert(c / TILE);
        for (int t : ct) {
            std::set<int> here;
            for (int c = t * TILE; c < std::min((t + 1) * TILE, M); ++c)
                for (int p = A.ptr[c]; p < A.ptr[c + 1]; ++p) here.insert(A.row[p]);
            per_tile += (long)here.size();
            merged.insert(here.begin(), here.end());
        }
        char buf[96];
        std::snprintf(buf, sizeof buf, "per_tile %ld vs %ld, merged %ld vs %zu",
                      mc.per_tile, per_tile, mc.merged, merged.size());
        check("merge_row_counts matches an independent recount",
              mc.per_tile == per_tile && mc.merged == (long)merged.size(), buf);
    }

    std::printf("\n%d checks, %d failed\n", checks, failures);
    return failures;
}
