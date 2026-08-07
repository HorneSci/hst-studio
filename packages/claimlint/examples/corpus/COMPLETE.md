# Widget press bench

The press arm finishes 15x sooner than the fold baseline on the reference
host: a 16-core x86 workstation, 5 repeats per cell, built with clang 18 at
-O2. Spread across repeats is under 3%.

A second cell reads 1.42x against the same baseline on the same machine over
5 runs.
