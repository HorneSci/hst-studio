"""Configuration, and the public/private split.

Every tuning decision in claimlint is configuration, never a fork:

    element regexes      [elements]
    required elements    claimlint.required
    window size          claimlint.window
    ratio pattern        claimlint.ratio
    ratchet policy       claimlint.allowlist, claimlint.reason_prefixes
    coverage floors      [floors]

Nothing above appears as a literal in the library. The shipped profiles are
domain-free; a project's own vocabulary lives in its `.claimlint.toml`, and
anything a project does not want in a public repository lives in a **private
overlay** -- a second TOML file, layered last, whose path is given by
`claimlint.private_overlay` or the `CLAIMLINT_PRIVATE_OVERLAY` environment
variable.

The overlay is a documented hook, not a fork, so the public and private
configurations differ by *data* and share every line of code. A missing overlay
is not an error -- the public configuration must stand on its own, and a run
that silently required a file nobody outside the team has would be a fork
wearing a config file's clothes. `Config.overlay_applied` records whether one
was found, and `--show-config` prints it.

Layering order, later wins:

    builtin profile (+ whatever it `extends`)
      -> project .claimlint.toml
        -> private overlay

Merge rules: scalars replace; `required` replaces wholesale (a project that
wants fewer elements must be able to say so); `elements`, `allowlist` and
`floors` merge key by key, so an overlay can replace one regex without
restating the rest.
"""

from __future__ import annotations

import difflib
import os
import re
import tomllib
from dataclasses import dataclass, field
from typing import Any

from .scan import DEFAULT_RATIO

__all__ = ["Config", "ConfigError", "load", "load_data", "PROFILE_DIR"]

PROFILE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "profiles")
CONFIG_NAME = ".claimlint.toml"
OVERLAY_ENV = "CLAIMLINT_PRIVATE_OVERLAY"

# Every key this tool understands, by the table it lives in. An unknown key is
# an ERROR, not a warning, and the reason is the whole thesis of the ratchet: a
# check that stops checking is worse than no check. Type `requird` instead of
# `required` and TOML is perfectly happy -- the misspelled key is inert data and
# `required` silently falls back to the profile's, so an element check the
# author believed they had configured is not the one running. There is no
# reading of that which is safe to warn about and continue, because the run that
# follows is green and wrong. Adding a key here is a one-line change; being
# unable to trust a passing run is not.
KNOWN_TABLES = {"claimlint", "elements", "allowlist", "floors"}
KNOWN_CLAIMLINT_KEYS = {
    "extends", "profile", "private_overlay", "window", "ratio", "required",
    "include", "exclude", "corpus", "reason_prefixes",
}
KNOWN_FLOOR_KEYS = {"files", "claim_bearing_files", "clean_files"}
KNOWN_ALLOWLIST_KEYS = {"missing", "reason"}


def _did_you_mean(name: str, known: set[str]) -> str:
    close = difflib.get_close_matches(name, sorted(known), n=1, cutoff=0.6)
    return f" -- did you mean {close[0]!r}?" if close else ""


def _check_keys(where: str, got, known: set[str], problems: list[str]) -> None:
    if not isinstance(got, dict):
        return
    for name in got:
        if name not in known:
            problems.append(
                f"  {where}.{name}: not a key claimlint understands"
                f"{_did_you_mean(name, known)}"
            )


def check_unknown_keys(data: dict[str, Any]) -> None:
    """Reject any key claimlint would otherwise ignore. See KNOWN_TABLES."""
    problems: list[str] = []
    for name in data:
        if name not in KNOWN_TABLES:
            problems.append(
                f"  [{name}]: not a table claimlint understands"
                f"{_did_you_mean(name, KNOWN_TABLES)}"
            )
    _check_keys("claimlint", data.get("claimlint"), KNOWN_CLAIMLINT_KEYS, problems)
    _check_keys("floors", data.get("floors"), KNOWN_FLOOR_KEYS, problems)
    for path, entry in (data.get("allowlist") or {}).items():
        _check_keys(f'allowlist."{path}"', entry, KNOWN_ALLOWLIST_KEYS, problems)
    if problems:
        raise ConfigError(
            "configuration has keys claimlint does not understand:\n"
            + "\n".join(problems)
            + "\n  A key claimlint ignores is a check the author believes is "
            "configured and is not. Fix the spelling or delete the key."
        )


class ConfigError(Exception):
    """A configuration file is missing, malformed, or self-contradictory."""


@dataclass
class AllowEntry:
    """One ratchet exemption: which elements, and why."""

    missing: set[str]
    reason: str


