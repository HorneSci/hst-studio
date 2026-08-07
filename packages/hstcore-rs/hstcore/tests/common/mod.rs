//! Finding and driving the recording stub.
//!
//! The stub is the `hst-stub` workspace member, built as a `cdylib`. It is
//! *not* a licensed `libhstcore` and does not pretend to be: it computes no
//! delta mathematics. What it can prove is that this crate calls the right
//! symbol with the right pointers and turns each return code into the right
//! error.

#![allow(dead_code)]

use std::path::PathBuf;

pub const OPEN: i32 = 0;
pub const OPEN_BATCHED: i32 = 1;
pub const APPLY: i32 = 2;
pub const SHADOW: i32 = 3;
pub const BATCH: i32 = 4;
pub const STATE: i32 = 5;
pub const SET_STATE: i32 = 6;
pub const RECOMPUTE: i32 = 7;
pub const CLOSE: i32 = 8;

fn stub_file_name() -> &'static str {
    if cfg!(target_os = "macos") {
        "libhst_stub.dylib"
    } else if cfg!(target_os = "windows") {
        "hst_stub.dll"
    } else {
        "libhst_stub.so"
    }
}

/// Where `cargo` put the stub. Panics rather than skipping: a test suite that
/// quietly passes because its subject was missing is worse than one that fails.
pub fn stub_path() -> PathBuf {
    if let Some(explicit) = std::env::var_os("HSTCORE_STUB") {
        return PathBuf::from(explicit);
    }
    let exe = std::env::current_exe().expect("current_exe");
    let deps = exe.parent().expect("deps dir");
    let profile = deps.parent().expect("profile dir");
    for dir in [profile, deps] {
        let candidate = dir.join(stub_file_name());
        if candidate.exists() {
            return candidate;
        }
    }
    panic!(
        "recording stub {} not found under {}. Build the whole workspace \
         (`cargo test --workspace`) or point HSTCORE_STUB at it.",
        stub_file_name(),
        profile.display()
    );
}

/// The stub's control surface, opened alongside the binding's own handle.
/// `dlopen` of the same file shares one set of statics, so these counters see
/// the calls the binding makes.
pub struct Stub {
    lib: libloading::Library,
}

impl Stub {
    pub fn open() -> Stub {
        // Safety: the stub is our own test artifact.
        let lib = unsafe { libloading::Library::new(stub_path()) }.expect("open stub");
        let stub = Stub { lib };
        stub.reset();
        stub
    }

    fn call0<R>(&self, name: &[u8]) -> R {
        // Safety: signatures match test-stub/src/lib.rs.
        unsafe {
            let f: libloading::Symbol<unsafe extern "C" fn() -> R> =
                self.lib.get(name).expect("stub symbol");
            f()
        }
    }

    pub fn reset(&self) {
        self.call0::<()>(b"hst_stub_reset\0")
    }

    pub fn count(&self, which: i32) -> i64 {
        // Safety: signature matches the stub.
        unsafe {
            let f: libloading::Symbol<unsafe extern "C" fn(i32) -> i64> =
                self.lib.get(b"hst_stub_count\0").expect("stub symbol");
            f(which)
        }
    }

    pub fn force(&self, which: i32, rc: i32) {
        // Safety: signature matches the stub.
        unsafe {
            let f: libloading::Symbol<unsafe extern "C" fn(i32, i32)> =
                self.lib.get(b"hst_stub_set_rc\0").expect("stub symbol");
            f(which, rc)
        }
    }

    pub fn dims(&self, n: i32, m: i32) {
        // Safety: signature matches the stub.
        unsafe {
            let f: libloading::Symbol<unsafe extern "C" fn(i32, i32)> =
                self.lib.get(b"hst_stub_set_dims\0").expect("stub symbol");
            f(n, m)
        }
    }

    pub fn report_batch(&self, b: i32) {
        // Safety: signature matches the stub.
        unsafe {
            let f: libloading::Symbol<unsafe extern "C" fn(i32)> = self
                .lib
                .get(b"hst_stub_set_batch_report\0")
                .expect("stub symbol");
            f(b)
        }
    }

    pub fn fail_open(&self, why: Option<&str>) {
        let c = why.map(|s| std::ffi::CString::new(s).unwrap());
        // Safety: signature matches the stub; the CString outlives the call.
        unsafe {
            let f: libloading::Symbol<unsafe extern "C" fn(i32, *const std::ffi::c_char)> = self
                .lib
                .get(b"hst_stub_set_open_fail\0")
                .expect("stub symbol");
            match &c {
                Some(s) => f(1, s.as_ptr()),
                None => f(0, std::ptr::null()),
            }
        }
    }

    pub fn last_cols(&self) -> u64 {
        self.call0::<u64>(b"hst_stub_last_cols\0")
    }
    pub fn last_vals(&self) -> u64 {
        self.call0::<u64>(b"hst_stub_last_vals\0")
    }
    pub fn last_y_out(&self) -> u64 {
        self.call0::<u64>(b"hst_stub_last_y_out\0")
    }
    pub fn last_count(&self) -> i32 {
        self.call0::<i32>(b"hst_stub_last_count\0")
    }
    pub fn last_set_len(&self) -> i32 {
        self.call0::<i32>(b"hst_stub_last_set_len\0")
    }
}

/// The stub's counters are process-wide statics and `cargo test` runs tests in
/// parallel threads, so every test takes this gate first. Without it the
/// counters would be a shared mutable resource and the suite would be flaky in
/// exactly the way it is meant to catch.
static GATE: std::sync::Mutex<()> = std::sync::Mutex::new(());

/// A locked, reset stub plus a `Library` loaded from it.
pub struct Fixture {
    pub stub: Stub,
    pub lib: hstcore::Library,
    // Declared last so it is released after the library is unloaded.
    _guard: std::sync::MutexGuard<'static, ()>,
}

pub fn fixture() -> Fixture {
    let guard = GATE.lock().unwrap_or_else(|poisoned| poisoned.into_inner());
    let stub = Stub::open();
    // Safety: the stub is our own test artifact, built from this workspace.
    let lib = unsafe { hstcore::Library::open_at(stub_path()) }.expect("load stub as a Library");
    Fixture {
        stub,
        lib,
        _guard: guard,
    }
}

/// A path that is never opened — the artifact argument only reaches the stub,
/// which ignores it.
pub fn artifact() -> &'static std::path::Path {
    std::path::Path::new("op.bin")
}
