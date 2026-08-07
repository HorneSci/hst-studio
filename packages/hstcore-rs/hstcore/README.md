# hstcore

Safe Rust bindings for the **HST-core Embedded** runtime (`libhstcore`).

This crate is a binding, not an engine. The library that does the work,
`libhstcore`, is **not included**. In an HST Studio download it is already in
`bin/` (`libhstcore.so` / `libhstcore.dylib`), Apache-2.0, unmetered, and needs
no key, token or account — pass its path to `Library::open_at`. A separate,
metered build of the same library also exists as its own artifact — that is not
"the Enterprise build", which is Profile 1 plus Profile 3 and has never been
built. Without any library
loaded, every entry point returns `Error::Load`. If you wanted an open sparse
delta-matvec you can run today, see
[`spdelta`](../../spdelta) instead — it ships in this same download.
(This linked a `github.com/HorneSci/spdelta` that does not exist until 2026-08-06,
for a package the reader already had.)

This README called the library "closed-source ... under a signed license"
until 2026-08-06, which was true of the metered build and false of the
community one shipped beside this crate in the same tree.

What this crate adds over calling the C API directly is that two rules
`hstcore.h` can only state in comments — the state pointer is invalidated by the
next apply, and shadow and production applies must never be interleaved on one
handle — become compile errors:

```rust
let y = session.state();          // borrows the session
session.apply(&cols, &vals)?;     // &mut self: does not compile
```

```rust
let mut shadow = session.into_shadow();   // consumes the session
session.apply(&cols, &vals)?;             // moved: does not compile
```

Sessions are closed by `Drop` and are neither `Send` nor `Sync`.

Full documentation, the honest scope, and what is untestable without a license:
see the [workspace README](https://github.com/HorneSci/hstcore-rs).
