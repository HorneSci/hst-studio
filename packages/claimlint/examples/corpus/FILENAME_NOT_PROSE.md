# A build tool named only by a filename

The result is 3.10x against the previous release. Raw output is in
[the log](results/discovery_gcc_18.csv), and the build script is
`run_with_clang.sh`.

Neither of those is the document *saying* what built it, so a build-tool
requirement must still report this file. It does name its host, a 16-core x86
node, and it ran 5 repeats.
