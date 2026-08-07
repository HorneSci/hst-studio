/* A recording stub for the HST-core Embedded ABI. NOT the product.
 *
 * ------------------------------------------------------------------------
 * THIS FILE COMPUTES NO DELTA MATHEMATICS, AND MUST NOT BE MADE TO.
 * ------------------------------------------------------------------------
 *
 * It exists to exercise the *plumbing* of the ctypes binding: that the right
 * symbol is called, that pointers arrive unchanged (which is how the no-copy
 * guarantee is tested), that counts and lengths are what the binding said they
 * were, and that each documented return code is turned into the right Python
 * exception.
 *
 * It deliberately does not emulate the engine. A fake that "sort of" applied a
 * delta would teach every reader of these tests a wrong expectation about a
 * product they have not bought yet, and would let a binding bug hide behind
 * plausible-looking numbers. The held state here changes only when
 * hst_set_state copies a caller buffer into it. Nothing is ever computed.
 *
 * Build (done automatically by tests/conftest.py):
 *   cc -shared -fPIC -O0 -o libhst_stub.<ext> hst_stub.c
 */
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#if defined(_WIN32)
#  define STUB_API __declspec(dllexport)
#else
#  define STUB_API __attribute__((visibility("default")))
#endif

struct hst_ctx {
    int32_t batch;
    int32_t n;
    int32_t m;
    double *held;
    double *held_x;   /* the INPUT state, separate from held on purpose */
};

enum {
    C_OPEN = 0,
    C_OPEN_BATCHED = 1,
    C_APPLY = 2,
    C_SHADOW = 3,
    C_BATCH = 4,
    C_STATE = 5,
    C_SET_STATE = 6,
    C_RECOMPUTE = 7,
    C_CLOSE = 8,
    C_SET_INPUT = 9,
    C_SLOTS = 10
};

static long g_calls[C_SLOTS];
static char g_open_fail[256];
static int g_open_fails;
static int32_t g_n = 8, g_m = 5;
static int32_t g_batch_report = -1; /* -1: report what was asked for */
static int g_rc_apply, g_rc_shadow, g_rc_set_state, g_rc_recompute, g_rc_set_input;
static uint64_t g_last_cols, g_last_vals, g_last_y_out;
static int32_t g_last_n = -1;
static int32_t g_last_set_len = -1;
static int32_t g_last_set_input_len = -1;

/* ---- stub control surface (not part of the ABI) ------------------------ */

STUB_API void hst_stub_reset(void) {
    memset(g_calls, 0, sizeof g_calls);
    g_open_fail[0] = 0;
    g_open_fails = 0;
    g_n = 8;
    g_m = 5;
    g_batch_report = -1;
    g_rc_apply = g_rc_shadow = g_rc_set_state = g_rc_recompute = g_rc_set_input = 0;
    g_last_cols = g_last_vals = g_last_y_out = 0;
    g_last_n = -1;
    g_last_set_len = -1;
    g_last_set_input_len = -1;
}

STUB_API void hst_stub_set_dims(int32_t n, int32_t m) { g_n = n; g_m = m; }
STUB_API void hst_stub_set_open_fail(int fails, const char *why) {
    g_open_fails = fails;
    g_open_fail[0] = 0;
    if (why) { strncpy(g_open_fail, why, sizeof g_open_fail - 1); }
}
STUB_API void hst_stub_set_batch_report(int32_t b) { g_batch_report = b; }
STUB_API void hst_stub_set_rc(int which, int rc) {
    if (which == C_APPLY) g_rc_apply = rc;
    else if (which == C_SHADOW) g_rc_shadow = rc;
    else if (which == C_SET_STATE) g_rc_set_state = rc;
    else if (which == C_RECOMPUTE) g_rc_recompute = rc;
    else if (which == C_SET_INPUT) g_rc_set_input = rc;
}
STUB_API long hst_stub_count(int which) {
    return (which >= 0 && which < C_SLOTS) ? g_calls[which] : -1;
}
STUB_API uint64_t hst_stub_last_cols(void) { return g_last_cols; }
STUB_API uint64_t hst_stub_last_vals(void) { return g_last_vals; }
STUB_API uint64_t hst_stub_last_y_out(void) { return g_last_y_out; }
STUB_API int32_t hst_stub_last_n(void) { return g_last_n; }
STUB_API int32_t hst_stub_last_set_len(void) { return g_last_set_len; }
STUB_API int32_t hst_stub_last_set_input_len(void) { return g_last_set_input_len; }

/* ---- the ABI ------------------------------------------------------------ */

