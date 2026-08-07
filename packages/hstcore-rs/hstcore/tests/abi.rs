//! What crosses the FFI boundary, against the recording stub.

mod common;

use common::{fixture, APPLY, BATCH, CLOSE, OPEN, OPEN_BATCHED, RECOMPUTE, SET_STATE, SHADOW};
use hstcore::Error;

const TOKEN: &str = "test-token";

#[test]
fn single_lane_goes_through_the_plain_open() {
    let f = fixture();
    let session = f.lib.open(common::artifact(), TOKEN).unwrap();
    assert_eq!(session.batch(), 1);
    assert_eq!(f.stub.count(OPEN), 1);
    assert_eq!(f.stub.count(OPEN_BATCHED), 0);
}

#[test]
fn batched_open_is_a_different_entry_point() {
    let f = fixture();
    f.stub.dims(64, 40);
    let session = f.lib.open_batched(common::artifact(), TOKEN, 8).unwrap();
    assert_eq!(session.batch(), 8);
    assert_eq!(session.output_dim(), 64);
    assert_eq!(session.input_dim(), 40);
    assert_eq!(session.state_len(), 64 * 8);
    assert_eq!(f.stub.count(OPEN_BATCHED), 1);
    assert_eq!(f.stub.count(OPEN), 0);
}

#[test]
fn batch_out_of_range_never_reaches_the_library() {
    let f = fixture();
    for bad in [0, -1, 33] {
        assert!(matches!(
            f.lib.open_batched(common::artifact(), TOKEN, bad),
            Err(Error::BadBatch(_))
        ));
    }
    assert_eq!(f.stub.count(OPEN_BATCHED), 0);
}

#[test]
fn lane_count_is_read_back_not_assumed() {
    let f = fixture();
    f.stub.report_batch(3);
    let got = f.lib.open_batched(common::artifact(), TOKEN, 8);
    assert!(matches!(
        got,
        Err(Error::LaneMismatch {
            requested: 8,
            reported: 3
        })
    ));
    assert_eq!(f.stub.count(BATCH), 1);
    assert_eq!(f.stub.count(CLOSE), 1, "the handle must not leak");
}

#[test]
fn degenerate_operator_is_refused_and_closed() {
    let f = fixture();
    f.stub.dims(0, 5);
    assert!(matches!(
        f.lib.open(common::artifact(), TOKEN),
        Err(Error::DegenerateOperator { n: 0, m: 5 })
    ));
    assert_eq!(f.stub.count(CLOSE), 1);
}

#[test]
fn open_failure_carries_the_libraries_reason() {
    let f = fixture();
    f.stub.fail_open(Some("license expired 2026-01-01"));
    // Bound to a local, because a Context may not outlive the Library it came
    // from — which is itself a thing this crate enforces at compile time.
    let got = f.lib.open(common::artifact(), TOKEN);
    match got {
        Err(Error::Open(reason)) => assert_eq!(reason, "license expired 2026-01-01"),
        other => panic!("expected Error::Open, got {other:?}"),
    }
}

#[test]
fn open_failure_with_no_reason_still_explains() {
    let f = fixture();
    f.stub.fail_open(Some("")); // refuses, and writes nothing into errbuf
    let got = f.lib.open(common::artifact(), TOKEN);
    match got {
        Err(Error::Open(reason)) => assert!(reason.contains("license"), "{reason}"),
        other => panic!("expected Error::Open, got {other:?}"),
    }
}

#[test]
fn slices_reach_c_without_being_copied() {
    let f = fixture();
    let mut session = f.lib.open(common::artifact(), TOKEN).unwrap();
    let cols: Vec<i32> = (0..4).collect();
    let vals = vec![1.0f64; 4];
    session.apply(&cols, &vals).unwrap();
    assert_eq!(f.stub.last_cols(), cols.as_ptr() as u64);
    assert_eq!(f.stub.last_vals(), vals.as_ptr() as u64);
    assert_eq!(f.stub.last_count(), 4);
}

#[test]
fn apply_without_a_buffer_passes_null() {
    let f = fixture();
    let mut session = f.lib.open(common::artifact(), TOKEN).unwrap();
    session.apply(&[0, 1], &[1.0, 2.0]).unwrap();
    assert_eq!(f.stub.last_y_out(), 0, "the dense output stays inside");
}

#[test]
fn apply_into_passes_the_callers_buffer() {
    let f = fixture();
    let mut session = f.lib.open(common::artifact(), TOKEN).unwrap();
    let mut y = vec![0.0; session.state_len()];
    let ptr = y.as_ptr() as u64;
    session.apply_into(&[0, 1], &[1.0, 2.0], &mut y).unwrap();
    assert_eq!(f.stub.last_y_out(), ptr);
}

