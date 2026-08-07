#ifndef HST_ASSERT_REL_HPP
#define HST_ASSERT_REL_HPP

// assert_rel.hpp -- the minimum machinery to make a probe's exit code mean
// something. Many probes in learn/ compute a correctness value (a rel-L2, a
// max-abs-diff, a parity flag) and print it, but never gate on it -- so a
// harness with clean, well-formed timings can be silently wrong and the run
// still exits 0. This header does not replace a real non-accumulating
// reference arm; it is just the plumbing so that once you have one, a
// violation is impossible to miss and impossible to ignore.
//
// Usage:
//   #include "include/assert_rel.hpp"   // path relative to learn/
//   ...
//   double rel = rel_l2(y, y_ref);
//   hst_check_rel("hst_p3 vs from-scratch", rel, 1e-9);
//   ...
//   return hst_checks_exit();   // 0 if every check passed, 1 otherwise
//
// Dependency-free: <cstdio> and <cmath> only. No global state beyond one
// pass/fail flag, so it is safe to include from multiple translation units
// that never link together (every probe here is a standalone binary).

#include <cmath>
#include <cstdio>

namespace hst_assert {
inline bool& fail_flag() {
    static bool failed = false;
    return failed;
}
}  // namespace hst_assert

// Prints PASS/FAIL for one named relative-error check and records the
// failure. `rel` should already be a non-negative error metric (rel-L2,
// max-abs-diff, whatever the caller computed); this does not compute it for
// you -- it only judges and reports it. Returns true if the check passed, so
// call sites that want to short-circuit can do
// `if (!hst_check_rel(...)) return 1;` instead of waiting for
// hst_checks_exit() at the end.
inline bool hst_check_rel(const char* tag, double rel, double tol) {
    bool ok = std::isfinite(rel) && rel <= tol;
    std::fprintf(stderr, "[check] %-40s rel=%.3e tol=%.3e  %s\n", tag, rel, tol,
                 ok ? "PASS" : "FAIL");
    if (!ok) hst_assert::fail_flag() = true;
    return ok;
}

// Same reporting, for a check that is naturally boolean (bit-exact parity,
// an invariant that either holds or doesn't) rather than a tolerance
// comparison.
inline bool hst_check(const char* tag, bool ok) {
    std::fprintf(stderr, "[check] %-40s %s\n", tag, ok ? "PASS" : "FAIL");
    if (!ok) hst_assert::fail_flag() = true;
    return ok;
}

// Call this from main()'s `return` so a harness that never explicitly
// checked its own accumulated failures still exits non-zero on one. Safe to
// call when no check ever ran (returns 0 -- "no violation observed" is not
// the same claim as "verified", so callers should still ensure at least one
// hst_check_rel/hst_check runs before trusting a 0 exit).
inline int hst_checks_exit() { return hst_assert::fail_flag() ? 1 : 0; }

#endif  // HST_ASSERT_REL_HPP
