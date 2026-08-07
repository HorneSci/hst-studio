//! A recording stub exporting the HST-core Embedded ABI. **Not the product.**
//!
//! ------------------------------------------------------------------------
//! THIS CRATE COMPUTES NO DELTA MATHEMATICS, AND MUST NOT BE MADE TO.
//! ------------------------------------------------------------------------
//!
//! It exists so the binding's plumbing can be tested: that the right symbol is
//! called, that slice pointers arrive unchanged, that lengths and counts are
//! what the safe layer said they were, and that each documented return code
//! becomes the right `Error` variant.
//!
//! It deliberately does not emulate the engine. A fake that half-applied a
//! delta would teach readers a wrong expectation about a product they have not
//! bought, and would let a binding bug hide behind plausible-looking output.
//! The held state changes here only when `hst_set_state` copies a caller buffer
//! into it. Nothing is ever computed.
//!
//! Built as a `cdylib` by `cargo build --workspace`; the integration tests find
//! it in the target directory and skip if it is not there.

#![allow(non_camel_case_types)]

use std::ffi::{c_char, c_int, CStr, CString};
use std::sync::atomic::{AtomicI32, AtomicI64, AtomicU64, Ordering::SeqCst};
use std::sync::Mutex;

/// Slot ids for [`hst_stub_count`], mirrored in the tests.
pub const SLOTS: usize = 10;

static CALLS: [AtomicI64; SLOTS] = [
    AtomicI64::new(0),
    AtomicI64::new(0),
    AtomicI64::new(0),
    AtomicI64::new(0),
    AtomicI64::new(0),
    AtomicI64::new(0),
    AtomicI64::new(0),
    AtomicI64::new(0),
    AtomicI64::new(0),
    AtomicI64::new(0),
];

const OPEN: usize = 0;
const OPEN_BATCHED: usize = 1;
const APPLY: usize = 2;
const SHADOW: usize = 3;
const BATCH: usize = 4;
const STATE: usize = 5;
const SET_STATE: usize = 6;
const SET_INPUT: usize = 9;
const RECOMPUTE: usize = 7;
const CLOSE: usize = 8;

static RC_APPLY: AtomicI32 = AtomicI32::new(0);
static RC_SHADOW: AtomicI32 = AtomicI32::new(0);
static RC_SET_STATE: AtomicI32 = AtomicI32::new(0);
static RC_SET_INPUT: AtomicI32 = AtomicI32::new(0);
static RC_RECOMPUTE: AtomicI32 = AtomicI32::new(0);
static DIM_N: AtomicI32 = AtomicI32::new(8);
static DIM_M: AtomicI32 = AtomicI32::new(5);
static BATCH_REPORT: AtomicI32 = AtomicI32::new(-1);
static OPEN_FAILS: AtomicI32 = AtomicI32::new(0);
static LAST_COLS: AtomicU64 = AtomicU64::new(0);
static LAST_VALS: AtomicU64 = AtomicU64::new(0);
static LAST_Y_OUT: AtomicU64 = AtomicU64::new(0);
static LAST_COUNT: AtomicI32 = AtomicI32::new(-1);
static LAST_SET_LEN: AtomicI32 = AtomicI32::new(-1);
static LAST_SET_INPUT_LEN: AtomicI32 = AtomicI32::new(-1);
static FAIL_REASON: Mutex<Option<CString>> = Mutex::new(None);

#[repr(C)]
pub struct hst_ctx {
    batch: i32,
    n: i32,
    m: i32,
    held: Vec<f64>,
    /// The INPUT state, sized by m — deliberately a different length from `held`.
    held_x: Vec<f64>,
}

// ---- stub control surface (not part of the ABI) -------------------------

#[no_mangle]
pub extern "C" fn hst_stub_reset() {
    for slot in CALLS.iter() {
        slot.store(0, SeqCst);
    }
    RC_APPLY.store(0, SeqCst);
    RC_SHADOW.store(0, SeqCst);
    RC_SET_STATE.store(0, SeqCst);
    RC_SET_INPUT.store(0, SeqCst);
    RC_RECOMPUTE.store(0, SeqCst);
    DIM_N.store(8, SeqCst);
    DIM_M.store(5, SeqCst);
    BATCH_REPORT.store(-1, SeqCst);
    OPEN_FAILS.store(0, SeqCst);
    LAST_COLS.store(0, SeqCst);
    LAST_VALS.store(0, SeqCst);
    LAST_Y_OUT.store(0, SeqCst);
    LAST_COUNT.store(-1, SeqCst);
    LAST_SET_LEN.store(-1, SeqCst);
    LAST_SET_INPUT_LEN.store(-1, SeqCst);
    *FAIL_REASON.lock().unwrap() = None;
}

#[no_mangle]
pub extern "C" fn hst_stub_set_dims(n: i32, m: i32) {
    DIM_N.store(n, SeqCst);
    DIM_M.store(m, SeqCst);
}

