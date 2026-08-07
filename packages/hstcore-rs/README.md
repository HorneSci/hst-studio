# hstcore-rs

Rust bindings for the **HST-core Embedded ABI** — the thirteen `extern "C"`
functions in `hstcore.h`, ABI node `HSTCORE_1.4`. Two crates, in the usual
arrangement:

| crate | what |
|---|---|
| [`hstcore-sys`](hstcore-sys/) | the raw declarations, opened with `dlopen`. Unsafe, no invariants. |
| [`hstcore`](hstcore/) | the safe surface: sessions, lifetimes, errors. |
| `test-stub/` | a recording stub used by the tests. Not published, computes nothing. |

## Who this is for

These are **bindings, not an engine**. The code that does the work is
`libhstcore`, a shared library these crates do not contain, bundle no fallback
for, and compute nothing without. Build them without one and everything
returns `Error::Load`.

**If you got this inside an HST Studio download, the library is already
there** — `bin/libhstcore.so` or `bin/libhstcore.dylib`, next to these crates.
It is Apache-2.0, unmetered, and needs no key, token or account. Pass its path
to `Library::open_at` and everything above runs. A separate, metered build of
the same library exists as its own artifact.

**That metered build is not "the Enterprise build", and there isn't one.**
Enterprise is defined as Profile 1 plus Profile 3; Profile 3 is research code
and no such library has been built, so nothing here is a paid artifact you
could be sold today. This section called the metered build "a separate, metered
enterprise build" until 2026-08-06, which would have a prospect asking to buy
something the root README then tells them does not exist — the worse of the two
orders to find that out in.

This section also said the day-one user count was "zero by construction" and
"the set of people holding a license" until 2026-08-06 — true of the metered
build, false of the community one shipped beside these crates in the same
tree.

They exist so an integration is a `Cargo.toml` line rather than a hand-rolled
`dlopen` block — and, more usefully, so that two rules the C header can only
state in comments become things the compiler refuses to build.

**If you arrived here by mistake** and wanted a sparse delta-matvec you can
actually run: [`spdelta`](../spdelta), which ships two directories away in this
same download — open, Apache-2.0, and deliberately the *baseline* rather than a
product. (This linked `github.com/HorneSci/spdelta` until 2026-08-06, a
repository that does not exist, for a package the reader already had.)

## The argument for a Rust binding, specifically

`hstcore.h` says, in prose:

> `hst_state` — valid until the next `hst_apply_delta` / `hst_set_state` /
> `hst_close`.
>
> **WARNING:** shares held state with `hst_apply_delta` on the same handle.
> Never interleave shadow and production applies on one `hst_ctx`.

In C those are comments. Here they are the type system, at no runtime cost:

```rust
let y = session.state();          // borrows the session
session.apply(&cols, &vals)?;     // takes &mut self — will not compile
println!("{}", y[0]);
```

```rust
let mut shadow = session.into_shadow();   // consumes the production session
session.apply(&cols, &vals)?;             // moved — will not compile
```

`state()` returns `&[f64]` borrowed from `&self`; every operation the header
lists as invalidating takes `&mut self`, and `close` is `Drop`. So the
invalidation rule is enforced by the borrow checker rather than by the reader's
memory. `into_shadow` takes `self` by value, so the two apply kinds cannot be
interleaved on one handle — there is no route back, and none should exist.
Sessions are also neither `Send` nor `Sync`, because the ABI asks for one handle
per thread and the held state is unsynchronized.

Those three rules are not just documented — they are tested by invoking `rustc`
on snippets and asserting the error codes it emits (`E0502`, `E0382`, `E0277`),
with a snippet that *must* compile as the control. A `compile_fail` doctest
alone would not do: it passes when the snippet fails for any reason at all, and
`rustdoc` does not enforce the error code such a block is pinned to. That was
measured here, not assumed.

## Depend on it

**From this tree.** These crates are not on crates.io — nothing here is published
to a registry yet, so `cargo add hstcore` resolves to a different crate or to
nothing. Point Cargo at the copy you already have:

```bash
cargo add --path ./packages/hstcore-rs/hstcore    # from your HST Studio download
```

or, in `Cargo.toml`:

```toml
[dependencies]
hstcore = { path = "/path/to/hst-studio/packages/hstcore-rs/hstcore" }
```

A crates.io coordinate is intended but does not exist today; when it does, this
README will name it.

## Use

```rust
use hstcore::Library;

// Safety: loading a shared library runs its initializers.
let lib = unsafe { Library::open_at("/opt/hst/libhstcore.so")? };
let mut session = lib.open("op.bin".as_ref(), &token)?;

let cols: Vec<i32> = (0..32).collect();
let mut vals = vec![0.0f64; 32];

for step in 0..steps {
    fill(&mut vals, step);
    session.apply(&cols, &vals)?;     // slices go straight to C, no copy
    let y = session.state();          // zero-copy borrow
    publish(&y[..8]);
}

let mut reference = vec![0.0; session.state_len()];
session.recompute_full(&mut reference)?;   // unmetered reference arm
```

Batched (`1..=32` lanes, interleaved as `vals[i * batch + lane]`):

```rust
let mut session = lib.open_batched("op.bin".as_ref(), &token, 16)?;
let vals = vec![0.0f64; 32 * 16];
session.apply(&cols, &vals)?;
```

Run the worked example against a real library:

```bash
cargo run --example hot_loop -- /opt/hst/libhstcore.so op.bin "$(cat prod.license)"
```

## Tests

```bash
cargo test --workspace     # 51 tests. --workspace matters: it builds the stub.
cargo clippy --workspace --all-targets
```

**No test needs, or stands in for, a real `libhstcore`.** They split three
ways:

* pure unit tests — the return-code map, the message content;
* compile-rule tests — `rustc` invoked on snippets, asserting `E0502` / `E0382`
  / `E0277` / a lifetime error, plus a control snippet that must compile;
* FFI tests against `test-stub`, a `cdylib` exporting the thirteen ABI symbols
  that records the pointers it was handed and returns codes on demand.

The stub **computes no delta mathematics, and must not be made to.** It tests
plumbing. A fake that half-emulated the engine would teach readers a wrong
expectation about a product they have not bought, and would let a binding bug
hide behind plausible-looking output.

So the following are **not tested here, and cannot be** without a real library:
that the delta path produces the same numbers as `recompute_full`; that metering
behaves as documented and `-3` arrives when a budget is spent (a metered build,
which is not the one in `bin/`); that
`-4` is really what an ungranted token returns; that the state pointer stays
valid for exactly as long as the header claims; that `hst_recompute_full` really
leaves the held state alone (this crate takes `&self` there on the strength of
that sentence alone); real batched lane interleaving; performance of any kind.

## License

Apache-2.0 for these bindings — and, in an HST Studio download, Apache-2.0 for the
library they bind. `bin/libhstcore.so` / `bin/libhstcore.dylib` ships under the same
terms as these crates: production use, modification and redistribution permitted, no
key, no token, no meter, no expiry. Only the separate metered build carries terms of
its own, and it is not what you have.

This section said the library was "licensed separately and is not covered by it"
until 2026-08-06 — contradicting the head of this same README, which had already been
corrected, and contradicting the download's own root licence. A redistributor reads
this section and not that one.
