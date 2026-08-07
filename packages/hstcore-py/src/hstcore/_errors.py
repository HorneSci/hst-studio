"""Exception hierarchy for the HST-core Embedded bindings.

Every failure mode the ABI can report gets its own class, because the codes mean
different things to the caller:

* an exhausted quota is a *commercial* condition — buy more, or stop,
* a missing shadow grant is a *licensing* condition — the token was minted
  without that right,
* bad arguments are a *caller* bug,
* an internal exception is a *library* bug worth reporting.

Collapsing them into one string, as the original ctypes shim did, means callers
must parse a message to tell "you have run out of applies" from "you passed a
null pointer".
"""

from __future__ import annotations

__all__ = [
    "HSTError",
    "HSTLoadError",
    "HSTLicenseError",
    "HSTArgumentError",
    "HSTBufferError",
    "HSTInternalError",
    "HSTQuotaError",
    "HSTShadowNotGrantedError",
    "HSTModeError",
    "HSTClosedError",
    "HSTStateExpiredError",
]


class HSTError(Exception):
    """Base class for everything this package raises."""


class HSTLoadError(HSTError):
    """The shared library could not be found, loaded, or bound.

    Raised by :func:`hstcore.load_library`. Also raised when a second, different
    library path is requested after one has already been loaded into the
    process: the binding holds exactly one library per process.
    """


class HSTLicenseError(HSTError):
    """``hst_open`` / ``hst_open_batched`` returned NULL.

    The library writes a short reason into its error buffer; it is carried in
    ``args[0]``. Documented causes: an invalid or expired license token, an
    operator larger than the license permits, an exhausted file quota, or an
    unreadable artifact. The ABI does not distinguish these by code — only by
    that string — so this binding does not invent a distinction.
    """


class HSTArgumentError(HSTError, ValueError):
    """Bad arguments.

    Raised locally for lengths, dimensions and out-of-range values, and for a
    ``-1`` return from the library. Subclasses :class:`ValueError` so ordinary
    argument-checking code catches it.
    """


class HSTBufferError(HSTError, TypeError):
    """A buffer was not in a form that can be passed without copying.

    Wrong dtype, not C-contiguous, wrong number of dimensions, not writeable
    (for an output buffer), or not a :class:`numpy.ndarray` at all.

    This is deliberately an error rather than a silent conversion. The whole
    claim of the embedded path is that a delta reaches the library with no
    serialization; a hidden ``np.asarray`` in the hot loop would be the single
    largest cost in a call the caller believes is free, and it would not appear
    in any profile of the library.
    """


class HSTInternalError(HSTError):
    """The library caught an internal exception (return code ``-2``)."""


class HSTQuotaError(HSTError):
    """A metered quota is exhausted (return code ``-3``).

    From :meth:`hstcore.HSTContext.apply` this is the production apply budget;
    from :meth:`hstcore.HSTContext.apply_shadow` it is the separate shadow
    budget. The two meters are independent.
    """


class HSTShadowNotGrantedError(HSTError):
    """The license carries no shadow-apply grant (return code ``-4``).

    Shadow rights come only from the signed token. No argument, environment
    variable or flag in this binding can enable shadow mode, and this error is
    the library saying so — it is checked on every shadow call, not just the
    first.
    """


class HSTModeError(HSTError):
    """Production and shadow applies were mixed on one handle.

    ``hstcore.h`` warns that ``hst_apply_shadow`` shares held input and output
    buffers with ``hst_apply_delta`` and that the two must never be interleaved
    on one handle. This binding turns that comment into an error: a context that
    has served one kind of apply refuses the other. Open a second context for
    shadow-mode validation.
    """


class HSTClosedError(HSTError):
    """The context has been closed; its handle is gone."""


class HSTStateExpiredError(HSTError):
    """A state view was used after the state it pointed into moved on.

    ``hst_state`` returns a pointer valid only until the next apply, set_state
    or close. Reading through a stale view is a use-after-free in C terms; this
    binding stamps each view and raises here instead.
    """
