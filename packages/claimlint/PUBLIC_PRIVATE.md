# The public/private split

**Rule: every tuning decision has a public variant and a private variant, and
the split is configuration, never a fork.**

A fork is what happens by default. Someone needs the internal vocabulary in the
element patterns, or a tighter window, or an allowlist that names documents that
do not exist publicly — so they copy the tool, edit it, and now there are two.
Six months later the two disagree about what a claim is, and the public one is
the one people trust because it is the one they can read.

So every knob lives in data, and the code is identical in both deployments.

## What is tunable, and where it lives

| Decision | Where |
|---|---|
| element regexes | `[elements]` |
| which elements are required | `claimlint.required` |
| window size | `claimlint.window` |
| the ratio pattern itself | `claimlint.ratio` |
| corpus builder | `claimlint.corpus`, `claimlint.include`, `claimlint.exclude` |
| ratchet policy | `[allowlist.*]`, `claimlint.reason_prefixes` |
| coverage floors | `[floors]` |

None of those appears as a literal in the library. `tests/test_config_and_cli.py`
asserts the shipped default profile is domain-free, and asserts the same regexes
still match plainly-written prose — so the first test cannot be satisfied by
emptying them.

## Layering

Later wins:

```
builtin profile  (src/claimlint/profiles/*.toml, and whatever it `extends`)
  -> project      .claimlint.toml
    -> private overlay
```

Merge rules:

- scalars and lists **replace** — including `required`, because a project that
  wants *fewer* elements must be able to say so;
- `[elements]`, `[floors]` and `[allowlist.*]` merge **key by key**, so an
  overlay can replace one regex or add one exemption without restating the rest.

## The overlay hook

Three ways to name it, checked in this order:

1. `--overlay PATH` on the command line
2. `CLAIMLINT_PRIVATE_OVERLAY` in the environment
3. `claimlint.private_overlay` in `.claimlint.toml`

**A missing overlay is not an error** for (2) and (3). This is the load-bearing
part of the design: the public configuration has to stand on its own. A run that
silently required a file nobody outside the team possesses would be a fork
wearing a config file's clothes — everyone outside would see a tool that cannot
run, and would fork it for real.

(1) is the exception: an overlay named explicitly on the command line must
exist, because there is no reading of `--overlay missing.toml` under which
silently ignoring it is what the caller meant.

`Config.overlay_applied` records which file was used, and `--show-config` prints
it, so "is this the tuned configuration?" is a question with an answer.

## What belongs in an overlay

- vocabulary that identifies internal systems, hosts, customers, or products
- allowlist entries for documents that are not in the public tree
- a tighter `required` set, or tighter floors, for a corpus you actively curate

## What does not

- anything that changes what a *claim* is. If the ratio pattern differs between
  the public and private configurations, the two deployments are measuring
  different things and their reports are not comparable. Change it in the
  profile, for everyone, or not at all.
- anything that makes the public configuration fail to run. Test both:

```bash
python -m claimlint . --ratchet                 # with the overlay
python -m claimlint . --ratchet --no-overlay    # exactly what an outsider sees
```

Both should pass. If only the first does, the public configuration is decorative.
