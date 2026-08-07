// Package hstcore binds the HST-core Embedded ABI — the thirteen extern "C"
// functions of hstcore.h, exported under ABI node HSTCORE_1.4.
//
// This package computes nothing. The work is done by libhstcore, a shared
// library this package does not contain -- and does not link against at build
// time, either (see "#cgo LDFLAGS: -lhstcore" below: the linker still needs it
// on its search path). In an HST Studio download the library is already in
// bin/ (libhstcore.so / libhstcore.dylib), Apache-2.0, unmetered, and needs no
// key, token or account -- point CGO_LDFLAGS/LIBRARY_PATH at bin/, since it is
// not on the linker's default search path. A separate, metered build of the
// same library also exists as its own artifact -- that is not "the Enterprise
// build", which is Profile 1 plus Profile 3 and has never been built. Build
// this without the library on
// the linker's path and it fails to link. If what you wanted was a sparse
// delta matvec you can actually run, you want spdelta: Apache-2.0, open, and
// deliberately the baseline rather than a product.
//
// This comment called the library "closed-source" and licence-gated across
// the board until 2026-08-06, which was true of the metered build and
// false of the community one shipped beside this binding in the same tree.
//
// # Lane interleaving
//
// With batch > 1 every state-shaped and value-shaped slice is lane-interleaved:
// element i of lane b is at buf[i*batch+b], NOT buf[b*n+i]. This is the most
// commonly mis-bound detail in this ABI and getting it wrong yields plausible
// numbers that are wrong.
//
// # Two rules
//
//  1. SetState and SetInput go together. They prime different buffers — the
//     output y, and the input x that RecomputeFull computes A*x from. Prime one
//     alone and RecomputeFull refuses with -5 rather than return a vector that
//     disagrees with y by exactly A*x0 forever.
//  2. Shadow and production applies must not share a session. ApplyShadow has
//     identical numerics to ApplyDelta but meters a different budget, and the two
//     share held state.
//
// A Session is not safe for concurrent use.
package hstcore

/*
#cgo LDFLAGS: -lhstcore
#include <stdlib.h>
#include <stdint.h>

typedef struct hst_ctx hst_ctx;

hst_ctx *hst_open(const char *artifact_path, const char *license_token,
                  char *errbuf, size_t errbuf_len);
hst_ctx *hst_open_batched(const char *artifact_path, const char *license_token,
                          int32_t batch, char *errbuf, size_t errbuf_len);
int hst_apply_delta(hst_ctx *ctx, const int32_t *cols, const double *vals,
                    int32_t n, double *y_out);
int hst_apply_shadow(hst_ctx *ctx, const int32_t *cols, const double *vals,
                     int32_t n, double *y_out);
int32_t hst_batch(const hst_ctx *ctx);
int32_t hst_output_dim(const hst_ctx *ctx);
int32_t hst_input_dim(const hst_ctx *ctx);
const double *hst_state(const hst_ctx *ctx);
int hst_set_state(hst_ctx *ctx, const double *y0, int32_t len);
int hst_set_input(hst_ctx *ctx, const double *x0, int32_t len);
int hst_recompute_full(hst_ctx *ctx, double *y_out);
void hst_close(hst_ctx *ctx);
const char *hst_version(void);
*/
import "C"

import (
	"errors"
	"fmt"
	"unsafe"
)

// ABINode is the versioned symbol node the library exports.
const ABINode = "HSTCORE_1.4"

// Symbols is every function in the ABI, in header order.
//
// Thirteen, not twelve: the commit that added hst_apply_shadow said "12 total",
// and both the Python and Rust bindings were written from that wrong count and
// shipped without hst_set_input. The authority is oss/hstcore-abi/abi.json.
var Symbols = []string{
	"hst_open",
	"hst_open_batched",
	"hst_apply_delta",
	"hst_apply_shadow",
	"hst_batch",
	"hst_output_dim",
	"hst_input_dim",
	"hst_state",
	"hst_set_state",
	"hst_set_input",
	"hst_recompute_full",
	"hst_close",
	"hst_version",
}

// Error is a non-zero return from the native boundary.
type Error struct {
	Entry string
	Code  int
}

func (e *Error) Error() string {
	return fmt.Sprintf("%s failed (code %d%s)", e.Entry, e.Code, explain(e.Code))
}

