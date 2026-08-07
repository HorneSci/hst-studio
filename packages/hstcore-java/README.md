# hstcore-java

**Java binding for the HST-core Embedded ABI** (`HSTCORE_1.4`) — thirteen `extern "C"`
functions, bound with Panama, no dependencies.

```bash
cd packages/hstcore-java && mvn install     # from your HST Studio download
```

installs `com.hornesci:hstcore:1.4.0` into your local `~/.m2`, after which the
usual block resolves:

```xml
<dependency>
  <groupId>com.hornesci</groupId>
  <artifactId>hstcore</artifactId>
  <version>1.4.0</version>
</dependency>
```

**That coordinate is not on Maven Central**, and nothing here is published to a
registry yet — the `mvn install` above is what makes the block resolve. `./build.sh`
in this directory needs only `javac` if you would rather not involve Maven at all.
A published coordinate is intended; when it exists, this README will say so.

JDK 22 or newer. `java.lang.foreign` left preview in 22 (JEP 454); on 21 this does not
compile, and the error is a missing package rather than anything that explains itself.

---

## Read this first

**This package computes nothing.** The work is done by `libhstcore`, a shared library
this package does not contain. In an HST Studio download the library is already in
`bin/` (`libhstcore.so` / `libhstcore.dylib`), Apache-2.0, unmetered, and needs no key,
token or account — pass its path to `Abi.load`, since `bin/` is not on the JVM's
default library search path. A separate, metered build of the same library exists as its
own artifact, and `Session.open`'s licence token is what *that* build gates on. Install
this on its own and the first call throws. There is no evaluation fallback and no
pure-Java path.

**That metered build is not "the Enterprise build", and there isn't one.** Enterprise is
defined as Profile 1 plus Profile 3; Profile 3 is research code and no such library has
been built, so nothing here is a paid artifact you could be sold today. This section
called the metered build "a separate, metered enterprise build" until 2026-08-06, which
would have a prospect asking to buy something the root README then tells them does not
exist — the worse of the two orders to find that out in.

This section also described `libhstcore` as closed-source and licence-gated across the
board until 2026-08-06, which was true of the metered build and false of the community
one shipped beside these bindings in the same tree.

**If what you want is a sparse delta matvec you can actually run**, you want
[`spdelta`](../spdelta) — Apache-2.0, open, and deliberately the *baseline* rather than
a product. Measure against it before buying anything.

**Panama, not JNI**, deliberately: no compile step, no per-platform artifact to publish,
and no ABI of this package's own to keep in step with a library you receive separately
and may replace between releases. The boundary carries only `int32`, `double`, `size_t`
and opaque pointers.

## Fifteen minutes

### 1. Build and conformance-check with nothing but a JDK

```bash
../hstcore-abi/conformance/build-stub.sh    # a fake libhstcore, no licence needed
./build.sh
```

`build.sh` compiles with plain `javac` and runs the smoke test against the **shared**
conformance stub — the same one the Python binding tests against, so "conformance"
means the bindings agree about one library rather than each agreeing with itself. The
stub reports a deliberately non-square operator (`n=8`, `m=5`), which is what catches a
binding that confuses `outputDim` with `inputDim`: square fixtures hide that bug, and it
corrupts memory on a real operator.

Maven is the right way to *depend* on this and the wrong thing to require in order to
*check* it, so both paths exist and compile the same sources.

### 2. Against the real library

```java
import com.hornesci.hstcore.Abi;
import com.hornesci.hstcore.Session;
import java.nio.file.Path;

Abi abi = Abi.load(Path.of("/opt/hst/libhstcore.so"));   // or Abi.load() to search

try (Session s = Session.open(abi, Path.of("operator.hst"), licenceToken, 8)) {
    s.setInput(x0);                       // inputDim * batch
    s.setState(y0);                       // outputDim * batch

    // Each step: the columns that changed, and by how much.
    double[] y = s.applyDelta(dirtyCols, deltaVals);
}
```

`Session` is `AutoCloseable`, `close()` is idempotent, and use after close is refused
rather than passed to the native side. Length mismatches are rejected in Java: a wrong
buffer length at an FFI boundary is a segfault, not an exception, so the check happens
before the call.

### 3. Streaming — the shape this is usually asked about

A stream processor holds an operator that does not change and a state vector that
changes a little per record. The binding does not care where the delta came from:

```java
public final class HstAggregator implements AutoCloseable {
    private final Session session;

    HstAggregator(Abi abi, Path operator, String token, int lanes) {
        this.session = Session.open(abi, operator, token, lanes);
    }

    /** cols/vals are the keys touched by this micro-batch and their increments. */
    public double[] advance(int[] cols, double[] vals) {
        return session.applyDelta(cols, vals);
    }

    @Override public void close() { session.close(); }
}
```

⚠️ **One `Session` is one mutable cursor over library-owned memory, and it is not
thread-safe.** Give each processing thread, task slot or partition its own `Session`, or
guard one with a lock. Sharing an instance across threads without either produces wrong
numbers rather than an exception, because two threads interleaving `setState` and
`applyDelta` each see a state the other moved.

⚠️ **Batching is not free parallelism.** The `batch` lanes must share one operator *and*
one delta sparsity pattern — they are independent right-hand sides, not independent
keys. Lanes amortize the sparse index traversal, which is where HST beats a plain exact
column delta; at `batch == 1` it frequently does not. Measure before assuming.

⚠️ **This is an in-process library.** Putting it behind REST or IPC destroys the win it
exists to deliver — per-call overhead has been worth more here than every kernel change
combined. If your call path crosses a process boundary, measure that path, not this one.

## Whether it will help you at all

HST needs a **fixed operator**, a **sparse delta**, **tile-local** dirty columns, and a
hot path that is a **matrix-vector product rather than a linear solve**. Outside that
envelope it does not win less — it loses, sometimes badly, and a badly fitted deployment
is a pessimization.

Nothing about being on the JVM changes that, and this binding cannot tell you which side
of the line you are on. `spdelta` can, in about a minute, without a licence.

## Thirteen, not twelve

The commit introducing `hst_apply_shadow` described the surface as "12 total";
`exported.linux.map`, which is what the linker reads, lists thirteen. Both the Python and
Rust bindings were written from the wrong count and shipped without `hst_set_input` until
2026-08-05 — each announcing full coverage against a denominator nobody had counted.

The authority is [`../hstcore-abi/abi.json`](../hstcore-abi/abi.json), derived from the
version map and checked against the built library. A library missing `hst_apply_shadow`
or `hst_set_input` is a **stale build** from before the 1.3 → 1.4 bump, not a different
ABI, and `Abi.load` says so by name rather than failing on first use.

## Licence

Apache-2.0 for this binding — and, in an HST Studio download, Apache-2.0 for `libhstcore`
too. The library in `bin/` ships under the same terms as this package: production use,
modification and redistribution permitted, no key, no token, no meter, no expiry. Only
the separate metered build carries terms of its own, and it is not what you have.

This section said `libhstcore` "is not covered by it and comes with its own terms" until
2026-08-06 — contradicting *Read this first* at the top of this same README, which had
already been corrected, and contradicting the download's own root licence. A
redistributor reads this section and not that one.
