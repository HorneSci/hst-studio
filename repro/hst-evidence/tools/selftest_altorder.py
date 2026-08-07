#!/usr/bin/env python3
"""Self-test for the comparison primitives. Exit code is the contract.

This package ships no pytest suite on purpose -- its stated idiom is that the
exit code IS the assertion. So this runs as a plain script and returns the
number of failures.

What it exists for: `rel_l2` and `bit_diffs` compared with `zip(a, b)`, which
stops at the shorter sequence. A truncated or zero-length vector therefore
compared as identical over whatever survived and scored perfectly --
`rel_l2([], good) == 0.0`, `bit_diffs([], good) == 0` -- so zeroing or
truncating a case's y.f64.bin produced "y bitdiff 0, rel_l2 0.000e+00" from
the verifier. The strongest possible statement of correctness, made over no
data.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from altorder import bit_diffs, rel_l2  # noqa: E402

GOOD = [1.0, 2.0, 3.0, 4.0]
failures = 0


def expect_refused(fn, a, b, label):
    global failures
    try:
        got = fn(a, b)
    except ValueError:
        print(f"  ok      {label}: refused")
        return
    failures += 1
    print(f"  FAIL    {label}: returned {got!r} instead of refusing")


def expect_value(fn, a, b, want, label):
    global failures
    try:
        got = fn(a, b)
    except ValueError as exc:
        failures += 1
        print(f"  FAIL    {label}: refused a legitimate comparison ({exc})")
        return
    if got != want:
        failures += 1
        print(f"  FAIL    {label}: got {got!r}, want {want!r}")
    else:
        print(f"  ok      {label}: {got!r}")


print("altorder comparison primitives")
for fn, name in ((rel_l2, "rel_l2"), (bit_diffs, "bit_diffs")):
    expect_refused(fn, [], GOOD, f"{name}(empty, good)")
    expect_refused(fn, GOOD[:1], GOOD, f"{name}(truncated, good)")
    expect_refused(fn, GOOD + [5.0], GOOD, f"{name}(too long, good)")

# The controls. Without these a function that refused EVERYTHING would pass
# every check above, which is the same defect in the other direction.
expect_value(rel_l2, GOOD, GOOD, 0.0, "rel_l2(good, good)")
expect_value(bit_diffs, GOOD, GOOD, 0, "bit_diffs(good, good)")
expect_value(bit_diffs, [1.0, 2.0, 3.0, 9.0], GOOD, 1, "bit_diffs(one flipped, good)")

print(f"\n{failures} failed")
sys.exit(1 if failures else 0)