@dataclass
class Config:
    root: str = "."
    window: int = 1200
    ratio: str = DEFAULT_RATIO
    required: list[str] = field(default_factory=list)
    elements: dict[str, str] = field(default_factory=dict)
    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    # "auto" prefers `git ls-files` and falls back to a walk; "walk" forces the
    # filesystem builder. Untracked-but-real corpora (a docs tree vendored into
    # a monorepo, an example directory) need "walk", and finding that out from a
    # floor failure rather than a silent zero is the whole reason floors exist.
    corpus: str = "auto"
    allowlist: dict[str, AllowEntry] = field(default_factory=dict)
    floors: dict[str, int] = field(default_factory=dict)
    reason_prefixes: tuple[str, ...] = ("n/a", "GAP")
    sources: list[str] = field(default_factory=list)
    overlay_applied: str = ""

    @property
    def compiled_elements(self) -> dict[str, re.Pattern[str]]:
        out = {}
        for name, pattern in self.elements.items():
            try:
                out[name] = re.compile(pattern, re.I)
            except re.error as exc:
                raise ConfigError(f"element {name!r} has an invalid regex: {exc}") from exc
        return out

    @property
    def compiled_ratio(self) -> re.Pattern[str]:
        try:
            return re.compile(self.ratio)
        except re.error as exc:
            raise ConfigError(f"claimlint.ratio is an invalid regex: {exc}") from exc

    def validate(self) -> None:
        unknown = [name for name in self.required if name not in self.elements]
        if unknown:
            raise ConfigError(
                f"required elements with no regex in [elements]: {unknown}. "
                f"Defined: {sorted(self.elements)}"
            )
        if not self.required:
            raise ConfigError(
                "claimlint.required is empty -- every document would pass and the run "
                "would report a clean corpus without checking anything."
            )
        if self.corpus not in ("auto", "git", "walk"):
            raise ConfigError(
                f"claimlint.corpus must be 'auto', 'git' or 'walk', got {self.corpus!r}"
            )
        self.compiled_elements  # raises on a bad pattern
        self.compiled_ratio


# --------------------------------------------------------------------------
# loading and layering
# --------------------------------------------------------------------------


def _read_toml(path: str) -> dict[str, Any]:
    try:
        with open(path, "rb") as handle:
            return tomllib.load(handle)
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path} is not valid TOML: {exc}") from exc


def _profile_path(name: str) -> str:
    path = os.path.join(PROFILE_DIR, f"{name}.toml")
    if not os.path.exists(path):
        available = sorted(
            os.path.splitext(f)[0] for f in os.listdir(PROFILE_DIR) if f.endswith(".toml")
        )
        raise ConfigError(f"no builtin profile named {name!r}; available: {available}")
    return path


def _merge(base: dict[str, Any], layer: dict[str, Any]) -> dict[str, Any]:
    """Scalars and lists replace; the three named tables merge key by key."""
    out = dict(base)
    for key, value in layer.items():
        if key in ("elements", "floors", "allowlist") and isinstance(value, dict):
            merged = dict(out.get(key, {}))
            merged.update(value)
            out[key] = merged
        elif key == "claimlint" and isinstance(value, dict):
            merged = dict(out.get(key, {}))
            merged.update(value)
            out[key] = merged
        else:
            out[key] = value
    return out


def _load_profile(name: str, seen: tuple[str, ...] = ()) -> dict[str, Any]:
    if name in seen:
        raise ConfigError(f"profile inheritance cycle: {' -> '.join(seen + (name,))}")
    data = _read_toml(_profile_path(name))
    parent = data.get("claimlint", {}).get("extends")
    if parent:
        data = _merge(_load_profile(parent, seen + (name,)), data)
    return data


def load_data(data: dict[str, Any], *, root: str = ".", sources: list[str] | None = None) -> Config:
    """Build a Config from already-merged TOML data."""
    check_unknown_keys(data)
    block = data.get("claimlint", {})
    allowlist = {}
    for path, entry in (data.get("allowlist") or {}).items():
        if not isinstance(entry, dict):
            raise ConfigError(f"allowlist entry for {path!r} must be a table")
        allowlist[path] = AllowEntry(
            missing=set(entry.get("missing", [])),
            reason=str(entry.get("reason", "")),
        )
    config = Config(
        root=root,
        window=int(block.get("window", 1200)),
        ratio=str(block.get("ratio", DEFAULT_RATIO)),
        required=list(block.get("required", [])),
        elements=dict(data.get("elements", {})),
        include=list(block.get("include", [])),
        corpus=str(block.get("corpus", "auto")),
        exclude=list(block.get("exclude", [])),
        allowlist=allowlist,
        floors={k: int(v) for k, v in (data.get("floors") or {}).items()},
        reason_prefixes=tuple(block.get("reason_prefixes", ("n/a", "GAP"))),
        sources=list(sources or []),
    )
    return config


def load(
    root: str = ".",
    *,
    config_path: str | None = None,
    profile: str | None = None,
    overlay: str | None = None,
    use_overlay: bool = True,
) -> Config:
    """Load the layered configuration for a project rooted at `root`.

    With no `.claimlint.toml` anywhere, the builtin `default` profile is used
    unchanged -- that is the zero-config path, and it is meant to produce a
    useful report on a corpus nobody has configured yet.
    """
    sources: list[str] = []

    project_path = config_path or os.path.join(root, CONFIG_NAME)
    project: dict[str, Any] = {}
    if os.path.exists(project_path):
        project = _read_toml(project_path)
        sources.append(project_path)

    base_name = profile or project.get("claimlint", {}).get("profile") or "default"
    data = _load_profile(base_name)
    sources.insert(0, f"<builtin profile: {base_name}>")
    data = _merge(data, project)

    overlay_used = ""
    if use_overlay:
        overlay_path = (
            overlay
            or os.environ.get(OVERLAY_ENV)
            or project.get("claimlint", {}).get("private_overlay")
        )
        if overlay_path:
            resolved = overlay_path if os.path.isabs(overlay_path) else os.path.join(root, overlay_path)
            if os.path.exists(resolved):
                data = _merge(data, _read_toml(resolved))
                sources.append(resolved)
                overlay_used = resolved
            elif overlay:
                # An overlay named explicitly on the command line must exist;
                # one named in config or the environment is optional, because
                # the public configuration has to stand on its own.
                raise ConfigError(f"private overlay {resolved} does not exist")

    config = load_data(data, root=root, sources=sources)
    config.overlay_applied = overlay_used
    config.validate()
    return config
