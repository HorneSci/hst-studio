# hstcore (Python)

Python bindings for the **HST-core Embedded ABI** — the thirteen `extern "C"`
functions in `hstcore.h`, ABI node `HSTCORE_1.4`.

## Who this is for

`hstcore` is a **binding, not an engine**. The code that does the work is
`libhstcore`, a shared library this package does not contain. It computes
nothing on its own and has no pure-Python fallback: point it at no library and
the first call raises `HSTLoadError`.

**If you got this inside an HST Studio download, the library is already here** —
`bin/libhstcore.so` or `bin/libhstcore.dylib`, next to this package. It is
Apache-2.0, unmetered, and needs no key, token or account. Pass its path as
`lib_path` and everything below runs.

```python
ctx = hstcore.HSTContext("operator.bin", "", batch=1, lib_path="../../bin/libhstcore.dylib")
```

This README described the library as closed-source and licence-gated until
2026-08-06, which was true of the metered build and false of the one shipped
beside it. A metered build does exist and is a separate artifact; nothing in a
Studio download asks you for a licence. It is **not** "the Enterprise build" —
Enterprise means Profile 1 plus Profile 3, Profile 3 is research code, and no
such library has been built.

This package exists so that an integration is one install and a typed,
tested surface, instead of the hundred-line `ctypes` file that used to be copied
out of the distribution tarball into each tree — a file that bound eight of the
thirteen symbols and copied its inputs on every call.

**If what you wanted was a sparse delta-matvec in pure Python**, you want
[`spdelta`](../spdelta), shipped in this same tree. It is Apache-2.0, needs only
numpy and scipy, and is deliberately the *baseline* — the honest thing to
measure a product against — rather than a product.

## What the library does

A sparse operator `A` is fixed and compiled once into an artifact. A dense state
evolves by a sparse delta each step. The library holds both, in your process,
and updates the dense output without serializing anything across a boundary.
That last part is the whole design: any process or network hop that has to carry
the dense state costs orders of magnitude more than the compute being saved, so
the only supported transport is a function call.

Whether it is *faster than your current approach* is a question about your
workload, and it is not one this README will answer for you.

## Install

**From this tree.** Nothing here is published to a registry yet, so
`pip install hstcore` resolves to nothing. Install the copy you already have,
from the root of the HST Studio download:

```bash
pip install ./packages/hstcore-py
```

That is the line `install.sh` itself runs. A PyPI coordinate is intended but does
not exist today; when it does, this README will name it.

Then point it at the library. In an HST Studio download that is `bin/libhstcore.*`
beside this package, and it needs no licence of any kind:

```python
import hstcore
hstcore.load_library("../../bin/libhstcore.dylib")   # or wherever yours lives
print(hstcore.version())
```

`load_library` is process-wide and idempotent — one library per process, because
the handles it hands out outlive any single call.

## Use

```python
import numpy as np
import hstcore

with hstcore.HSTContext("op.bin", token) as ctx:
    # Allocate once, outside the loop. The binding will not convert for you.
    cols = np.empty(32, dtype=np.int32)
    vals = np.empty(32, dtype=np.float64)

    ctx.set_state(y0)                    # optional: prime a nonzero start

    for step in stream:
        cols[:] = step.cols              # filled in place
        vals[:] = step.vals
        ctx.apply(cols, vals)            # nothing is copied, nothing marshalled
        y = ctx.state                    # zero-copy view, expires next apply
        publish(y[:8])
```

Batched (`1 <= batch <= 32` independent right-hand-side lanes under one
operator, lane-interleaved):

```python
with hstcore.HSTContext("op.bin", token, batch=16) as ctx:
    vals = np.empty((32, 16), dtype=np.float64)   # vals[i, lane]
    ctx.apply(cols, vals)
    y = ctx.state                                  # shape (output_dim, 16)
```

Checking the delta path against the from-scratch reference — the control that
belongs in any before/after comparison, and the one call the metered build never
counts either:

```python
ref = np.empty(ctx.state_size)
ctx.recompute_full(ref)
assert np.allclose(ctx.state, ref.reshape(ctx.state.shape))
```

## API

| | |
|---|---|
| `load_library(path=None)` | Load `libhstcore`. Process-wide, idempotent. |
| `version()` | The library's version string (not this package's). |
| `HSTContext(artifact, token, *, batch=1, lib_path=None)` | Open a session. |
| `.batch` `.output_dim` `.input_dim` `.state_size` `.mode` `.closed` | Read-only properties. |
| `.apply(cols, vals, *, out=None)` | Delta apply — the hot path. |
| `.apply_shadow(cols, vals, *, out=None)` | Shadow apply, same numerics. |
| `.state` | Zero-copy read-only view, expires on the next apply. |
| `.set_state(y0)` | Prime the dense state. |
| `.recompute_full(out=None)` | Full recompute. The reference arm. |
| `.close()` / `with` / `__del__` | Release the handle. Idempotent. |

