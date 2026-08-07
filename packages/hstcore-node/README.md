# @hornesci/hstcore

**Node binding for the HST-core Embedded ABI** (`HSTCORE_1.4`) — thirteen `extern "C"`
functions, bound through [koffi](https://koffi.dev).

```bash
npm install ./packages/hstcore-node        # from the root of your HST Studio download
```

Node 18 or newer. **Nothing here is published to a registry yet**, so
`npm install @hornesci/hstcore` returns a 404 — install the copy in this tree
instead. An npm coordinate is intended but does not exist today; when it does,
this README will name it.

---

## Read this first

**This package computes nothing.** The work is done by `libhstcore`, a shared library
this package does not contain. In an HST Studio download the library is already in
`bin/` (`libhstcore.so` / `libhstcore.dylib`), Apache-2.0, unmetered, and needs no key,
token or account — pass its path to `load()`, since `bin/` is not on koffi's default
search path. A separate, metered build of the same library exists as its own artifact,
and that is the one `Session.open`'s licence token gates. There is no evaluation fallback
and no pure-JS path.

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

```js
import { load, Session } from "@hornesci/hstcore";

const api = load("/opt/hst/libhstcore.so");        // or load() to search
const s = Session.open(api, "operator.hst", token, 8);
try {
  s.setInput(x0);                                   // inputDim * batch
  s.setState(y0);                                   // outputDim * batch
  const y = s.applyDelta(dirtyCols, deltaVals);
} finally {
  s.close();
}
```

`close()` is idempotent and use after close is refused rather than passed to the native
side. Length mismatches are rejected in JS: a wrong buffer length at an FFI boundary is a
segfault, not an exception.

⚠️ **One `Session` is one mutable cursor over library-owned memory.** Node's single
thread makes the usual race impossible, but `worker_threads` do not share it safely —
give each worker its own `Session`.

⚠️ **`applyDelta` is synchronous and blocks the event loop** for its duration. That is
the point (the win here is per-call overhead, and a queue hop would eat it), but it means
a large operator on the main thread stalls everything else. Put it on a worker if you are
also serving requests.

⚠️ **Batching is not free parallelism.** The `batch` lanes share one operator *and* one
delta sparsity pattern — independent right-hand sides, not independent keys. At
`batch === 1` HST frequently loses to a plain exact column delta. Measure.

## Whether it will help you at all

HST needs a **fixed operator**, a **sparse delta**, **tile-local** dirty columns, and a
hot path that is a **matrix-vector product rather than a linear solve**. Outside that
envelope it loses, sometimes badly, and a badly fitted deployment is a pessimization.
This binding cannot tell you which side you are on; `spdelta` can, in about a minute.

## Thirteen, not twelve

The authority is [`../hstcore-abi/abi.json`](../hstcore-abi/abi.json), derived from the
linker's version map. A library missing `hst_apply_shadow` or `hst_set_input` is a
**stale build** from before the 1.3 → 1.4 bump, not a different ABI, and `load()` says so
by name rather than failing on first use.

```bash
../hstcore-abi/conformance/build-stub.sh && npm test
```

runs the binding against the **shared** conformance stub — the same one every other
binding tests against, reporting a deliberately non-square operator (`n=8`, `m=5`) so a
binding that confuses `outputDim` with `inputDim` fails instead of passing.

## Licence

Apache-2.0 for this binding — and, in an HST Studio download, Apache-2.0 for `libhstcore`
too. The library in `bin/` ships under the same terms as this package: production use,
modification and redistribution permitted, no key, no token, no meter, no expiry. Only
the separate metered build carries terms of its own, and it is not what you have.

This section said `libhstcore` "is not covered by it and comes with its own terms" until
2026-08-06 — contradicting *Read this first* at the top of this same README, which had
already been corrected, and contradicting the download's own root licence. A
redistributor reads this section and not that one.
