# hstcore-go

**Go binding for the HST-core Embedded ABI** (`HSTCORE_1.4`) — thirteen `extern "C"`
functions, bound with cgo.

```bash
# from your own module, against the copy in your HST Studio download:
go mod edit -replace github.com/HorneSci/hstcore-go=/path/to/hst-studio/packages/hstcore-go
go mod edit -require github.com/HorneSci/hstcore-go@v0.0.0
go mod tidy
```

Go 1.23 or newer, and cgo enabled (`CGO_ENABLED=1`). This binding cannot work with cgo
off — the whole package is the boundary.

**`go get github.com/HorneSci/hstcore-go` does not work yet**: that repository does not
exist, because nothing here is published. The `replace` directive above points the same
import path at the directory you already have, so your source needs no change when the
module is published. When it is, this README will say so.

---

## Read this first

**This package computes nothing.** The work is done by `libhstcore`, a shared library
this package does not link against by default. In an HST Studio download the library is
already in `bin/` (`libhstcore.so` / `libhstcore.dylib`), Apache-2.0, unmetered, and
needs no key, token or account — point `CGO_LDFLAGS`/`LIBRARY_PATH` at `bin/`, since it
is not on the linker's default search path. A separate, metered build of the same library
exists as its own artifact, and that is the one `Open`'s licence token gates. There is
no evaluation fallback and no pure-Go path.

**That metered build is not "the Enterprise build", and there isn't one.** Enterprise is
defined as Profile 1 plus Profile 3; Profile 3 is research code and no such library has
been built, so nothing here is a paid artifact you could be sold today. This section
called the metered build "a separate, metered enterprise build" until 2026-08-06, which
would have a prospect asking to buy something the root README then tells them does not
exist — the worse of the two orders to find that out in.

This section also described `libhstcore` as closed-source and licence-gated across the
board until 2026-08-06, which was true of the metered build and false of the community
one shipped beside this binding in the same tree.

**If what you want is a sparse delta matvec you can actually run**, you want
[`spdelta`](../spdelta) — Apache-2.0, open, and deliberately the *baseline*. Measure
against it before buying anything.

## Use

```go
s, err := hstcore.OpenBatched("operator.hst", licenceToken, 8)
if err != nil {
    return err
}
defer s.Close()

if err := s.SetInput(x0); err != nil {   // len == InputSize()
    return err
}
if err := s.SetState(y0); err != nil {   // len == StateSize()
    return err
}

y, err := s.ApplyDelta(dirtyCols, deltaVals)
```

`Close` is idempotent and use after close is refused rather than passed to the native
side. Length mismatches come back as errors: a wrong buffer length at an FFI boundary is
a segfault, not a panic you can recover from, so the check happens before the call.

⚠️ **A `Session` is one mutable cursor over library-owned memory, and it is not
goroutine-safe.** Give each goroutine its own, or guard one with a mutex. Sharing without
either produces wrong numbers rather than a race detector hit on the library's side of
the boundary — the state two goroutines are interleaving lives in C memory the detector
does not see.

⚠️ **`ApplyDelta` blocks the OS thread** for the duration of the cgo call, and the Go
scheduler cannot preempt it. On a large operator that is a real scheduling cost, not just
a latency one.

⚠️ **Batching is not free parallelism.** The `batch` lanes share one operator *and* one
delta sparsity pattern — independent right-hand sides, not independent keys. At
`batch == 1` HST frequently loses to a plain exact column delta. Measure.

## Whether it will help you at all

HST needs a **fixed operator**, a **sparse delta**, **tile-local** dirty columns, and a
hot path that is a **matrix-vector product rather than a linear solve**. Outside that
envelope it loses, sometimes badly, and a badly fitted deployment is a pessimization.
This binding cannot tell you which side you are on; `spdelta` can, in about a minute.

## Thirteen, not twelve

The authority is [`../hstcore-abi/abi.json`](../hstcore-abi/abi.json), derived from the
linker's version map. A library missing `hst_apply_shadow` or `hst_set_input` is a
**stale build** from before the 1.3 → 1.4 bump, not a different ABI.

```bash
../hstcore-abi/conformance/build-stub.sh && go test ./...
```

runs against the **shared** conformance stub, which reports a deliberately non-square
operator (`n=8`, `m=5`) so a binding that confuses `OutputDim` with `InputDim` fails
instead of passing.

## Licence

Apache-2.0 for this binding — and, in an HST Studio download, Apache-2.0 for `libhstcore`
too. The library in `bin/` ships under the same terms as this package: production use,
modification and redistribution permitted, no key, no token, no meter, no expiry. Only
the separate metered build carries terms of its own, and it is not what you have.

This section said `libhstcore` "is not covered by it and comes with its own terms" until
2026-08-06 — contradicting *Read this first* at the top of this same README, which had
already been corrected, and contradicting the download's own root licence. A
redistributor reads this section and not that one.
