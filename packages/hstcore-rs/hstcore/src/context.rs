//! Sessions: [`Context`] for production applies, [`ShadowContext`] for shadow
//! ones, and no way to be both.

use std::marker::PhantomData;
use std::path::Path;

use hstcore_sys::{c_char, hst_ctx, HstApply};

use crate::error::{check, Error};
use crate::Library;

pub(crate) const MAX_BATCH: i32 = 32;
const ERRBUF: usize = 256;

/// The parts every session shares. Not public: what distinguishes a production
/// session from a shadow one is which wrapper owns this, and that distinction
/// is the point.
pub(crate) struct Handle<'lib> {
    raw: *mut hst_ctx,
    lib: &'lib Library,
    batch: i32,
    n: i32,
    m: i32,
    // `lib` above already ties this handle to the library's lifetime; this
    // states the same intent where a reader looks for it.
    _lifetime: PhantomData<&'lib Library>,
    // A raw pointer here removes both `Send` and `Sync`. The held state is
    // unsynchronized and the ABI asks for one handle per thread or stream, so
    // a handle that could be moved or shared across threads would be a bug the
    // compiler is perfectly able to catch.
    _unsend: PhantomData<*const ()>,
}

impl<'lib> Handle<'lib> {
    pub(crate) fn open(
        lib: &'lib Library,
        artifact: &Path,
        token: &str,
        batch: i32,
        batched: bool,
    ) -> Result<Self, Error> {
        if !(1..=MAX_BATCH).contains(&batch) {
            return Err(Error::BadBatch(batch));
        }
        let artifact_c = std::ffi::CString::new(artifact.to_str().ok_or(Error::NonUtf8Path)?)
            .map_err(|_| Error::InteriorNul("artifact path"))?;
        let token_c =
            std::ffi::CString::new(token).map_err(|_| Error::InteriorNul("license token"))?;
        let mut errbuf = [0 as c_char; ERRBUF];

        let api = lib.api();
        // Safety: both C strings outlive the call, `errbuf` is a live array of
        // exactly ERRBUF bytes, and `batch` was range-checked above.
        let raw = unsafe {
            if batched {
                (api.hst_open_batched)(
                    artifact_c.as_ptr(),
                    token_c.as_ptr(),
                    batch,
                    errbuf.as_mut_ptr(),
                    ERRBUF,
                )
            } else {
                (api.hst_open)(
                    artifact_c.as_ptr(),
                    token_c.as_ptr(),
                    errbuf.as_mut_ptr(),
                    ERRBUF,
                )
            }
        };
        if raw.is_null() {
            let end = errbuf.iter().position(|&b| b == 0).unwrap_or(0);
            let bytes: Vec<u8> = errbuf[..end].iter().map(|&b| b as u8).collect();
            let reason = String::from_utf8_lossy(&bytes).trim().to_string();
            return Err(Error::Open(if reason.is_empty() {
                "no reason given (invalid or expired license, operator larger than the \
                 license permits, exhausted file quota, or an unreadable artifact)"
                    .to_string()
            } else {
                reason
            }));
        }

        // Safety: `raw` is a live handle from the open call just above; these
        // three are pure reads on it.
        let reported = unsafe { (api.hst_batch)(raw) };
        // Safety: as above.
        let n = unsafe { (api.hst_output_dim)(raw) };
        // Safety: as above.
        let m = unsafe { (api.hst_input_dim)(raw) };
        let handle = Handle {
            raw,
            lib,
            batch: reported,
            n,
            m,
            _lifetime: PhantomData,
            _unsend: PhantomData,
        };
        if reported != batch {
            // `handle` closes on the way out of this function.
            return Err(Error::LaneMismatch {
                requested: batch,
                reported,
            });
        }
        if n <= 0 || m <= 0 {
            return Err(Error::DegenerateOperator { n, m });
        }
        Ok(handle)
    }

    #[inline]
    pub(crate) fn batch(&self) -> i32 {
        self.batch
    }
    #[inline]
    pub(crate) fn output_dim(&self) -> i32 {
        self.n
    }
    #[inline]
    pub(crate) fn input_dim(&self) -> i32 {
        self.m
    }
    #[inline]
    pub(crate) fn state_len(&self) -> usize {
        self.n as usize * self.batch as usize
    }

    /// `input_dim * batch`. Differs from [`state_len`] on a non-square
    /// operator, which is exactly why `set_input` may not reuse it.
    pub(crate) fn input_len(&self) -> usize {
        self.m as usize * self.batch as usize
    }

