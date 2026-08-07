package hstcore

// Conformance tests against the shared C stub — the same stub hstcore-py and
// hstcore-java use, so "conformance" means the bindings agree about one library
// rather than each agreeing with itself.
//
// The stub reports a deliberately NON-SQUARE operator (n=8, m=5). That is the
// whole point: a binding that confuses StateSize with InputSize passes every
// square test and fails here.
//
// Build and run:
//
//	cc -shared -fPIC -o /tmp/stub/libhstcore.dylib ../hstcore-py/tests/stub/hst_stub.c
//	CGO_LDFLAGS="-L/tmp/stub" go test -ldflags="-r /tmp/stub" ./...

import (
	"testing"
)

const token = "stub-token"

func open(t *testing.T, batch int) *Session {
	t.Helper()
	s, err := OpenBatched("operator.bin", token, batch)
	if err != nil {
		t.Skipf("stub library not loadable (%v) — set CGO_LDFLAGS and the rpath", err)
	}
	t.Cleanup(s.Close)
	return s
}

func TestSymbolListIsTheWholeABI(t *testing.T) {
	if len(Symbols) != 13 {
		t.Fatalf("Symbols has %d entries, the ABI has 13", len(Symbols))
	}
	for _, want := range []string{"hst_set_input", "hst_apply_shadow", "hst_recompute_full"} {
		found := false
		for _, s := range Symbols {
			if s == want {
				found = true
			}
		}
		if !found {
			t.Errorf("Symbols is missing %q", want)
		}
	}
}

func TestDimensionsAreReadFromTheLibrary(t *testing.T) {
	s := open(t, 4)
	if s.OutputDim() != 8 {
		t.Errorf("OutputDim = %d, want 8", s.OutputDim())
	}
	if s.InputDim() != 5 {
		t.Errorf("InputDim = %d, want 5", s.InputDim())
	}
	if s.Batch() != 4 {
		t.Errorf("Batch = %d, want 4", s.Batch())
	}
}

func TestStateSizeAndInputSizeDiffer(t *testing.T) {
	s := open(t, 4)
	if s.StateSize() != 32 {
		t.Errorf("StateSize = %d, want outputDim*batch = 32", s.StateSize())
	}
	if s.InputSize() != 20 {
		t.Errorf("InputSize = %d, want inputDim*batch = 20", s.InputSize())
	}
	if s.StateSize() == s.InputSize() {
		t.Fatal("StateSize and InputSize are equal; the stub is supposed to be non-square, " +
			"which is what makes the SetState/SetInput confusion detectable")
	}
}

func TestValsMustBeColsTimesBatch(t *testing.T) {
	s := open(t, 4)
	if _, err := s.ApplyDelta([]int32{0, 1}, []float64{1.0}); err == nil {
		t.Fatal("a vals slice of the wrong length was accepted; values are lane-interleaved " +
			"so the length is len(cols)*batch")
	}
	if _, err := s.ApplyDelta([]int32{0, 2, 4}, make([]float64, 12)); err != nil {
		t.Fatalf("a correctly-sized delta was rejected: %v", err)
	}
}

func TestSetStateAndSetInputWantDifferentLengths(t *testing.T) {
	s := open(t, 4)
	if err := s.SetState(make([]float64, s.StateSize())); err != nil {
		t.Errorf("SetState rejected StateSize: %v", err)
	}
	if err := s.SetState(make([]float64, s.InputSize())); err == nil {
		t.Error("SetState accepted InputSize")
	}
	if err := s.SetInput(make([]float64, s.InputSize())); err != nil {
		t.Errorf("SetInput rejected InputSize: %v", err)
	}
	if err := s.SetInput(make([]float64, s.StateSize())); err == nil {
		t.Error("SetInput accepted StateSize")
	}
}

func TestStateIsACopyNotAView(t *testing.T) {
	s := open(t, 4)
	prime := make([]float64, s.StateSize())
	for i := range prime {
		prime[i] = float64(i)
	}
	if err := s.SetState(prime); err != nil {
		t.Fatalf("SetState: %v", err)
	}
	first, err := s.State()
	if err != nil {
		t.Fatalf("State: %v", err)
	}
	if len(first) != s.StateSize() {
		t.Fatalf("State len = %d, want %d", len(first), s.StateSize())
	}
	// Mutating the returned slice must not reach into library memory.
	first[0] = -12345
	second, err := s.State()
	if err != nil {
		t.Fatalf("State: %v", err)
	}
	if second[0] == -12345 {
		t.Fatal("State() aliases library memory; it must copy, because the native " +
			"pointer is invalidated by the next mutating call")
	}
}

func TestRecomputeFullReturnsStateSize(t *testing.T) {
	s := open(t, 4)
	ref, err := s.RecomputeFull()
	if err != nil {
		t.Fatalf("RecomputeFull: %v", err)
	}
	if len(ref) != s.StateSize() {
		t.Errorf("RecomputeFull len = %d, want %d", len(ref), s.StateSize())
	}
}

func TestShadowApplyIsReachable(t *testing.T) {
	s := open(t, 4)
	out, err := s.ApplyShadow([]int32{0, 2, 4}, make([]float64, 12))
	if err != nil {
		t.Fatalf("ApplyShadow: %v", err)
	}
	if len(out) != s.StateSize() {
		t.Errorf("ApplyShadow len = %d, want %d", len(out), s.StateSize())
	}
}

func TestUseAfterCloseIsRefused(t *testing.T) {
	s, err := Open("operator.bin", token)
	if err != nil {
		t.Skipf("stub not loadable: %v", err)
	}
	s.Close()
	s.Close() // idempotent
	if _, err := s.State(); err != ErrClosed {
		t.Errorf("State after close returned %v, want ErrClosed", err)
	}
	if err := s.SetState(make([]float64, s.StateSize())); err != ErrClosed {
		t.Errorf("SetState after close returned %v, want ErrClosed", err)
	}
}

func TestErrorCodesExplainThemselves(t *testing.T) {
	for code, want := range map[int]string{
		-3: "shadow quota exhausted",
		-4: "no shadow-apply grant",
		-5: "primed together",
	} {
		e := &Error{Entry: "hst_apply_shadow", Code: code}
		if msg := e.Error(); !contains(msg, want) {
			t.Errorf("code %d message %q does not explain %q", code, msg, want)
		}
	}
}

func contains(s, sub string) bool {
	for i := 0; i+len(sub) <= len(s); i++ {
		if s[i:i+len(sub)] == sub {
			return true
		}
	}
	return false
}
