# HorneSci.Hstcore

**.NET binding for the HST-core Embedded ABI** (`HSTCORE_1.4`) — thirteen `extern "C"`
functions, bound with `LibraryImport` source generation.

```bash
# from your own project, against the copy in your HST Studio download:
dotnet add reference ./packages/hstcore-dotnet/src/Hstcore/Hstcore.csproj
```

.NET 9 or newer. **Nothing here is published to a registry yet**, so
`dotnet add package HorneSci.Hstcore` finds nothing on nuget.org — reference the
project in this tree instead. A NuGet coordinate is intended but does not exist
today; when it does, this README will name it.

---

## Read this first

**This package computes nothing.** The work is done by `libhstcore`, a shared library
this package does not contain. In an HST Studio download the library is already in
`bin/` (`libhstcore.so` / `libhstcore.dylib`), Apache-2.0, unmetered, and needs no key,
token or account — copy it (or set `DYLD_LIBRARY_PATH` / `LD_LIBRARY_PATH` / `PATH`) so
the runtime's native resolver can find it as `hstcore`, since `bin/` is not on that
search path by default. A separate, metered build of the same library exists as its own
artifact, and that is the one `Session.Open`'s licence token gates. There is no
evaluation fallback and no pure-managed path.

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

```csharp
using var s = Session.Open("operator.hst", licenceToken, batch: 8);

s.SetInput(x0);                       // InputSize  == InputDim  * Batch
s.SetState(y0);                       // StateSize  == OutputDim * Batch

double[] y = s.ApplyDelta(dirtyCols, deltaVals);
```

`Dispose` is idempotent and use after dispose is refused rather than passed to the native
side. Length mismatches throw before the call: a wrong buffer length at an FFI boundary is
an access violation, not an exception.

⚠️ **A `Session` is one mutable cursor over library-owned memory, and it is not
thread-safe.** Give each thread its own, or guard one with a lock. This matters more here
than the API suggests: `ApplyDelta` is synchronous, so the natural `Task.Run` fan-out over
a shared `Session` is exactly the wrong shape and produces wrong numbers rather than an
exception.

⚠️ **There is no async overload, on purpose.** The win this library exists to deliver is
per-call overhead, and a state machine plus a thread hop costs more than the call. If your
path needs async, the boundary belongs further out.

⚠️ **Batching is not free parallelism.** The `batch` lanes share one operator *and* one
delta sparsity pattern — independent right-hand sides, not independent keys. At
`batch: 1` HST frequently loses to a plain exact column delta. Measure.

## Whether it will help you at all

HST needs a **fixed operator**, a **sparse delta**, **tile-local** dirty columns, and a
hot path that is a **matrix-vector product rather than a linear solve**. Outside that
envelope it loses, sometimes badly, and a badly fitted deployment is a pessimization.
This binding cannot tell you which side you are on; `spdelta` can, in about a minute.

## Thirteen, not twelve

The authority is [`../hstcore-abi/abi.json`](../hstcore-abi/abi.json), derived from the
linker's version map. A library missing `hst_apply_shadow` or `hst_set_input` is a
**stale build** from before the 1.3 → 1.4 bump, not a different ABI.

The **shared** conformance stub (`../hstcore-abi/conformance/build-stub.sh`) reports a
deliberately non-square operator (`n=8`, `m=5`), so a binding that confuses `OutputDim`
with `InputDim` fails instead of passing.

## Licence

Apache-2.0 for this binding — and, in an HST Studio download, Apache-2.0 for `libhstcore`
too. The library in `bin/` ships under the same terms as this package: production use,
modification and redistribution permitted, no key, no token, no meter, no expiry. Only
the separate metered build carries terms of its own, and it is not what you have.

This section said `libhstcore` "is not covered by it and comes with its own terms" until
2026-08-06 — contradicting *Read this first* at the top of this same README, which had
already been corrected, and contradicting the download's own root licence. A
redistributor reads this section and not that one.