#[no_mangle]
pub extern "C" fn hst_stub_set_batch_report(b: i32) {
    BATCH_REPORT.store(b, SeqCst);
}

/// # Safety
/// `why` must be a valid NUL-terminated string or null.
#[no_mangle]
pub unsafe extern "C" fn hst_stub_set_open_fail(fails: i32, why: *const c_char) {
    OPEN_FAILS.store(fails, SeqCst);
    *FAIL_REASON.lock().unwrap() = if why.is_null() {
        None
    } else {
        Some(CStr::from_ptr(why).to_owned())
    };
}

#[no_mangle]
pub extern "C" fn hst_stub_set_rc(which: i32, rc: i32) {
    match which as usize {
        APPLY => RC_APPLY.store(rc, SeqCst),
        SHADOW => RC_SHADOW.store(rc, SeqCst),
        SET_STATE => RC_SET_STATE.store(rc, SeqCst),
        SET_INPUT => RC_SET_INPUT.store(rc, SeqCst),
        RECOMPUTE => RC_RECOMPUTE.store(rc, SeqCst),
        _ => {}
    }
}

#[no_mangle]
pub extern "C" fn hst_stub_count(which: i32) -> i64 {
    CALLS
        .get(which as usize)
        .map(|slot| slot.load(SeqCst))
        .unwrap_or(-1)
}

#[no_mangle]
pub extern "C" fn hst_stub_last_cols() -> u64 {
    LAST_COLS.load(SeqCst)
}
#[no_mangle]
pub extern "C" fn hst_stub_last_vals() -> u64 {
    LAST_VALS.load(SeqCst)
}
#[no_mangle]
pub extern "C" fn hst_stub_last_y_out() -> u64 {
    LAST_Y_OUT.load(SeqCst)
}
#[no_mangle]
pub extern "C" fn hst_stub_last_count() -> i32 {
    LAST_COUNT.load(SeqCst)
}
#[no_mangle]
pub extern "C" fn hst_stub_last_set_len() -> i32 {
    LAST_SET_LEN.load(SeqCst)
}

// ---- the ABI -------------------------------------------------------------

unsafe fn make_ctx(batch: i32, errbuf: *mut c_char, errbuf_len: usize) -> *mut hst_ctx {
    if OPEN_FAILS.load(SeqCst) != 0 {
        if !errbuf.is_null() && errbuf_len > 0 {
            let guard = FAIL_REASON.lock().unwrap();
            let bytes = guard.as_ref().map(|s| s.as_bytes()).unwrap_or(b"");
            let take = bytes.len().min(errbuf_len - 1);
            std::ptr::copy_nonoverlapping(bytes.as_ptr() as *const c_char, errbuf, take);
            *errbuf.add(take) = 0;
        }
        return std::ptr::null_mut();
    }
    let n = DIM_N.load(SeqCst);
    let m = DIM_M.load(SeqCst);
    let reported = BATCH_REPORT.load(SeqCst);
    let ctx = Box::new(hst_ctx {
        batch: if reported >= 0 { reported } else { batch },
        n,
        m,
        held: vec![0.0; (n.max(0) as usize) * (batch.max(1) as usize)],
        held_x: vec![0.0; (m.max(0) as usize) * (batch.max(1) as usize)],
    });
    Box::into_raw(ctx)
}

/// # Safety
/// C entry point; pointers must be valid.
#[no_mangle]
pub unsafe extern "C" fn hst_open(
    _artifact_path: *const c_char,
    _license_token: *const c_char,
    errbuf: *mut c_char,
    errbuf_len: usize,
) -> *mut hst_ctx {
    CALLS[OPEN].fetch_add(1, SeqCst);
    make_ctx(1, errbuf, errbuf_len)
}

/// # Safety
/// C entry point; pointers must be valid.
#[no_mangle]
pub unsafe extern "C" fn hst_open_batched(
    _artifact_path: *const c_char,
    _license_token: *const c_char,
    batch: i32,
    errbuf: *mut c_char,
    errbuf_len: usize,
) -> *mut hst_ctx {
    CALLS[OPEN_BATCHED].fetch_add(1, SeqCst);
    make_ctx(batch, errbuf, errbuf_len)
}

fn record(cols: *const i32, vals: *const f64, count: i32, y_out: *mut f64) {
    LAST_COLS.store(cols as u64, SeqCst);
    LAST_VALS.store(vals as u64, SeqCst);
    LAST_Y_OUT.store(y_out as u64, SeqCst);
    LAST_COUNT.store(count, SeqCst);
}

/// Records what it was handed. Touches no values.
///
/// # Safety
/// C entry point; pointers must be valid.
#[no_mangle]
pub unsafe extern "C" fn hst_apply_delta(
    _ctx: *mut hst_ctx,
    cols: *const i32,
    vals: *const f64,
    count: i32,
    y_out: *mut f64,
) -> c_int {
    CALLS[APPLY].fetch_add(1, SeqCst);
    record(cols, vals, count, y_out);
    RC_APPLY.load(SeqCst)
}

