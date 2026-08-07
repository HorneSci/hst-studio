//! Safe Rust bindings for the **HST-core Embedded** runtime (`libhstcore`).
//!
//! This crate is a binding, not an engine. The code that does the work is
//! `libhstcore`, a shared library this crate does not contain; nothing here
//! computes anything. In an HST Studio download the library is already in
//! `bin/` (`libhstcore.so` / `libhstcore.dylib`), Apache-2.0, unmetered, and
//! needs no key, token or account. A separate, metered build of the same library also
//! exists as its own artifact. Without any library loaded, every entry point
//! returns [`Error::Load`]. If you arrived looking for an open sparse
//! delta-matvec you can run today, this is not it — see the README.
//!
//! This doc comment called the library "closed-source ... under a signed
//! license" until 2026-08-06, which was true of the metered build and
//! false of the community one shipped beside this crate in the same tree.
//!
//! # What the library does
//!
//! A sparse operator is compiled once into an artifact. A dense state evolves
//! by a sparse delta each step. The library holds both, in your process, and
//! updates the dense output with no serialization anywhere — which is the whole
//! design, because any process or network hop that carries the dense state
//! costs far more than the compute being saved.
//!
//! # Shape of a program
//!
//! ```no_run
//! use hstcore::Library;
//!
//! # fn main() -> Result<(), Box<dyn std::error::Error>> {
//! // Safety: loading a shared library runs its initializers.
//! let lib = unsafe { Library::open_at("/opt/hst/libhstcore.so")? };
//! println!("{}", lib.version()?);
//!
//! let mut session = lib.open("op.bin".as_ref(), &std::fs::read_to_string("prod.license")?)?;
//!
//! let mut reference = vec![0.0; session.state_len()];
//! let cols: Vec<i32> = (0..32).collect();
//! let mut vals = vec![0.0f64; 32];
//!
//! for step in 0..1000 {
//!     vals.iter_mut().for_each(|v| *v = 0.01 * step as f64);
//!     session.apply(&cols, &vals)?;
//!     let y = session.state();          // zero-copy; borrows the session
//!     std::hint::black_box(y[0]);
//! }
//!
//! session.recompute_full(&mut reference)?;   // the unmetered reference arm
//! # Ok(()) }
//! ```
//!
//! # The one thing this binding does that the C API cannot
//!
//! `hstcore.h` documents two rules in comments:
//!
//! * the pointer from `hst_state` is valid only until the next apply,
//!   `set_state` or `close`;
//! * shadow and production applies share held buffers and must never be
//!   interleaved on one handle.
//!
//! In C both are warnings. Here the first is [`Context::state`] borrowing the
//! session, so holding it across an `&mut self` call does not compile; and the
//! second is [`Context::into_shadow`] consuming the session by value, so a
//! production apply after the conversion does not compile either. Both rules
//! have a `compile_fail` doctest holding them in place.
//!
//! # Threading
//!
//! [`Context`] and [`ShadowContext`] are deliberately neither `Send` nor
//! `Sync`. The ABI asks for one handle per thread or stream and the held state
//! is unsynchronized, so this is one more comment turned into a compile error.

#![warn(missing_docs)]
#![warn(clippy::undocumented_unsafe_blocks)]

mod context;
mod error;

pub use context::{Context, ShadowContext};
pub use error::Error;
pub use hstcore_sys::{default_library_name, ABI_NODE, SYMBOLS};

use std::path::Path;

/// A loaded `libhstcore`.
///
/// Sessions borrow the library, so it cannot be dropped while one is open —
/// the compiler enforces the ordering that a C program has to remember.
pub struct Library {
    api: hstcore_sys::Api,
}

impl Library {
    /// Load the library from an explicit path.
    ///
    /// # Safety
    ///
    /// Loading a shared library executes its initializers, and this crate
    /// cannot verify that the file is really `libhstcore` — only that it
    /// exports the right thirteen names. Point it at a library you trust.
    pub unsafe fn open_at<P: AsRef<std::ffi::OsStr>>(path: P) -> Result<Self, Error> {
        Ok(Library {
            api: hstcore_sys::Api::open_at(path)?,
        })
    }

    /// Load the library by its conventional name, leaving the search to the
    /// dynamic loader.
    ///
    /// # Safety
    ///
    /// As [`Library::open_at`], and additionally: which file the loader finds
    /// depends on the environment.
    pub unsafe fn open_default() -> Result<Self, Error> {
        Ok(Library {
            api: hstcore_sys::Api::open_default()?,
        })
    }

    /// The library's version string, e.g. `"hstcore 1.4.0"`.
    pub fn version(&self) -> Result<String, Error> {
        // Safety: hst_version returns a pointer to a static string owned by the
        // library, which outlives this borrow.
        let ptr = unsafe { (self.api.hst_version)() };
        if ptr.is_null() {
            return Ok(String::new());
        }
        // Safety: as above; the string is NUL-terminated by contract.
        Ok(unsafe { std::ffi::CStr::from_ptr(ptr) }
            .to_string_lossy()
            .into_owned())
    }

    /// Open a single-lane session over a compiled operator artifact.
    pub fn open(&self, artifact: &Path, token: &str) -> Result<Context<'_>, Error> {
        Ok(Context(context::Handle::open(self, artifact, token, 1, false)?))
    }

    /// Open a session carrying `batch` independent right-hand-side lanes
    /// (`1..=32`) under one operator and one delta sparsity pattern.
    ///
    /// All buffers are then lane-interleaved: `state[i * batch + b]`,
    /// `vals[i * batch + b]`.
    pub fn open_batched(
        &self,
        artifact: &Path,
        token: &str,
        batch: i32,
    ) -> Result<Context<'_>, Error> {
        Ok(Context(context::Handle::open(
            self, artifact, token, batch, true,
        )?))
    }

    pub(crate) fn api(&self) -> &hstcore_sys::Api {
        &self.api
    }
}

impl std::fmt::Debug for Library {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("Library")
            .field("abi", &ABI_NODE)
            .field("version", &self.version().unwrap_or_default())
            .finish()
    }
}