    fn check_input_len(&self, got: usize, what: &'static str) -> Result<(), Error> {
        if got != self.input_len() {
            return Err(Error::Length {
                what,
                expected: self.input_len(),
                got,
            });
        }
        Ok(())
    }

    fn check_state_len(&self, got: usize, what: &'static str) -> Result<(), Error> {
        if got != self.state_len() {
            return Err(Error::Length {
                what,
                expected: self.state_len(),
                got,
            });
        }
        Ok(())
    }

    pub(crate) fn apply_through(
        &mut self,
        entry_fn: HstApply,
        entry: &'static str,
        cols: &[i32],
        vals: &[f64],
        y_out: Option<&mut [f64]>,
    ) -> Result<(), Error> {
        let count =
            i32::try_from(cols.len()).map_err(|_| Error::TooManyEntries(cols.len()))?;
        let need = cols
            .len()
            .checked_mul(self.batch as usize)
            .ok_or(Error::TooManyEntries(cols.len()))?;
        if vals.len() != need {
            return Err(Error::Length {
                what: "vals",
                expected: need,
                got: vals.len(),
            });
        }
        let out_ptr = match y_out {
            Some(buf) => {
                self.check_state_len(buf.len(), "y_out")?;
                buf.as_mut_ptr()
            }
            None => std::ptr::null_mut(),
        };
        // Safety: `raw` is live for as long as this handle is; `cols` and
        // `vals` are live slices of exactly `count` and `count * batch`
        // elements, checked above; `out_ptr` is null or a live buffer of
        // `state_len()`. Slices are already contiguous and correctly typed, so
        // this is a pointer hand-off: nothing is copied, and nothing needs to
        // be.
        let code =
            unsafe { entry_fn(self.raw, cols.as_ptr(), vals.as_ptr(), count, out_ptr) };
        check(code, entry)
    }

    pub(crate) fn state(&self) -> &[f64] {
        // Safety: `raw` is a live handle; this is a pure read.
        let ptr = unsafe { (self.lib.api().hst_state)(self.raw) };
        if ptr.is_null() {
            return &[];
        }
        // Safety: the pointer is the library's own state buffer, of exactly
        // this length, and it stays valid until the next apply / set_state /
        // close. Each of those takes `&mut self` or consumes the handle, so the
        // borrow checker will not let this slice outlive any of them.
        unsafe { std::slice::from_raw_parts(ptr, self.state_len()) }
    }

    pub(crate) fn set_state(&mut self, y0: &[f64]) -> Result<(), Error> {
        self.check_state_len(y0.len(), "y0")?;
        // Safety: `raw` is live, and `y0` is a live slice of exactly
        // `state_len()` doubles, which is the length being passed.
        let code = unsafe {
            (self.lib.api().hst_set_state)(self.raw, y0.as_ptr(), self.state_len() as i32)
        };
        check(code, "hst_set_state")
    }

    pub(crate) fn set_input(&mut self, x0: &[f64]) -> Result<(), Error> {
        self.check_input_len(x0.len(), "x0")?;
        // Safety: `raw` is live, and `x0` is a live slice of exactly
        // `input_len()` doubles, which is the length being passed.
        let code = unsafe {
            (self.lib.api().hst_set_input)(self.raw, x0.as_ptr(), self.input_len() as i32)
        };
        check(code, "hst_set_input")
    }

    pub(crate) fn recompute_full(&self, y_out: &mut [f64]) -> Result<(), Error> {
        self.check_state_len(y_out.len(), "y_out")?;
        // Safety: `raw` is live, and `y_out` is a live writeable slice of
        // exactly `state_len()` doubles, which is what the library writes.
        let code =
            unsafe { (self.lib.api().hst_recompute_full)(self.raw, y_out.as_mut_ptr()) };
        check(code, "hst_recompute_full")
    }
}

impl Drop for Handle<'_> {
    fn drop(&mut self) {
        // Safety: this is the only place a handle is closed — there is no
        // explicit close() to call twice — and the library documents hst_close
        // as safe on null. The library outlives the handle by construction.
        unsafe { (self.lib.api().hst_close)(self.raw) }
    }
}

