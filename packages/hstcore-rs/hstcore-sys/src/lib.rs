//! Raw FFI declarations for the **HST-core Embedded ABI** — the thirteen
//! `extern "C"` functions of `hstcore.h`, exported under ABI node
//! `HSTCORE_1.4`.
//!
//! This crate declares the surface and nothing else. There are no safe
//! wrappers, no lifetimes and no invariants enforced here; use [`hstcore`] for
//! that. Everything below is `unsafe` to call and easy to misuse — in
//! particular the pointer returned by [`Api::hst_state`] is valid only until
//! the next apply, `set_state` or `close`, and nothing in this crate stops you
//! from reading it afterwards.
//!
//! # Why `dlopen` and not linking
//!
//! `libhstcore` ships separately from any program that uses it — as of
//! 2026-08-06, in two forms: an Apache-2.0, unmetered community build (in an
//! HST Studio download's `bin/`, no key/token/account) and a separate, metered
//! build of the same library — and a user may swap between them or between releases.
//! Linking against it at build time would mean every downstream crate needed a
//! copy of one of those binaries just to compile. So the library is opened at
//! runtime with [`libloading`], and a program that never opens it never needs
//! it present.
//!
//! This doc comment said every copy was "a commercial binary" until
//! 2026-08-06, which was true of the metered build and false of the
//! community one shipped beside this crate in the same tree.
//!
//! # Why no `bindgen`
//!
//! Thirteen functions over an opaque pointer, with no structs, no enums and no
//! macros to translate. Hand-declaring them costs less than a build script and
//! keeps this crate buildable with no `libclang` on the machine.
//!
//! [`hstcore`]: https://docs.rs/hstcore

#![warn(missing_docs)]
#![allow(non_camel_case_types)]

use libc::c_int;
use std::ffi::OsStr;

/// The platform's `char`, re-exported so downstream crates need not depend on
/// `libc` themselves just to build an error buffer.
pub use libc::c_char;

/// The dynamic-loader error type, re-exported so downstream crates need not
/// depend on `libloading` themselves to name it.
pub use libloading::Error as LoadError;
use std::marker::{PhantomData, PhantomPinned};

/// The versioned symbol node the library exports.
pub const ABI_NODE: &str = "HSTCORE_1.4";

/// Every symbol in the ABI, in header order.
///
/// Used by this crate to bind, and available to callers that want to check a
/// library before trusting it.
pub const SYMBOLS: [&str; 13] = [
    "hst_open",
    "hst_open_batched",
    "hst_apply_delta",
    "hst_apply_shadow",
    "hst_batch",
    "hst_output_dim",
    "hst_input_dim",
    "hst_state",
    "hst_set_state",
    "hst_set_input",
    "hst_recompute_full",
    "hst_close",
    "hst_version",
];

/// Opaque session handle (`hst_ctx` in the header).
///
/// Never constructed on this side: it exists only to give the pointers a type.
#[repr(C)]
pub struct hst_ctx {
    _data: [u8; 0],
    _marker: PhantomData<(*mut u8, PhantomPinned)>,
}

/// `hst_ctx *hst_open(const char*, const char*, char*, size_t)`
pub type HstOpen =
    unsafe extern "C" fn(*const c_char, *const c_char, *mut c_char, usize) -> *mut hst_ctx;

/// `hst_ctx *hst_open_batched(const char*, const char*, int32_t, char*, size_t)`
pub type HstOpenBatched =
    unsafe extern "C" fn(*const c_char, *const c_char, i32, *mut c_char, usize) -> *mut hst_ctx;

/// `int hst_apply_delta(hst_ctx*, const int32_t*, const double*, int32_t, double*)`,
/// and `hst_apply_shadow`, which has the same shape.
pub type HstApply =
    unsafe extern "C" fn(*mut hst_ctx, *const i32, *const f64, i32, *mut f64) -> c_int;

/// `int32_t hst_batch/hst_output_dim/hst_input_dim(const hst_ctx*)`
pub type HstDim = unsafe extern "C" fn(*const hst_ctx) -> i32;

/// `const double *hst_state(const hst_ctx*)`
pub type HstState = unsafe extern "C" fn(*const hst_ctx) -> *const f64;

/// `int hst_set_state(hst_ctx*, const double*, int32_t)`
pub type HstSetState = unsafe extern "C" fn(*mut hst_ctx, *const f64, i32) -> c_int;

/// `int hst_set_input(hst_ctx*, const double*, int32_t)`
///
/// Sets the INPUT state x, the buffer `hst_recompute_full` computes `A*x` from.
/// Must be paired with [`HstSetState`] using the same baseline: priming one
/// without the other leaves them inconsistent and `hst_recompute_full` then
/// refuses with `-5`.
pub type HstSetInput = unsafe extern "C" fn(*mut hst_ctx, *const f64, i32) -> c_int;

/// `int hst_recompute_full(hst_ctx*, double*)`
pub type HstRecomputeFull = unsafe extern "C" fn(*mut hst_ctx, *mut f64) -> c_int;