#[test]
fn vals_must_be_cols_times_batch() {
    let f = fixture();
    let mut session = f.lib.open_batched(common::artifact(), TOKEN, 4).unwrap();
    let err = session.apply(&[0, 1, 2], &[1.0; 3]).unwrap_err();
    assert!(matches!(
        err,
        Error::Length {
            what: "vals",
            expected: 12,
            got: 3
        }
    ));
    assert_eq!(f.stub.count(APPLY), 0, "refused before the call");

    session.apply(&[0, 1, 2], &[1.0; 12]).unwrap();
    assert_eq!(f.stub.count(APPLY), 1);
}

#[test]
fn output_buffer_must_be_state_len() {
    let f = fixture();
    let mut session = f.lib.open_batched(common::artifact(), TOKEN, 2).unwrap();
    let mut too_small = vec![0.0; session.state_len() - 1];
    let err = session
        .apply_into(&[0], &[1.0, 2.0], &mut too_small)
        .unwrap_err();
    assert!(matches!(err, Error::Length { what: "y_out", .. }));
    assert_eq!(f.stub.count(APPLY), 0);
}

#[test]
fn an_empty_delta_is_allowed() {
    let f = fixture();
    let mut session = f.lib.open(common::artifact(), TOKEN).unwrap();
    session.apply(&[], &[]).unwrap();
    assert_eq!(f.stub.last_count(), 0);
}

#[test]
fn return_codes_keep_their_meanings() {
    let f = fixture();
    let mut session = f.lib.open(common::artifact(), TOKEN).unwrap();
    for (code, matches) in [
        (-1, matches_bad_args as fn(&Error) -> bool),
        (-2, matches_internal),
        (-3, matches_quota),
        (-99, matches_unknown),
    ] {
        f.stub.force(APPLY, code);
        let err = session.apply(&[0], &[1.0]).unwrap_err();
        assert!(matches(&err), "code {code} became {err:?}");
    }
}

fn matches_bad_args(e: &Error) -> bool {
    matches!(e, Error::BadArgs { entry: "hst_apply_delta" })
}
fn matches_internal(e: &Error) -> bool {
    matches!(e, Error::Internal { .. })
}
fn matches_quota(e: &Error) -> bool {
    matches!(e, Error::QuotaExhausted { .. })
}
fn matches_unknown(e: &Error) -> bool {
    matches!(e, Error::Unknown { code: -99, .. })
}

#[test]
fn shadow_calls_the_shadow_entry_point() {
    let f = fixture();
    let session = f.lib.open(common::artifact(), TOKEN).unwrap();
    let mut shadow = session.into_shadow();
    shadow.apply(&[0], &[1.0]).unwrap();
    assert_eq!(f.stub.count(SHADOW), 1);
    assert_eq!(f.stub.count(APPLY), 0, "production entry must be untouched");
}

#[test]
fn into_shadow_reuses_the_handle_rather_than_reopening() {
    let f = fixture();
    let session = f.lib.open(common::artifact(), TOKEN).unwrap();
    let shadow = session.into_shadow();
    assert_eq!(f.stub.count(OPEN), 1);
    assert_eq!(f.stub.count(CLOSE), 0, "the old wrapper must not close it");
    drop(shadow);
    assert_eq!(f.stub.count(CLOSE), 1);
}

#[test]
fn a_missing_shadow_grant_is_its_own_error() {
    let f = fixture();
    f.stub.force(SHADOW, -4);
    let mut shadow = f.lib.open(common::artifact(), TOKEN).unwrap().into_shadow();
    assert!(matches!(
        shadow.apply(&[0], &[1.0]),
        Err(Error::ShadowNotGranted)
    ));
}

#[test]
fn dropping_a_session_closes_it_exactly_once() {
    let f = fixture();
    {
        let _session = f.lib.open(common::artifact(), TOKEN).unwrap();
        assert_eq!(f.stub.count(CLOSE), 0);
    }
    assert_eq!(f.stub.count(CLOSE), 1);
}

#[test]
fn state_round_trips_through_set_state() {
    let f = fixture();
    f.stub.dims(6, 6);
    let mut session = f.lib.open(common::artifact(), TOKEN).unwrap();
    let y0: Vec<f64> = (0..6).map(|i| i as f64 * 0.5).collect();
    session.set_state(&y0).unwrap();
    assert_eq!(f.stub.last_set_len(), 6);
    assert_eq!(session.state(), &y0[..]);
}

