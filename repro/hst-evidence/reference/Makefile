# Reference implementation build. Public domain (CC0 1.0).
#
# -ffp-contract=off is NOT optional for the f64 GRADE-A cases, and this is
# measured rather than assumed. Without it, Apple clang 17 on arm64 contracts
# `y[i] += a * x[j]` into a fused multiply-add, which rounds once instead of
# twice, and every f64 GRADE-A case fails at rel_l2 ~1e-16. The same source
# under Homebrew GCC 13.4 at -O2 happened not to contract and passed. Same
# code, same summation order, different last bits.
#
# The six integer-exact cases pass under BOTH compilers with and without the
# flag, because no addition in them ever rounds. That is the entire argument
# for why they are the strongest object in this set.
#
# Name your compiler when you report a result. `cc` and `gcc` on macOS are
# Apple clang.

CC      ?= clang
CFLAGS  ?= -O2 -std=c99 -Wall -ffp-contract=off
LDLIBS  ?= -lm

reference_spmv: reference_spmv.c
	$(CC) $(CFLAGS) -o $@ $< $(LDLIBS)

clean:
	rm -f reference_spmv

.PHONY: clean
