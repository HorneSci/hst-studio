# Bit-exactness probes. Public domain (CC0 1.0).
#
# NAME YOUR COMPILER. On macOS `g++` and `cc` are Apple clang, not GCC, and
# they are different toolchains with different codegen. Every result reported
# in this repository's README names the compiler and its version; do the same
# if you report one.
#
#   make CXX=g++-13        # Homebrew GCC
#   make CXX=clang++       # Apple clang / LLVM
#
# Both probes gate their exit code on their own correctness assertion, so
# `make check` failing is a real failure and not a formatting difference.
# Neither probe has any dependency beyond the C++17 standard library.

CXX      ?= g++-13
CXXFLAGS ?= -O3 -std=c++17 -DNDEBUG -Wall

BINS = hst_wavefront_exact_probe hst_dc_telemetry

all: $(BINS)

hst_wavefront_exact_probe: hst_wavefront_exact_probe.cpp include/assert_rel.hpp
	$(CXX) $(CXXFLAGS) -o $@ $<

hst_dc_telemetry: hst_dc_telemetry.cpp
	$(CXX) $(CXXFLAGS) -o $@ $<

# The frozen run (churn=0) is included deliberately: a harness whose "frozen"
# control is not actually frozen is the defect this one asserts against.
#
# The four negative cases are here for the same reason the positive ones are.
# `./hst_dc_telemetry banana -5` used to run, perform ZERO parity checks and
# exit 0 -- atof/atoi return 0 on garbage and cannot report that they did, so
# the loop body never executed and the exit code said everything was fine. A
# probe whose contract IS its exit code has to fail loudly on an argument it
# cannot honour, and that has to be asserted, not just implemented.
check: $(BINS)
	./hst_wavefront_exact_probe
	./hst_dc_telemetry 0.03 400
	./hst_dc_telemetry 0 400
	@for a in "banana -5" "5 400" "0.03 0" "0.03 400 2.5"; do \
	  if ./hst_dc_telemetry $$a >/dev/null 2>&1; then \
	    echo "FAIL: hst_dc_telemetry $$a exited 0; a run that checks nothing must not pass"; \
	    exit 1; \
	  fi; \
	done; echo "ok: invalid arguments are refused (churn/steps/locality)"
	@# The comparison primitives the verifier reports PASS from. They used
	@# zip(), so a zero-length or truncated vector scored a perfect match.
	python3 ../tools/selftest_altorder.py

clean:
	rm -f $(BINS)

.PHONY: all check clean
