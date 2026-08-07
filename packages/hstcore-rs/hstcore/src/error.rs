//! What can go wrong, kept apart.
//!
//! The ABI's negative return codes mean four different things and call for four
//! different responses: an exhausted quota is a commercial event, a missing
//! shadow grant is a licensing one, bad arguments are a caller bug, and an
//! internal exception is worth reporting upstream. They get four variants.

use thiserror::Error;

/// Everything this crate can fail with.
#[derive(Debug, Error)]
#[non_exhaustive]
pub enum Error {
    /// The shared library could not be loaded, or did not export the ABI.
    #[error("could not load libhstcore: {0}. This crate is only the binding; it \
             ships no library. In an HST Studio download the library is in bin/ \
             (libhstcore.so or libhstcore.dylib) -- pass its path to \
             Library::open_at, since bin/ is not on the dynamic loader's default \
             search path.")]
    Load(#[from] hstcore_sys::LoadError),

    /// `hst_open` returned null. The library's own reason is carried here:
    /// an invalid or expired token, an operator larger than the license
    /// permits, an exhausted file quota, or an unreadable artifact.
    #[error("hst_open refused: {0}")]
    Open(String),

    /// The artifact path could not be represented as a C string.
    #[error("artifact path is not valid UTF-8; the ABI takes a C string")]
    NonUtf8Path,

    /// A string argument contained a NUL byte.
    #[error("{0} contains an interior NUL byte and cannot cross the ABI")]
    InteriorNul(&'static str),

    /// `batch` outside the range the ABI accepts.
    #[error("batch must be in 1..=32, got {0}")]
    BadBatch(i32),

    /// The library disagreed with the requested lane count. Every buffer length
    /// this crate computes derives from it, so it refuses to continue.
    #[error("asked for {requested} lanes, the library reports {reported}; every \
             buffer length here derives from that number")]
    LaneMismatch {
        /// What was asked for.
        requested: i32,
        /// What the library said.
        reported: i32,
    },

    /// A slice was the wrong length for this handle.
    #[error("{what}: expected {expected} values, got {got}")]
    Length {
        /// Which argument.
        what: &'static str,
        /// What the handle's dimensions require.
        expected: usize,
        /// What was passed.
        got: usize,
    },

    /// More delta entries than the ABI's `int32` count can carry.
    #[error("{0} delta entries; the ABI takes an int32 count")]
    TooManyEntries(usize),

    /// Return code `-1`.
    #[error("{entry} returned -1: bad arguments")]
    BadArgs {
        /// The C entry point that reported it.
        entry: &'static str,
    },

    /// Return code `-2`.
    #[error("{entry} returned -2: internal exception inside the library")]
    Internal {
        /// The C entry point that reported it.
        entry: &'static str,
    },

    /// Return code `-3`. Production and shadow budgets are metered separately,
    /// so this names which one is spent.
    #[error("{entry} returned -3: quota exhausted (the other apply budget is \
             metered separately and is unaffected)")]
    QuotaExhausted {
        /// The C entry point that reported it.
        entry: &'static str,
    },

    /// Return code `-4`, from `hst_apply_shadow` only.
    ///
    /// Shadow rights come solely from the signed token. Nothing in this crate,
    /// and no flag or environment variable, can grant them; the token has to be
    /// reissued.
    #[error("hst_apply_shadow returned -4: this license carries no shadow-apply \
             grant, and only a reissued token can add one")]
    ShadowNotGranted,

    /// A negative code the header does not document.
    #[error("{entry} returned {code}: undocumented return code")]
    Unknown {
        /// The C entry point that reported it.
        entry: &'static str,
        /// The code.
        code: i32,
    },

    /// The library reported an operator with a zero or negative dimension.
    #[error("the library reports a degenerate operator: N={n}, M={m}")]
    DegenerateOperator {
        /// Rows.
        n: i32,
        /// Columns.
        m: i32,
    },
}

/// Turn an ABI return code into a `Result`.
pub(crate) fn check(code: i32, entry: &'static str) -> Result<(), Error> {
    match code {
        0 => Ok(()),
        -1 => Err(Error::BadArgs { entry }),
        -2 => Err(Error::Internal { entry }),
        -3 => Err(Error::QuotaExhausted { entry }),
        -4 => Err(Error::ShadowNotGranted),
        code => Err(Error::Unknown { entry, code }),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn zero_is_success() {
        assert!(check(0, "hst_apply_delta").is_ok());
    }

    #[test]
    fn every_documented_code_gets_its_own_variant() {
        let got: Vec<String> = [-1, -2, -3, -4]
            .iter()
            .map(|&c| format!("{:?}", check(c, "hst_apply_shadow").unwrap_err()))
            .map(|s| s.split_whitespace().next().unwrap().to_string())
            .collect();
        let mut unique = got.clone();
        unique.sort();
        unique.dedup();
        assert_eq!(unique.len(), 4, "codes collapsed into {got:?}");
    }

    #[test]
    fn an_undocumented_code_says_so_and_keeps_the_number() {
        let text = check(-42, "hst_set_state").unwrap_err().to_string();
        assert!(text.contains("-42"), "{text}");
        assert!(text.contains("undocumented"), "{text}");
        assert!(text.contains("hst_set_state"), "{text}");
    }

    #[test]
    fn quota_names_the_entry_point_that_reported_it() {
        let production = check(-3, "hst_apply_delta").unwrap_err().to_string();
        let shadow = check(-3, "hst_apply_shadow").unwrap_err().to_string();
        assert!(production.contains("hst_apply_delta"));
        assert!(shadow.contains("hst_apply_shadow"));
        assert_ne!(production, shadow);
        // The two budgets are separate, and the message has to say so or a
        // reader will assume one meter.
        assert!(production.contains("separately"));
    }

    #[test]
    fn the_shadow_grant_error_points_at_the_token() {
        let text = check(-4, "hst_apply_shadow").unwrap_err().to_string();
        assert!(text.contains("token"), "{text}");
        assert!(text.contains("reissued"), "{text}");
    }

    #[test]
    fn errors_are_std_errors() {
        fn assert_error<E: std::error::Error + Send + Sync + 'static>(_: &E) {}
        assert_error(&check(-1, "hst_apply_delta").unwrap_err());
    }
}