macro_rules! shared_session_api {
    ($t:ident) => {
        impl $t<'_> {
            /// Right-hand-side lanes on this handle (1 for a plain open).
            pub fn batch(&self) -> i32 {
                self.0.batch()
            }

            /// N — rows of the operator.
            pub fn output_dim(&self) -> i32 {
                self.0.output_dim()
            }

            /// M — columns of the operator. Delta column indices live in `0..M`.
            pub fn input_dim(&self) -> i32 {
                self.0.input_dim()
            }

            /// `output_dim * batch` — the length of every state-shaped buffer.
            pub fn state_len(&self) -> usize {
                self.0.state_len()
            }

            /// `input_dim * batch` — the length `set_input` requires.
            pub fn input_len(&self) -> usize {
                self.0.input_len()
            }

            /// Borrow the held dense output state, zero-copy.
            ///
            /// Lane-interleaved: element `i` of lane `b` is at
            /// `state[i * batch + b]`.
            ///
            /// `hstcore.h` says this pointer is valid only until the next
            /// apply, `set_state` or `close`. Here that rule is the borrow
            /// checker's, not the reader's: the returned slice borrows `self`,
            /// every invalidating operation takes `&mut self` or consumes the
            /// session, and `Drop` handles the close. Holding the slice across
            /// one of them does not compile.
            ///
            /// ```compile_fail,E0502
            /// # fn demo(session: &mut hstcore::Context) -> Result<(), hstcore::Error> {
            /// let y = session.state();
            /// session.apply(&[0], &[1.0])?;   // cannot borrow as mutable
            /// println!("{}", y[0]);
            /// # Ok(()) }
            /// ```
            ///
            /// The accepted shape is to finish with the borrow first, or to
            /// copy out of it:
            ///
            /// ```
            /// # fn demo(session: &mut hstcore::Context) -> Result<(), hstcore::Error> {
            /// let kept: Vec<f64> = session.state().to_vec();
            /// session.apply(&[0], &[1.0])?;
            /// println!("{}", kept[0]);
            /// # Ok(()) }
            /// ```
            pub fn state(&self) -> &[f64] {
                self.0.state()
            }

            /// Overwrite the held dense output state.
            ///
            /// `y0` must be exactly [`state_len`](Self::state_len) long.
            pub fn set_state(&mut self, y0: &[f64]) -> Result<(), Error> {
                self.0.set_state(y0)
            }

            /// Overwrite the held dense **input** state x.
            ///
            /// `x0` must be exactly [`input_len`](Self::input_len) long — which
            /// is `input_dim * batch`, NOT the state length, and the two differ
            /// whenever the operator is not square.
            ///
            /// **Pair this with [`set_state`](Self::set_state) using the same
            /// baseline.** Priming one without the other leaves the handle's
            /// input and output states inconsistent, and `recompute_full` then
            /// refuses rather than return a vector that disagrees with the held
            /// state by exactly `A*x0` forever.
            pub fn set_input(&mut self, x0: &[f64]) -> Result<(), Error> {
                self.0.set_input(x0)
            }

            /// Recompute the whole dense output from scratch into `y_out`.
            /// **Not metered.**
            ///
            /// This is the reference arm — the "before" of a before/after
            /// comparison, and the only thing that can tell you the delta path
            /// is returning the right numbers. It spends no applies.
            ///
            /// It takes `&self` because, per the header, it writes only into
            /// `y_out` and leaves the held state alone — so an outstanding
            /// [`state`](Self::state) borrow stays valid across it. That is a
            /// contract this crate depends on and cannot verify.
            pub fn recompute_full(&self, y_out: &mut [f64]) -> Result<(), Error> {
                self.0.recompute_full(y_out)
            }
        }
    };
}

/// A production session: one compiled operator, one evolving dense state.
///
/// Not `Send` and not `Sync`. The ABI asks for one handle per thread or
/// stream, and the held state is unsynchronized; a handle that could cross
/// threads would be a data race the compiler is able to prevent.
///
/// Closed by `Drop`. There is no `close()` to forget or to call twice.
///
/// ```compile_fail,E0277
/// fn needs_send<T: Send>(_: T) {}
/// # fn demo(session: hstcore::Context) { needs_send(session); }
/// ```
///
/// The companion below compiles, so the one above cannot be passing merely
/// because something in it is misspelled — `rustdoc` does not enforce the
/// error code it is pinned to, and a `compile_fail` block with a typo would
/// otherwise pass for the wrong reason.
///
/// ```
/// fn needs_send<T: Send>(_: T) {}
/// # fn demo(e: hstcore::Error) { needs_send(e); }
/// ```
pub struct Context<'lib>(pub(crate) Handle<'lib>);