#[test]
fn set_state_length_is_checked_here_not_there() {
    let f = fixture();
    f.stub.dims(6, 6);
    let mut session = f.lib.open(common::artifact(), TOKEN).unwrap();
    let err = session.set_state(&[0.0; 5]).unwrap_err();
    assert!(matches!(
        err,
        Error::Length {
            what: "y0",
            expected: 6,
            got: 5
        }
    ));
    assert_eq!(f.stub.count(SET_STATE), 0);
}

#[test]
fn set_state_errors_map() {
    let f = fixture();
    f.stub.dims(6, 6);
    f.stub.force(SET_STATE, -1);
    let mut session = f.lib.open(common::artifact(), TOKEN).unwrap();
    assert!(matches!(
        session.set_state(&[0.0; 6]),
        Err(Error::BadArgs {
            entry: "hst_set_state"
        })
    ));
}

#[test]
fn state_is_lane_interleaved_and_the_right_length() {
    let f = fixture();
    f.stub.dims(5, 5);
    let session = f.lib.open_batched(common::artifact(), TOKEN, 4).unwrap();
    assert_eq!(session.state().len(), 20);
    assert_eq!(session.state_len(), 20);
}

#[test]
fn recompute_full_writes_into_the_callers_buffer() {
    let f = fixture();
    f.stub.dims(6, 6);
    let session = f.lib.open(common::artifact(), TOKEN).unwrap();
    let mut reference = vec![0.0; session.state_len()];
    session.recompute_full(&mut reference).unwrap();
    assert_eq!(f.stub.count(RECOMPUTE), 1);
    assert!(reference.iter().all(|&v| v == -7.0), "{reference:?}");
}

#[test]
fn recompute_full_checks_the_buffer_length() {
    let f = fixture();
    f.stub.dims(6, 6);
    let session = f.lib.open(common::artifact(), TOKEN).unwrap();
    let mut short = vec![0.0; 5];
    assert!(matches!(
        session.recompute_full(&mut short),
        Err(Error::Length { what: "y_out", .. })
    ));
    assert_eq!(f.stub.count(RECOMPUTE), 0);
}

#[test]
fn recompute_full_errors_map() {
    let f = fixture();
    f.stub.force(RECOMPUTE, -2);
    let session = f.lib.open(common::artifact(), TOKEN).unwrap();
    let mut reference = vec![0.0; session.state_len()];
    assert!(matches!(
        session.recompute_full(&mut reference),
        Err(Error::Internal {
            entry: "hst_recompute_full"
        })
    ));
}

#[test]
fn a_state_borrow_survives_recompute_full() {
    // Compiles only because recompute_full takes &self — which is the header's
    // claim that it leaves the held state alone, expressed as a signature.
    let f = fixture();
    f.stub.dims(6, 6);
    let session = f.lib.open(common::artifact(), TOKEN).unwrap();
    let y = session.state();
    let mut reference = vec![0.0; session.state_len()];
    session.recompute_full(&mut reference).unwrap();
    assert_eq!(y.len(), 6);
}

#[test]
fn version_comes_from_the_library() {
    let f = fixture();
    assert_eq!(f.lib.version().unwrap(), "hstcore-stub 0.0.0 (no engine)");
}

#[test]
fn the_symbol_list_is_the_whole_abi() {
    assert_eq!(hstcore::SYMBOLS.len(), 13);
    for name in [
        "hst_open_batched",
        "hst_apply_shadow",
        "hst_batch",
        "hst_set_input",
        "hst_recompute_full",
    ] {
        assert!(hstcore::SYMBOLS.contains(&name), "{name} missing");
    }
    assert_eq!(hstcore::ABI_NODE, "HSTCORE_1.4");
}

#[test]
fn a_missing_library_is_a_load_error() {
    // Safety: the path does not exist, so nothing is executed.
    let got = unsafe { hstcore::Library::open_at("/nonexistent/libhstcore-nope.so") };
    assert!(matches!(got, Err(Error::Load(_))));
    assert!(format!("{}", got.unwrap_err()).contains("binding"));
}

#[test]
fn a_library_without_the_abi_is_refused() {
    let path = if cfg!(target_os = "macos") {
        "/usr/lib/libSystem.B.dylib"
    } else {
        "libc.so.6"
    };
    // Safety: a system library; opening it runs only its own initializers.
    let got = unsafe { hstcore::Library::open_at(path) };
    assert!(matches!(got, Err(Error::Load(_))), "expected a load error");
}
