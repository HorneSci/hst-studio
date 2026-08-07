# Errata — this download's own documentation

This file is about **this tree's README and scripts** — dated corrections to
things this download once said about itself. It is not about the paper:
corrections to the paper and its artifact live in
[`repro/paper-artifact/ERRATA.md`](repro/paper-artifact/ERRATA.md).

Each entry is the correction as it stood in the README, moved here verbatim
when the README was shortened. Nothing below is softened by living here: every
one of these was a thing we said that was not true, corrected under its date
rather than quietly.

## 2026-08-07 — the router section claimed measurement that never shipped

From *The router*:

> This section said the opposite until 2026-08-07 — that the build ran both arms and took
> the winner. That was never true of any build we have ever shipped. It is corrected here
> rather than quietly, because a reader who takes a routing claim at face value and then
> reads the behaviour has learned something worse about us than a threshold.

The section itself now describes what the build actually does — a structural
threshold, nothing timed, with `hst tune` as the advisory measurement.

## 2026-08-06 — three binding install rows named registries that 404

From *Calling the runtime from your language*:

> Until 2026-08-06 three of these rows read
> `go get` / `cargo add` / `dotnet add package`, naming coordinates that return 404, and
> `hstcore-rs`'s README linked a GitHub repository for `spdelta` while `spdelta` sat two
> directories away in the same tree.

Every install row now installs from this download, which is the only thing that
works until a registry coordinate exists.