static struct hst_ctx *make_ctx(int32_t batch, char *errbuf, size_t errbuf_len) {
    struct hst_ctx *ctx;
    if (g_open_fails) {
        if (errbuf && errbuf_len) {
            strncpy(errbuf, g_open_fail, errbuf_len - 1);
            errbuf[errbuf_len - 1] = 0;
        }
        return NULL;
    }
    ctx = (struct hst_ctx *)calloc(1, sizeof *ctx);
    if (!ctx) return NULL;
    ctx->batch = (g_batch_report >= 0) ? g_batch_report : batch;
    ctx->n = g_n;
    ctx->m = g_m;
    ctx->held = (double *)calloc((size_t)(g_n > 0 ? g_n : 1) * (size_t)(batch > 0 ? batch : 1),
                                 sizeof(double));
    /* Sized by m, not n. The two differ in this stub (n=8, m=5) precisely so a
     * binding that passes an output-shaped length to hst_set_input is caught
     * instead of writing past the end of a buffer that happened to be big
     * enough. */
    ctx->held_x = (double *)calloc((size_t)(g_m > 0 ? g_m : 1) * (size_t)(batch > 0 ? batch : 1),
                                   sizeof(double));
    return ctx;
}

STUB_API struct hst_ctx *hst_open(const char *artifact_path, const char *license_token,
                                  char *errbuf, size_t errbuf_len) {
    (void)artifact_path; (void)license_token;
    g_calls[C_OPEN]++;
    return make_ctx(1, errbuf, errbuf_len);
}

STUB_API struct hst_ctx *hst_open_batched(const char *artifact_path, const char *license_token,
                                          int32_t batch, char *errbuf, size_t errbuf_len) {
    (void)artifact_path; (void)license_token;
    g_calls[C_OPEN_BATCHED]++;
    return make_ctx(batch, errbuf, errbuf_len);
}

/* Records what it was handed. Touches no values. */
STUB_API int hst_apply_delta(struct hst_ctx *ctx, const int32_t *cols, const double *vals,
                             int32_t n, double *y_out) {
    (void)ctx;
    g_calls[C_APPLY]++;
    g_last_cols = (uint64_t)(uintptr_t)cols;
    g_last_vals = (uint64_t)(uintptr_t)vals;
    g_last_y_out = (uint64_t)(uintptr_t)y_out;
    g_last_n = n;
    return g_rc_apply;
}

STUB_API int hst_apply_shadow(struct hst_ctx *ctx, const int32_t *cols, const double *vals,
                              int32_t n, double *y_out) {
    (void)ctx;
    g_calls[C_SHADOW]++;
    g_last_cols = (uint64_t)(uintptr_t)cols;
    g_last_vals = (uint64_t)(uintptr_t)vals;
    g_last_y_out = (uint64_t)(uintptr_t)y_out;
    g_last_n = n;
    return g_rc_shadow;
}

STUB_API int32_t hst_batch(const struct hst_ctx *ctx) {
    g_calls[C_BATCH]++;
    return ctx ? ctx->batch : 0;
}

STUB_API int32_t hst_output_dim(const struct hst_ctx *ctx) { return ctx ? ctx->n : 0; }
STUB_API int32_t hst_input_dim(const struct hst_ctx *ctx) { return ctx ? ctx->m : 0; }

STUB_API const double *hst_state(const struct hst_ctx *ctx) {
    g_calls[C_STATE]++;
    return ctx ? ctx->held : NULL;
}

/* A copy, not a computation: the tests need to see that the bytes the binding
 * passed are the bytes the library received, at the right length. */
STUB_API int hst_set_state(struct hst_ctx *ctx, const double *y0, int32_t len) {
    g_calls[C_SET_STATE]++;
    g_last_set_len = len;
    if (g_rc_set_state) return g_rc_set_state;
    if (ctx && ctx->held && y0 && len > 0) {
        memcpy(ctx->held, y0, (size_t)len * sizeof(double));
    }
    return 0;
}

/* The INPUT state's own setter. Separate buffer, separate length
 * (input_dim*batch, not output_dim*batch), so a binding that confuses the two
 * shows up as a length mismatch here rather than as plausible wrong numbers. */
STUB_API int hst_set_input(struct hst_ctx *ctx, const double *x0, int32_t len) {
    g_calls[C_SET_INPUT]++;
    g_last_set_input_len = len;
    if (g_rc_set_input) return g_rc_set_input;
    if (!ctx || !x0 || len <= 0) return -1;
    if (len != ctx->m * ctx->batch) return -1;
    memcpy(ctx->held_x, x0, (size_t)len * sizeof(double));
    return 0;
}

/* Writes a constant. There is no operator here to recompute from. */
STUB_API int hst_recompute_full(struct hst_ctx *ctx, double *y_out) {
    int32_t i, total;
    g_calls[C_RECOMPUTE]++;
    g_last_y_out = (uint64_t)(uintptr_t)y_out;
    if (g_rc_recompute) return g_rc_recompute;
    if (!ctx || !y_out) return -1;
    total = ctx->n * ctx->batch;
    for (i = 0; i < total; ++i) y_out[i] = -7.0;
    return 0;
}

STUB_API void hst_close(struct hst_ctx *ctx) {
    g_calls[C_CLOSE]++;
    if (!ctx) return;
    free(ctx->held);
    free(ctx->held_x);
    free(ctx);
}

STUB_API const char *hst_version(void) { return "hstcore-stub 0.0.0 (no engine)"; }