/// A shadow session: identical numerics, metered against the license's
/// separate shadow budget.
///
/// Reached only through [`Context::into_shadow`], which **consumes** the
/// production session. `hstcore.h` warns that shadow and production applies
/// share the held input and output buffers and must never be interleaved on
/// one handle; because the conversion is one-way and by value, interleaving
/// them is a compile error rather than a rule to remember.
pub struct ShadowContext<'lib>(pub(crate) Handle<'lib>);

shared_session_api!(Context);
shared_session_api!(ShadowContext);

impl std::fmt::Debug for Context<'_> {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("Context")
            .field("output_dim", &self.0.output_dim())
            .field("input_dim", &self.0.input_dim())
            .field("batch", &self.0.batch())
            .finish()
    }
}

impl std::fmt::Debug for ShadowContext<'_> {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("ShadowContext")
            .field("output_dim", &self.0.output_dim())
            .field("input_dim", &self.0.input_dim())
            .field("batch", &self.0.batch())
            .finish()
    }
}

impl<'lib> Context<'lib> {
    /// Apply a sparse delta to the held state. Metered.
    ///
    /// Column `cols[i]` changes by `vals[i * batch + b]` in lane `b`, so
    /// `vals` must be exactly `cols.len() * batch` long. Both slices are handed
    /// to C as pointers — there is no conversion step and no allocation here.
    ///
    /// The dense output stays inside the library; read it back with
    /// [`state`](Self::state), or use [`apply_into`](Self::apply_into) to have
    /// it written into a buffer you own.
    pub fn apply(&mut self, cols: &[i32], vals: &[f64]) -> Result<(), Error> {
        let entry_fn = self.0.lib_apply();
        self.0
            .apply_through(entry_fn, "hst_apply_delta", cols, vals, None)
    }

    /// [`apply`](Self::apply), also writing the dense output into `y_out`,
    /// which must be exactly [`state_len`](Self::state_len) long.
    pub fn apply_into(
        &mut self,
        cols: &[i32],
        vals: &[f64],
        y_out: &mut [f64],
    ) -> Result<(), Error> {
        let entry_fn = self.0.lib_apply();
        self.0
            .apply_through(entry_fn, "hst_apply_delta", cols, vals, Some(y_out))
    }

    /// Convert this session into a shadow session, consuming it.
    ///
    /// One-way. There is no route back, because there must not be one:
    ///
    /// ```compile_fail,E0382
    /// # fn demo(mut session: hstcore::Context) -> Result<(), hstcore::Error> {
    /// let mut shadow = session.into_shadow();
    /// shadow.apply(&[0], &[1.0])?;
    /// session.apply(&[0], &[1.0])?;   // moved: production is no longer reachable
    /// # Ok(()) }
    /// ```
    ///
    /// To run both, open two sessions from the library — which is exactly what
    /// the header tells you to do. The companion below compiles, so the block
    /// above is failing on the move and not on a misspelling (`rustdoc` does
    /// not enforce the error code a `compile_fail` block is pinned to):
    ///
    /// ```
    /// # fn demo(session: hstcore::Context) -> Result<(), hstcore::Error> {
    /// let mut shadow = session.into_shadow();
    /// shadow.apply(&[0], &[1.0])?;
    /// # Ok(()) }
    /// ```
    pub fn into_shadow(self) -> ShadowContext<'lib> {
        ShadowContext(self.0)
    }
}

impl ShadowContext<'_> {
    /// Apply a sparse delta metered against the shadow budget.
    ///
    /// Same numerics as a production apply and the same argument rules. Fails
    /// with [`Error::ShadowNotGranted`] on every call if the signed token
    /// carries no shadow grant, and with [`Error::QuotaExhausted`] when the
    /// shadow budget — which is separate from the production one — is spent.
    pub fn apply(&mut self, cols: &[i32], vals: &[f64]) -> Result<(), Error> {
        let entry_fn = self.0.lib_shadow();
        self.0
            .apply_through(entry_fn, "hst_apply_shadow", cols, vals, None)
    }

    /// [`apply`](Self::apply), also writing the dense output into `y_out`.
    pub fn apply_into(
        &mut self,
        cols: &[i32],
        vals: &[f64],
        y_out: &mut [f64],
    ) -> Result<(), Error> {
        let entry_fn = self.0.lib_shadow();
        self.0
            .apply_through(entry_fn, "hst_apply_shadow", cols, vals, Some(y_out))
    }
}

impl Handle<'_> {
    fn lib_apply(&self) -> HstApply {
        self.lib.api().hst_apply_delta
    }
    fn lib_shadow(&self) -> HstApply {
        self.lib.api().hst_apply_shadow
    }
}