func explain(code int) string {
	switch code {
	case -1:
		return ": bad arguments or length mismatch"
	case -2:
		return ": internal exception in libhstcore"
	case -3:
		return ": shadow quota exhausted"
	case -4:
		return ": licence carries no shadow-apply grant"
	case -5:
		return ": input and output states were not primed together — call SetState " +
			"and SetInput with the same baseline, or neither"
	default:
		return ""
	}
}

// ErrClosed is returned by any method on a closed Session.
var ErrClosed = errors.New("hstcore: session is closed")

// Session is a live HST session: a compiled operator plus the dense state
// evolving under it. Everything is in-process; a network hop in front of this
// destroys the win outright, which is why there is no client mode to reach for.
type Session struct {
	ctx       *C.hst_ctx
	outputDim int
	inputDim  int
	batch     int
}

// Open opens a single-lane session.
func Open(artifactPath, licenseToken string) (*Session, error) {
	return OpenBatched(artifactPath, licenseToken, 1)
}

// OpenBatched opens a session with batch independent right-hand-side lanes
// (1..32), all evolving under the same operator and the same delta sparsity
// pattern. Batching amortizes the sparse index traversal across lanes, which is
// where HST beats a plain exact column delta. At batch == 1 it frequently does
// not — measure before assuming.
func OpenBatched(artifactPath, licenseToken string, batch int) (*Session, error) {
	if batch < 1 || batch > 32 {
		return nil, fmt.Errorf("hstcore: batch must be 1..32, got %d", batch)
	}
	cPath := C.CString(artifactPath)
	defer C.free(unsafe.Pointer(cPath))
	cTok := C.CString(licenseToken)
	defer C.free(unsafe.Pointer(cTok))

	const errLen = 512
	errbuf := (*C.char)(C.calloc(errLen, 1))
	defer C.free(unsafe.Pointer(errbuf))

	var ctx *C.hst_ctx
	if batch == 1 {
		ctx = C.hst_open(cPath, cTok, errbuf, C.size_t(errLen))
	} else {
		ctx = C.hst_open_batched(cPath, cTok, C.int32_t(batch), errbuf, C.size_t(errLen))
	}
	if ctx == nil {
		return nil, fmt.Errorf("hstcore: open failed: %s (artifact=%s)",
			C.GoString(errbuf), artifactPath)
	}

	s := &Session{
		ctx:       ctx,
		batch:     int(C.hst_batch(ctx)),
		outputDim: int(C.hst_output_dim(ctx)),
		inputDim:  int(C.hst_input_dim(ctx)),
	}
	if s.outputDim <= 0 || s.inputDim <= 0 || s.batch <= 0 {
		s.Close()
		return nil, fmt.Errorf("hstcore: library reported a nonsensical shape: "+
			"output=%d input=%d batch=%d", s.outputDim, s.inputDim, s.batch)
	}
	return s, nil
}

// OutputDim is the operator's row count N.
func (s *Session) OutputDim() int { return s.outputDim }

// InputDim is the operator's column count M.
func (s *Session) InputDim() int { return s.inputDim }

// Batch is the number of right-hand-side lanes.
func (s *Session) Batch() int { return s.batch }

// StateSize is outputDim*batch — the length of every state-shaped slice.
func (s *Session) StateSize() int { return s.outputDim * s.batch }

// InputSize is inputDim*batch — the length SetInput requires. It differs from
// StateSize on any non-square operator, which is why SetInput cannot reuse it.
func (s *Session) InputSize() int { return s.inputDim * s.batch }

// Version is the library version string.
func Version() string { return C.GoString(C.hst_version()) }

// ApplyDelta applies a sparse delta. Column cols[i] changes by vals[i*batch+b]
// in lane b. Metered against the licence's max_applies.
func (s *Session) ApplyDelta(cols []int32, vals []float64) ([]float64, error) {
	return s.apply(cols, vals, false)
}

// ApplyShadow is ApplyDelta's numerics metered against max_shadow_applies
// instead, leaving applies_used untouched. This is the primitive SHADOW
// validation is built on: run it beside the real computation, compare against
// RecomputeFull, change nothing.
//
// Use a session opened solely for shadow work. Shadow rights come only from the
// signed licence token — no argument or environment variable can grant them, and
// a licence without max_shadow_applies fails every call with -4.
func (s *Session) ApplyShadow(cols []int32, vals []float64) ([]float64, error) {
	return s.apply(cols, vals, true)
}

