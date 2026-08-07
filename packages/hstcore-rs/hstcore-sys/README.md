# hstcore-sys

Raw FFI declarations for the **HST-core Embedded ABI** — thirteen `extern "C"`
functions over an opaque handle, ABI node `HSTCORE_1.4`.

Declarations only: no safe wrappers, no invariants, no library. Everything here
is `unsafe` to call. Use [`hstcore`](../hstcore) — the safe crate beside
this one in the same tree — unless you have a reason not to. (This linked
crates.io until 2026-08-06; neither crate is published there yet.)

**`dlopen`, not linking.** `libhstcore` ships separately from any program that
uses it — as of 2026-08-06, in two forms: an Apache-2.0, unmetered community
build (in an HST Studio download's `bin/`, no key/token/account) and a
separate, metered build of the same library — and a user may swap between them or
between releases. Linking at build time would mean every downstream crate
needed a copy of one of those binaries just to compile, so the library is
opened at runtime with `libloading`; a program that never opens it never needs
it present.

**No `bindgen`.** Thirteen functions over an opaque pointer, with no structs,
enums or macros to translate. The declarations are written by hand from the
header, which costs less than a build script and keeps this crate buildable with
no `libclang` on the machine.

Apache-2.0 for these declarations — and, in an HST Studio download, Apache-2.0
for the library they describe. `bin/libhstcore.*` ships under the same terms as
this crate: production use, modification and redistribution permitted, no key,
no token, no meter. The library ships as its own artifact and a separate metered
build of it exists, which is the only one carrying terms of its own.

This said the library "is not covered by this crate's license" and named its two
forms "community or enterprise" until 2026-08-06. Both were wrong about the tree
this crate arrives in: the library beside it is Apache-2.0, and there is no
Enterprise build — that tier is Profile 1 plus Profile 3, and Profile 3 has never
been built.