/// `void hst_close(hst_ctx*)`
pub type HstClose = unsafe extern "C" fn(*mut hst_ctx);

/// `const char *hst_version(void)`
pub type HstVersion = unsafe extern "C" fn() -> *const c_char;

/// A loaded `libhstcore` with all thirteen entry points resolved.
///
/// The library is held by this struct and unloaded when it is dropped. Because
/// fields drop in declaration order and the handle is declared last, the
/// function pointers are never dropped after the code they point into is gone —
/// but note that any `hst_ctx` still open when this is dropped becomes a
/// dangling handle. The safe crate ties context lifetimes to the library for
/// exactly that reason.
pub struct Api {
    /// Open a session. Returns null on failure, with a reason in `errbuf`.
    pub hst_open: HstOpen,
    /// Open a session with 1..=32 right-hand-side lanes.
    pub hst_open_batched: HstOpenBatched,
    /// Apply a sparse delta. Metered.
    pub hst_apply_delta: HstApply,
    /// Apply a sparse delta against the shadow budget. Never interleave with
    /// the above on one handle.
    pub hst_apply_shadow: HstApply,
    /// Lane count of a handle.
    pub hst_batch: HstDim,
    /// Rows of the operator.
    pub hst_output_dim: HstDim,
    /// Columns of the operator.
    pub hst_input_dim: HstDim,
    /// Pointer to the held dense state. Valid until the next apply, set_state
    /// or close.
    pub hst_state: HstState,
    /// Overwrite the held dense state.
    pub hst_set_state: HstSetState,
    /// Overwrite the held dense INPUT state. Pair with `hst_set_state`.
    pub hst_set_input: HstSetInput,
    /// Full recompute into a caller buffer. Not metered.
    pub hst_recompute_full: HstRecomputeFull,
    /// Release a handle.
    pub hst_close: HstClose,
    /// Library version string.
    pub hst_version: HstVersion,

    // Declared last so it is dropped last.
    _handle: libloading::Library,
}

/// Platform-conventional file name of the shipped library.
pub fn default_library_name() -> &'static str {
    if cfg!(target_os = "macos") {
        "libhstcore.dylib"
    } else if cfg!(target_os = "windows") {
        "hstcore.dll"
    } else {
        "libhstcore.so"
    }
}

impl Api {
    /// Open a library by path and resolve all thirteen symbols.
    ///
    /// # Safety
    ///
    /// Loading a shared library executes its initializers, and this crate
    /// cannot check that the file at `path` is really `libhstcore` — only that
    /// it exports the right names. Point it at a library you trust. Calling any
    /// resolved function is likewise unsafe: the ABI's own rules (one handle per
    /// thread, no interleaving of shadow and production applies, state pointers
    /// invalidated by the next call) are not enforced here.
    pub unsafe fn open_at<P: AsRef<OsStr>>(path: P) -> Result<Self, libloading::Error> {
        let handle = libloading::Library::new(path)?;

        // Each resolution is its own statement so the borrow of `handle` ends
        // before it is moved into the struct.
        let hst_open = *handle.get::<HstOpen>(b"hst_open\0")?;
        let hst_open_batched = *handle.get::<HstOpenBatched>(b"hst_open_batched\0")?;
        let hst_apply_delta = *handle.get::<HstApply>(b"hst_apply_delta\0")?;
        let hst_apply_shadow = *handle.get::<HstApply>(b"hst_apply_shadow\0")?;
        let hst_batch = *handle.get::<HstDim>(b"hst_batch\0")?;
        let hst_output_dim = *handle.get::<HstDim>(b"hst_output_dim\0")?;
        let hst_input_dim = *handle.get::<HstDim>(b"hst_input_dim\0")?;
        let hst_state = *handle.get::<HstState>(b"hst_state\0")?;
        let hst_set_state = *handle.get::<HstSetState>(b"hst_set_state\0")?;
        let hst_set_input = *handle.get::<HstSetInput>(b"hst_set_input\0")?;
        let hst_recompute_full = *handle.get::<HstRecomputeFull>(b"hst_recompute_full\0")?;
        let hst_close = *handle.get::<HstClose>(b"hst_close\0")?;
        let hst_version = *handle.get::<HstVersion>(b"hst_version\0")?;

        Ok(Api {
            hst_open,
            hst_open_batched,
            hst_apply_delta,
            hst_apply_shadow,
            hst_batch,
            hst_output_dim,
            hst_input_dim,
            hst_state,
            hst_set_state,
            hst_set_input,
            hst_recompute_full,
            hst_close,
            hst_version,
            _handle: handle,
        })
    }

    /// Open the library by its conventional name, leaving the path to the
    /// dynamic loader.
    ///
    /// # Safety
    ///
    /// As [`Api::open_at`], and additionally: what the loader finds depends on
    /// the environment (`LD_LIBRARY_PATH`, `DYLD_LIBRARY_PATH`, rpath).
    pub unsafe fn open_default() -> Result<Self, libloading::Error> {
        Self::open_at(default_library_name())
    }
}
