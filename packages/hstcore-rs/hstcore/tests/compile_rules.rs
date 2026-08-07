//! The two rules `hstcore.h` states as comments, checked as compiler errors.
//!
//! The crate's `compile_fail` doctests document these, but a `compile_fail`
//! block passes when the snippet fails to compile for *any* reason — a
//! misspelled method passes it just as well as the borrow violation it is
//! supposed to demonstrate — and `rustdoc` does not enforce the error code the
//! block is pinned to. (Measured: changing `E0382` to `E0499` in a doctest
//! changes nothing.)
//!
//! So these tests run `rustc` and assert on the *code it emits*. A snippet that
//! must compile runs alongside them as the control: without it, a broken
//! invocation would make every snippet "fail" and this file would pass while
//! proving nothing.

use std::path::{Path, PathBuf};
use std::process::Command;

fn target_dirs() -> (PathBuf, PathBuf) {
    let exe = std::env::current_exe().expect("current_exe");
    let deps = exe.parent().expect("deps").to_path_buf();
    let profile = deps.parent().expect("profile").to_path_buf();
    (profile, deps)
}

/// The freshest `libhstcore-<hash>.rlib` cargo has built for this run.
fn crate_rlib() -> PathBuf {
    let (_, deps) = target_dirs();
    let mut best: Option<(std::time::SystemTime, PathBuf)> = None;
    for entry in std::fs::read_dir(&deps).expect("read deps") {
        let path = entry.expect("dir entry").path();
        let name = match path.file_name().and_then(|s| s.to_str()) {
            Some(n) => n,
            None => continue,
        };
        if !name.starts_with("libhstcore-") || !name.ends_with(".rlib") {
            continue;
        }
        let stamp = path
            .metadata()
            .and_then(|m| m.modified())
            .unwrap_or(std::time::SystemTime::UNIX_EPOCH);
        if best.as_ref().map(|(t, _)| stamp > *t).unwrap_or(true) {
            best = Some((stamp, path));
        }
    }
    best.map(|(_, p)| p).unwrap_or_else(|| {
        panic!(
            "no libhstcore-*.rlib under {}; build the workspace first",
            deps.display()
        )
    })
}

struct Outcome {
    ok: bool,
    stderr: String,
}

fn compile(snippet: &str, tag: &str) -> Outcome {
    let (_, deps) = target_dirs();
    let dir = std::env::temp_dir().join(format!("hstcore-compile-rules-{tag}"));
    std::fs::create_dir_all(&dir).expect("temp dir");
    let source: &Path = &dir.join("snippet.rs");
    std::fs::write(source, snippet).expect("write snippet");

    let out = Command::new(std::env::var("RUSTC").unwrap_or_else(|_| "rustc".into()))
        .arg("--edition=2021")
        .arg("--crate-type=lib")
        .arg("--emit=metadata")
        .arg("--out-dir")
        .arg(&dir)
        .arg("-L")
        .arg(format!("dependency={}", deps.display()))
        .arg("--extern")
        .arg(format!("hstcore={}", crate_rlib().display()))
        .arg(source)
        .output()
        .expect("run rustc");

    Outcome {
        ok: out.status.success(),
        stderr: String::from_utf8_lossy(&out.stderr).into_owned(),
    }
}

/// The control. If this fails, every other assertion in this file is worthless,
/// because "did not compile" would mean nothing.
#[test]
fn the_harness_can_compile_a_correct_program() {
    let got = compile(
        r#"
        pub fn demo(session: &mut hstcore::Context) -> Result<(), hstcore::Error> {
            let kept: Vec<f64> = session.state().to_vec();
            session.apply(&[0], &[1.0])?;
            let mut reference = vec![0.0; session.state_len()];
            session.recompute_full(&mut reference)?;
            let _ = kept.len();
            Ok(())
        }
        "#,
        "control",
    );
    assert!(got.ok, "the control snippet must compile:\n{}", got.stderr);
}

#[test]
fn a_state_borrow_cannot_span_an_apply() {
    let got = compile(
        r#"
        pub fn demo(session: &mut hstcore::Context) -> Result<(), hstcore::Error> {
            let y = session.state();
            session.apply(&[0], &[1.0])?;
            println!("{}", y[0]);
            Ok(())
        }
        "#,
        "state-borrow",
    );
    assert!(!got.ok, "this must not compile");
    assert!(
        got.stderr.contains("E0502"),
        "expected a borrow conflict (E0502), got:\n{}",
        got.stderr
    );
    assert!(
        got.stderr.contains("cannot borrow"),
        "expected the borrow checker to be the one objecting, got:\n{}",
        got.stderr
    );
}

#[test]
fn a_production_session_is_gone_once_it_becomes_a_shadow_session() {
    let got = compile(
        r#"
        pub fn demo(mut session: hstcore::Context) -> Result<(), hstcore::Error> {
            let mut shadow = session.into_shadow();
            shadow.apply(&[0], &[1.0])?;
            session.apply(&[0], &[1.0])?;
            Ok(())
        }
        "#,
        "into-shadow",
    );
    assert!(!got.ok, "this must not compile");
    assert!(
        got.stderr.contains("E0382"),
        "expected a use-after-move (E0382), got:\n{}",
        got.stderr
    );
    assert!(
        got.stderr.contains("moved"),
        "expected the move to be the reason, got:\n{}",
        got.stderr
    );
}

#[test]
fn a_session_cannot_cross_threads() {
    let got = compile(
        r#"
        fn needs_send<T: Send>(_: T) {}
        pub fn demo(session: hstcore::Context) { needs_send(session); }
        "#,
        "send",
    );
    assert!(!got.ok, "this must not compile");
    assert!(
        got.stderr.contains("E0277"),
        "expected an unsatisfied Send bound (E0277), got:\n{}",
        got.stderr
    );
    assert!(
        got.stderr.contains("Send"),
        "expected Send to be named, got:\n{}",
        got.stderr
    );
}

#[test]
fn a_shadow_session_cannot_cross_threads_either() {
    let got = compile(
        r#"
        fn needs_sync<T: Sync>(_: T) {}
        pub fn demo(session: hstcore::ShadowContext) { needs_sync(session); }
        "#,
        "sync",
    );
    assert!(!got.ok, "this must not compile");
    assert!(got.stderr.contains("E0277"), "got:\n{}", got.stderr);
}

#[test]
fn a_session_cannot_outlive_the_library_it_came_from() {
    let got = compile(
        r#"
        pub fn demo(path: &str, token: &str) -> Result<hstcore::Context<'static>, hstcore::Error> {
            let lib = unsafe { hstcore::Library::open_at(path)? };
            lib.open(std::path::Path::new("op.bin"), token)
        }
        "#,
        "outlive",
    );
    assert!(!got.ok, "this must not compile");
    assert!(
        got.stderr.contains("E0515") || got.stderr.contains("E0106") || got.stderr.contains("E0597"),
        "expected a lifetime error, got:\n{}",
        got.stderr
    );
}
