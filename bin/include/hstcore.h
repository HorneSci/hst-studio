/* HST-core Embedded — public ABI.
 *
 * This is the ONLY header shipped to customers. It exposes an opaque handle and
 * a handful of C functions. No algorithm types, no core.hpp. The engine runs
 * in-process: you pass a sparse delta as native arrays and read the dense output
 * back with zero serialization — the only transport that preserves HST's sub-ms win.
 *
 * Licensing is enforced inside the compiled (stripped) library, not here.
 */
#ifndef HSTCORE_H
#define HSTCORE_H

#include <stdint.h>
#include <stddef.h>

#if defined(_WIN32)
#  define HSTCORE_API __declspec(dllexport)
#else
#  define HSTCORE_API __attribute__((visibility("default")))
#endif

#ifdef __cplusplus
extern "C" {
#endif

typedef struct hst_ctx hst_ctx;

/* Open a session from a compiled operator artifact (.bin) under a signed license
 * token. Returns NULL on failure — invalid/expired license, operator larger than
 * the license permits, or an unreadable artifact — and writes a short reason into
 * errbuf (if errbuf != NULL). The returned handle holds the operator plus the
 * evolving dense state; free it with hst_close(). */
HSTCORE_API hst_ctx *hst_open(const char *artifact_path, const char *license_token,
                              char *errbuf, size_t errbuf_len);

/* Like hst_open, but the session carries `batch` independent right-hand-side
 * lanes (1 <= batch <= 32) evolving under the same operator and the same delta
 * sparsity pattern. All state and delta buffers are lane-interleaved:
 * state[row*batch + b], delta vals[i*batch + b]. Batching amortizes the sparse
 * index traversal across lanes — this is where HST beats a plain exact delta. */
HSTCORE_API hst_ctx *hst_open_batched(const char *artifact_path, const char *license_token,
                                      int32_t batch, char *errbuf, size_t errbuf_len);

/* Apply a sparse delta of n entries to the held state, in-process, with no
 * serialization. Column cols[i] changes by vals[i*batch + b] in lane b (for an
 * hst_open handle, batch is 1 and vals is simply vals[i]). If y_out != NULL it
 * must have length hst_output_dim()*hst_batch() and receives the updated dense
 * output. Returns 0 on success, negative on error. */
HSTCORE_API int hst_apply_delta(hst_ctx *ctx, const int32_t *cols, const double *vals,
                                int32_t n, double *y_out);

/* Shadow-mode apply: identical numerics to hst_apply_delta, but meters against
 * the license's max_shadow_applies budget instead of max_applies, and does NOT
 * touch applies_used. Shadow rights come exclusively from the signed license
 * token's max_shadow_applies field -- no caller argument, env var, or flag can
 * enable shadow mode. Returns 0 success; -1 bad args; -2 internal exception;
 * -3 shadow quota exhausted; -4 license carries no shadow-apply grant
 * (max_shadow_applies <= 0), checked unconditionally on every call.
 *
 * WARNING: shares held state (input/output buffers) with hst_apply_delta on
 * the same handle. Never interleave shadow and production applies on one
 * hst_ctx -- open a separate handle for shadow-mode validation. */
HSTCORE_API int hst_apply_shadow(hst_ctx *ctx, const int32_t *cols, const double *vals,
                                 int32_t n, double *y_out);

/* Number of right-hand-side lanes for this handle (1 for hst_open). */
HSTCORE_API int32_t hst_batch(const hst_ctx *ctx);

/* Output dimension N of the operator (rows). The held state buffer has
 * N*hst_batch() doubles, lane-interleaved. */
HSTCORE_API int32_t hst_output_dim(const hst_ctx *ctx);

/* Input dimension M of the operator (columns). */
HSTCORE_API int32_t hst_input_dim(const hst_ctx *ctx);

/* Zero-copy read of the current dense output state (length
 * hst_output_dim()*hst_batch(), lane-interleaved). Valid until the next
 * hst_apply_delta / hst_set_state / hst_close. */
HSTCORE_API const double *hst_state(const hst_ctx *ctx);

/* Set the internal dense output state (len must equal
 * hst_output_dim()*hst_batch()). Use to prime a nonzero starting state.
 *
 * WARNING: this sets ONLY the output state y. The internal input state x —
 * the buffer hst_recompute_full() computes A*x from — is separate and is
 * otherwise mutated only inside hst_apply_delta/hst_apply_shadow. Priming y
 * alone (e.g. from your own full recompute done at startup) without also
 * calling hst_set_input() with the SAME baseline leaves x at its pristine
 * zero value: hst_recompute_full() would then silently disagree with y by
 * exactly A*x0, forever. Always pair this call with hst_set_input() using
 * the corresponding baseline. hst_recompute_full() refuses (-5) rather than
 * return a silently wrong vector when the two have not been primed together
 * — see hst_set_input().
 *
 * Returns 0 on success, -1 on a null pointer or length mismatch. */
HSTCORE_API int hst_set_state(hst_ctx *ctx, const double *y0, int32_t len);

/* Set the internal dense input state x (len must equal
 * hst_input_dim()*hst_batch()). This is the buffer hst_recompute_full()
 * computes A*x from; there is otherwise no way to set it other than
 * accumulating it one hst_apply_delta()/hst_apply_shadow() at a time from
 * its pristine zero start. Pair this with hst_set_state() using the
 * corresponding baseline output — priming only one of the pair leaves the
 * handle's input/output states in a state hst_recompute_full() refuses to
 * use (see its doc comment).
 *
 * Returns 0 on success, -1 on a null pointer or length mismatch. */
HSTCORE_API int hst_set_input(hst_ctx *ctx, const double *x0, int32_t len);

/* Reference baseline: recompute the full dense output A*x from scratch for the
 * current held input state — the "before" in a before/after comparison. Writes
 * hst_output_dim()*hst_batch() doubles into y_out. NOT metered: this is the
 * correctness/telemetry reference the delta path is checked against, not the
 * product hot path. Returns 0 on success; -1 bad args; -2 internal exception;
 * -5 refused because the held input state x and output state y are not known
 * to be consistent with each other — hst_set_state() was called without a
 * matching hst_set_input() (or vice versa). Call both together with the same
 * baseline (or neither, leaving the pristine zero state, which is always
 * consistent) before calling this. */
HSTCORE_API int hst_recompute_full(hst_ctx *ctx, double *y_out);

/* Release a handle. Safe on NULL. */
HSTCORE_API void hst_close(hst_ctx *ctx);

/* Library version string, e.g. "hstcore 1.4.0". */
HSTCORE_API const char *hst_version(void);

#ifdef __cplusplus
}
#endif

#endif /* HSTCORE_H */
