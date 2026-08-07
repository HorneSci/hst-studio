"""`python -m claimlint` -- statcheck for performance claims, in one command.

    python -m claimlint .                 report every incomplete document
    python -m claimlint . --ratchet       apply the three ratchet rules
    python -m claimlint . --stanza        print an allowlist to paste and annotate
    python -m claimlint . --show-config   what layered onto what, and from where
    python -m claimlint . --json          machine-readable, for CI

Zero configuration is a supported path: with no `.claimlint.toml` anywhere, the
builtin `default` profile runs and produces a real report. That is the point of
shipping a domain-free default -- the first run has to be worth reading, or
there is no second one.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from .api import run
from .config import ConfigError, load
from .ratchet import allowlist_stanza

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_USAGE = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="claimlint",
        description="Report performance claims whose conditions are not stated nearby.",
    )
    parser.add_argument("root", nargs="?", default=".", help="project root (default: .)")
    parser.add_argument("--config", help="path to a .claimlint.toml (default: <root>/.claimlint.toml)")
    parser.add_argument("--profile", help="builtin profile to start from (default / strict)")
    parser.add_argument("--overlay", help="private overlay TOML, layered last")
    parser.add_argument("--no-overlay", action="store_true", help="ignore any configured overlay")
    parser.add_argument("--ratchet", action="store_true", help="apply the three ratchet rules")
    parser.add_argument("--stanza", action="store_true", help="print an allowlist stanza and exit")
    parser.add_argument("--show-config", action="store_true", help="print the resolved configuration")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("-q", "--quiet", action="store_true", help="only print the summary line")
    parser.add_argument(
        "--allow-empty-corpus",
        action="store_true",
        help="permit a run over zero documents (default: that is an error)",
    )
    parser.add_argument(
        "--allow-unreadable",
        action="store_true",
        help="permit documents that could not be read (default: that is an error)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    # A pathspec that does not exist used to produce "0 documents ... exit 0":
    # green on a typo, which is `corpus vacuity` -- the exact risk the floors
    # section of this tool's own README names. Checked before the config load so
    # the message points at the path rather than at a missing .claimlint.toml.
    if not os.path.isdir(args.root):
        what = "is not a directory" if os.path.exists(args.root) else "does not exist"
        print(
            f"claimlint: {args.root!r} {what}, so the corpus is empty and every rule "
            f"below it would pass without reading anything.\n"
            f"  Fix: pass a project root that exists, or `cd` to it and run "
            f"`claimlint .`.",
            file=sys.stderr,
        )
        return EXIT_USAGE

    try:
        config = load(
            args.root,
            config_path=args.config,
            profile=args.profile,
            overlay=args.overlay,
            use_overlay=not args.no_overlay,
        )
    except ConfigError as exc:
        print(f"claimlint: {exc}", file=sys.stderr)
        return 2

    if args.show_config:
        print("configuration layers, later wins:")
        for source in config.sources:
            print(f"  {source}")
        print(f"private overlay applied: {config.overlay_applied or '(none)'}")
        print(f"window: {config.window}")
        print(f"required: {config.required}")
        print(f"ratio: {config.ratio}")
        print(f"corpus builder: {config.corpus}")
        print(f"floors: {config.floors or '(none enforced)'}")
        print(f"allowlist entries: {len(config.allowlist)}")
        return 0

    result = run(args.root, config=config, apply_ratchet=args.ratchet)

    # A corpus of zero is never a pass. This is deliberately NOT spelled as a
    # non-zero default `files` floor: the floors are calibrated per project from
    # a real run, and a default of 1 would be an arbitrary number pretending to
    # be a calibration, while a default of 10 would fail correct small corpora.
    # Zero is not a calibration question -- no include glob, no builder and no
    # tuning makes "read nothing, report clean" a meaningful answer -- so it is
    # a categorical error with its own opt-out, and the floors stay a tuning
    # knob the user sets from observed counts.
    if not len(result.corpus) and not args.allow_empty_corpus:
        print(
            f"claimlint: 0 documents matched under {args.root!r} "
            f"({result.corpus.builder}), so nothing was checked and 'clean' means "
            f"nothing.\n"
            f"  include = {config.include}\n"
            f"  exclude = {config.exclude}\n"
            f"  Fix: widen `claimlint.include` in .claimlint.toml, or set "
            f"`claimlint.corpus = \"walk\"` if the documents are untracked "
            f"(current: {config.corpus!r}).\n"
            f"  If an empty corpus is genuinely expected here, say so with "
            f"--allow-empty-corpus.",
            file=sys.stderr,
        )
        return EXIT_USAGE

    # Unreadable is the third state, and it belongs to the same family as the
    # empty corpus above: not "your documents broke a rule" (exit 1) but "this
    # run could not establish anything about them" (exit 2). A document that
    # could not be read was not checked, and a report that counts it as clean
    # is counting a document it never opened.
    #
    # This is checked BEFORE --stanza on purpose. A stanza generated from a
    # corpus that was only partly read is an allowlist missing entries, which
    # is the more expensive version of the same mistake: it looks complete.
    unreadable = result.unreadable
    if unreadable and not args.allow_unreadable:
        for report in sorted(unreadable, key=lambda r: r.path):
            print(f"claimlint: {report.path}: {report.error}", file=sys.stderr)
        print(
            f"  {len(unreadable)} of {len(result.corpus)} documents could not be read, so "
            f"they were not checked and 'clean' does not cover them.\n"
            f"  A UTF-16 file with a BOM is ordinary Windows output and a permission bit "
            f"is an ordinary checkout accident -- neither is a passing document.\n"
            f"  Fix: convert or exclude them (`claimlint.exclude` in .claimlint.toml), "
            f"or pass --allow-unreadable if a corpus you cannot fully read is genuinely "
            f"acceptable here.",
            file=sys.stderr,
        )
        return EXIT_USAGE

    if args.stanza:
        stanza = allowlist_stanza(result.reports)
        print(stanza or "# nothing incomplete -- no allowlist needed")
        return 0

    if args.json:
        print(json.dumps(_as_json(result), indent=2))
        return 0 if _passed(result, args) else 1

    if not args.quiet:
        for report in sorted(result.reports, key=lambda r: r.path):
            if report.error:
                print(f"{report.path}: {report.error}")
                continue
            if not report.gaps:
                continue
            # Under --ratchet the same wall of findings printed whether a
            # document was allowlisted or not; only a trailing ", ratchet ok"
            # on the summary said which. A reader could not tell a new
            # violation from an exempted one by looking, which is most of what
            # they came to the output for. Mark each document by its status,
            # and quote the exemption's own reason next to it -- an exemption a
            # reader can see is an exemption a reader can challenge.
            mark, note = _status(report, args.ratchet, config)
            print(f"{mark}{report.path}{note}")
            for element, claims in sorted(report.gaps.items()):
                where = ", ".join(f"{c.raw} (line {c.lineno})" for c in claims[:4])
                more = f" +{len(claims) - 4} more" if len(claims) > 4 else ""
                allowed = (
                    args.ratchet
                    and report.path in config.allowlist
                    and element in config.allowlist[report.path].missing
                )
                tag = "allowed" if allowed else "missing"
                print(f"  {tag} {element}: {where}{more}")

        if args.ratchet and result.ratchet is not None:
            for message in result.ratchet.messages():
                print()
                print(message)
        for failure in result.floor_failures:
            print(f"\nFLOOR {failure}")

    print(
        f"\n{len(result.corpus)} documents ({result.corpus.builder}), "
        f"{len(result.with_claims)} quoting ratios, "
        f"{len(result.incomplete)} missing at least one element"
        + (f", ratchet {'ok' if result.ratchet.ok else 'FAILED'}" if result.ratchet else "")
    )
    return 0 if _passed(result, args) else 1


def _passed(result, args) -> bool:
    """Exit status, honouring --allow-unreadable.

    `Result.ok` is deliberately strict: it is false whenever a document could
    not be read, because a library caller asserting on it should not have to
    know that a corpus silently shrank. The CLI flag is the one place that
    acceptance is expressed, so it is the one place `rules_ok` is consulted
    instead.
    """
    if args.allow_unreadable:
        return result.rules_ok
    return result.ok


def _status(report, ratchet: bool, config) -> tuple[str, str]:
    """The per-document prefix and suffix: NEW, WIDENED, or an exemption."""
    if not ratchet:
        return "", ""
    entry = config.allowlist.get(report.path)
    if entry is None:
        return "NEW       ", "   (not allowlisted -- this fails the ratchet)"
    if report.missing - entry.missing:
        widened = sorted(report.missing - entry.missing)
        return "WIDENED   ", f"   (allowlisted, but newly missing {widened})"
    return "allowlisted ", f"   ({entry.reason})"


def _as_json(result) -> dict:
    return {
        "corpus": {"size": len(result.corpus), "builder": result.corpus.builder},
        "required": result.config.required,
        "window": result.config.window,
        "documents": [
            {
                "path": r.path,
                "error": r.error,
                "claims": len(r.claims),
                "missing": {k: [c.lineno for c in v] for k, v in sorted(r.gaps.items())},
            }
            for r in sorted(result.reports, key=lambda r: r.path)
            if r.claims or r.error
        ],
        "ratchet": None
        if result.ratchet is None
        else {
            "ok": result.ratchet.ok,
            "new_incomplete": {k: sorted(v) for k, v in result.ratchet.new_incomplete.items()},
            "widened": {k: sorted(v) for k, v in result.ratchet.widened.items()},
            "stale": result.ratchet.stale,
            "bad_reasons": result.ratchet.bad_reasons,
            "placeholder_reasons": result.ratchet.placeholder_reasons,
            "unreadable": result.ratchet.unreadable,
        },
        "floor_failures": result.floor_failures,
        "ok": result.ok,
    }


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