**Nothing in that table is metered in a Studio download** — the community library
has the licence check and the counter compiled out, so no call decrements anything
and none of them can raise `HSTQuotaError`. This table labelled `.apply` "Metered
delta apply" until 2026-08-06, which describes the separate metered build and not
the one shipped beside it. Under that build `.apply` and `.apply_shadow` count
against the licence's quota and `.recompute_full` does not; the numerics are the
same either way.

Exceptions, all under `HSTError`: `HSTLoadError`, `HSTLicenseError`,
`HSTArgumentError` (also a `ValueError`), `HSTBufferError` (also a `TypeError`),
`HSTInternalError`, `HSTQuotaError`, `HSTShadowNotGrantedError`, `HSTModeError`,
`HSTClosedError`, `HSTStateExpiredError`.

## Four things this does that the tarball's `ctypes` shim did not

1. **All thirteen symbols are bound.** The shim bound eight. Missing were
   `hst_open_batched` and `hst_batch` — multi-lane batching, which is where the
   ABI's own documentation says the engine beats a plain exact delta —
   `hst_apply_shadow`, and `hst_recompute_full`, the unmetered from-scratch
   reference arm. A binding with no reference arm cannot be used to check
   whether the fast path is returning the right answer.

2. **Nothing is copied in the hot loop.** The shim rebuilt a `ctypes` array from
   a Python list on every call — an O(n) element-by-element copy in Python, in
   a loop whose entire premise is a sub-millisecond win, and one that would show
   up in no profile of the library. This binding takes C-contiguous numpy arrays
   of exactly `int32` / `float64` and passes their pointers. Anything else
   **raises** rather than being quietly converted: a hidden copy here is not a
   convenience, it is the measurement being destroyed. A test asserts pointer
   identity between the array you passed and the pointer C received.

3. **No phantom output buffer.** The shim allocated an `output_dim`-sized buffer
   it never used, and which would have been the wrong size under batching
   (`N`, not `N * batch`). Here, `out=None` means the dense output stays inside
   the library — the true hot-loop cost — and if you pass `out`, it is your own
   array, validated at `output_dim * batch`.

4. **Return codes stay distinct.** `-1` bad args, `-2` internal, `-3` quota
   exhausted, `-4` no shadow grant in the license: four different things to do
   about them, four exception types. The shim rendered all four as one string.

Two more things follow from that list. `hstcore.h` warns that shadow and
production applies share held buffers and must never be interleaved on one
handle — here that is `HSTModeError`, raised before the call. And `hst_state`
returns a pointer valid only until the next apply; a plain numpy array over it
keeps working after the memory moves on, and reports wrong numbers that look
right. `.state` is version-stamped and raises `HSTStateExpiredError` instead.

## Tests

```bash
python -m pytest            # 121 tests, ~0.5s
```

**No test needs, or stands in for, a real `libhstcore`.** Most need no
library at all: argument and dtype enforcement, the state-view guard, the
shadow/production separation, the return-code map, the symbol table. The rest
load `tests/stub/hst_stub.c`, a recording stub compiled at test time, which
counts calls, records the pointers it was handed, and returns codes on demand.

That stub **computes no delta mathematics, and must not be made to.** It is
there to test plumbing. A fake that half-emulated the engine would teach every
reader of these tests a wrong expectation about a product they have not bought,
and would let a binding bug hide behind plausible-looking output.

So the following are **not tested here, and cannot be** without a real library:
that the delta path produces the same numbers as `recompute_full`; that metering
decrements as documented and `-3` arrives when the budget is spent (a metered
build, which is not the one in `bin/`); that a `-4` really is what an unshadowed
token returns; that the state pointer
survives exactly as long as the header says; that `hst_recompute_full` really
leaves the held state alone (this binding assumes it, and does not expire the
state view across it); real batched lane interleaving; performance of any kind.
Run those against the real library before relying on any of them.

## License

Apache-2.0 for this binding — and, in an HST Studio download, Apache-2.0 for the
library it binds. `bin/libhstcore.so` / `bin/libhstcore.dylib` ships under the same
terms as this package: production use, modification and redistribution permitted,
no key, no token, no meter, no expiry. Only the separate metered build carries
terms of its own, and it is not what you have.

This section said the library was "separately licensed and is not covered by it"
until 2026-08-06 — contradicting the head of this same README, which had already
been corrected, and contradicting the download's own root licence. A redistributor
reads this section and not that one.