func (s *Session) apply(cols []int32, vals []float64, shadow bool) ([]float64, error) {
	if s.ctx == nil {
		return nil, ErrClosed
	}
	if len(vals) != len(cols)*s.batch {
		return nil, fmt.Errorf("hstcore: vals must be len(cols)*batch = %d*%d = %d, got %d "+
			"(values are LANE-INTERLEAVED: vals[i*batch+b])",
			len(cols), s.batch, len(cols)*s.batch, len(vals))
	}
	if len(cols) == 0 {
		return make([]float64, s.StateSize()), nil
	}
	out := make([]float64, s.StateSize())
	cCols := (*C.int32_t)(unsafe.Pointer(&cols[0]))
	cVals := (*C.double)(unsafe.Pointer(&vals[0]))
	cOut := (*C.double)(unsafe.Pointer(&out[0]))
	cN := C.int32_t(len(cols))

	// Branched rather than dispatched through a variable: cgo does not permit a
	// C function to be assigned to one.
	entry := "hst_apply_delta"
	var rc int
	if shadow {
		entry = "hst_apply_shadow"
		rc = int(C.hst_apply_shadow(s.ctx, cCols, cVals, cN, cOut))
	} else {
		rc = int(C.hst_apply_delta(s.ctx, cCols, cVals, cN, cOut))
	}
	if rc != 0 {
		return nil, &Error{Entry: entry, Code: rc}
	}
	return out, nil
}

// State returns a copy of the current dense output state, lane-interleaved.
//
// The native call hands back a borrowed pointer invalidated by the next mutating
// call, so this copies rather than aliasing library memory into Go's heap.
func (s *Session) State() ([]float64, error) {
	if s.ctx == nil {
		return nil, ErrClosed
	}
	p := C.hst_state(s.ctx)
	if p == nil {
		return nil, errors.New("hstcore: hst_state returned NULL")
	}
	n := s.StateSize()
	out := make([]float64, n)
	copy(out, unsafe.Slice((*float64)(unsafe.Pointer(p)), n))
	return out, nil
}

// SetState primes the held dense output state y. Pair with SetInput.
func (s *Session) SetState(y0 []float64) error {
	return s.set(y0, s.StateSize(), "hst_set_state", "StateSize")
}

// SetInput primes the held dense input state x — the buffer RecomputeFull
// computes A*x from. There is otherwise no way to set it other than accumulating
// it one apply at a time from a pristine zero start. Pair with SetState.
func (s *Session) SetInput(x0 []float64) error {
	return s.set(x0, s.InputSize(), "hst_set_input", "InputSize")
}

func (s *Session) set(buf []float64, want int, entry, whatWant string) error {
	if s.ctx == nil {
		return ErrClosed
	}
	if len(buf) != want {
		return fmt.Errorf("hstcore: %s needs %s = %d values, got %d",
			entry, whatWant, want, len(buf))
	}
	var rc C.int
	if entry == "hst_set_state" {
		rc = C.hst_set_state(s.ctx, (*C.double)(unsafe.Pointer(&buf[0])), C.int32_t(want))
	} else {
		rc = C.hst_set_input(s.ctx, (*C.double)(unsafe.Pointer(&buf[0])), C.int32_t(want))
	}
	if int(rc) != 0 {
		return &Error{Entry: entry, Code: int(rc)}
	}
	return nil
}

// RecomputeFull recomputes the whole dense output from scratch. NOT metered.
//
// This is the reference arm — the "before" of a before/after comparison, and the
// only thing that can tell you the delta path is returning the right numbers.
// Assert against it every repeat, not once: three defects on one probe in this
// estate produced clean, well-formed, entirely wrong timings because each arm did
// the right amount of work with the wrong values.
//
// Returns code -5 if the held input and output states were not primed together.
func (s *Session) RecomputeFull() ([]float64, error) {
	if s.ctx == nil {
		return nil, ErrClosed
	}
	out := make([]float64, s.StateSize())
	rc := int(C.hst_recompute_full(s.ctx, (*C.double)(unsafe.Pointer(&out[0]))))
	if rc != 0 {
		return nil, &Error{Entry: "hst_recompute_full", Code: rc}
	}
	return out, nil
}

// Close releases the handle. Idempotent.
func (s *Session) Close() {
	if s.ctx != nil {
		C.hst_close(s.ctx)
		s.ctx = nil
	}
}