/// # Safety
/// C entry point; pointers must be valid.
#[no_mangle]
pub unsafe extern "C" fn hst_apply_shadow(
    _ctx: *mut hst_ctx,
    cols: *const i32,
    vals: *const f64,
    count: i32,
    y_out: *mut f64,
) -> c_int {
    CALLS[SHADOW].fetch_add(1, SeqCst);
    record(cols, vals, count, y_out);
    RC_SHADOW.load(SeqCst)
}

/// # Safety
/// C entry point; `ctx` must come from an open call.
#[no_mangle]
pub unsafe extern "C" fn hst_batch(ctx: *const hst_ctx) -> i32 {
    CALLS[BATCH].fetch_add(1, SeqCst);
    ctx.as_ref().map(|c| c.batch).unwrap_or(0)
}

/// # Safety
/// C entry point; `ctx` must come from an open call.
#[no_mangle]
pub unsafe extern "C" fn hst_output_dim(ctx: *const hst_ctx) -> i32 {
    ctx.as_ref().map(|c| c.n).unwrap_or(0)
}

/// # Safety
/// C entry point; `ctx` must come from an open call.
#[no_mangle]
pub unsafe extern "C" fn hst_input_dim(ctx: *const hst_ctx) -> i32 {
    ctx.as_ref().map(|c| c.m).unwrap_or(0)
}

/// # Safety
/// C entry point; `ctx` must come from an open call.
#[no_mangle]
pub unsafe extern "C" fn hst_state(ctx: *const hst_ctx) -> *const f64 {
    CALLS[STATE].fetch_add(1, SeqCst);
    match ctx.as_ref() {
        Some(c) => c.held.as_ptr(),
        None => std::ptr::null(),
    }
}

/// A copy, not a computation.
///
/// # Safety
/// C entry point; `y0` must point at `len` doubles.
#[no_mangle]
pub unsafe extern "C" fn hst_set_state(ctx: *mut hst_ctx, y0: *const f64, len: i32) -> c_int {
    CALLS[SET_STATE].fetch_add(1, SeqCst);
    LAST_SET_LEN.store(len, SeqCst);
    let rc = RC_SET_STATE.load(SeqCst);
    if rc != 0 {
        return rc;
    }
    if let Some(c) = ctx.as_mut() {
        if !y0.is_null() && len > 0 {
            let take = (len as usize).min(c.held.len());
            std::ptr::copy_nonoverlapping(y0, c.held.as_mut_ptr(), take);
        }
    }
    0
}

/// The INPUT state's own setter. Separate buffer, sized by `m` not `n`, so a
/// binding that passes an output-shaped length is caught here rather than
/// writing past a buffer that happened to be large enough.
///
/// # Safety
/// C entry point; `x0` must point at `len` doubles.
#[no_mangle]
pub unsafe extern "C" fn hst_set_input(ctx: *mut hst_ctx, x0: *const f64, len: i32) -> c_int {
    CALLS[SET_INPUT].fetch_add(1, SeqCst);
    LAST_SET_INPUT_LEN.store(len, SeqCst);
    let rc = RC_SET_INPUT.load(SeqCst);
    if rc != 0 {
        return rc;
    }
    match ctx.as_mut() {
        Some(c) if !x0.is_null() && len > 0 => {
            if len as usize != c.held_x.len() {
                return -1;
            }
            std::ptr::copy_nonoverlapping(x0, c.held_x.as_mut_ptr(), len as usize);
            0
        }
        _ => -1,
    }
}

/// Writes a constant. There is no operator here to recompute from.
///
/// # Safety
/// C entry point; `y_out` must point at `output_dim * batch` doubles.
#[no_mangle]
pub unsafe extern "C" fn hst_recompute_full(ctx: *mut hst_ctx, y_out: *mut f64) -> c_int {
    CALLS[RECOMPUTE].fetch_add(1, SeqCst);
    LAST_Y_OUT.store(y_out as u64, SeqCst);
    let rc = RC_RECOMPUTE.load(SeqCst);
    if rc != 0 {
        return rc;
    }
    match (ctx.as_ref(), y_out.is_null()) {
        (Some(c), false) => {
            let total = (c.n as usize) * (c.batch as usize);
            for i in 0..total {
                *y_out.add(i) = -7.0;
            }
            0
        }
        _ => -1,
    }
}

/// # Safety
/// C entry point; `ctx` must come from an open call, or be null.
#[no_mangle]
pub unsafe extern "C" fn hst_close(ctx: *mut hst_ctx) {
    CALLS[CLOSE].fetch_add(1, SeqCst);
    if !ctx.is_null() {
        drop(Box::from_raw(ctx));
    }
}

#[no_mangle]
pub extern "C" fn hst_version() -> *const c_char {
    b"hstcore-stub 0.0.0 (no engine)\0".as_ptr() as *const c_char
}
