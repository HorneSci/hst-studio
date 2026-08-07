# claimlint

**statcheck for performance claims.** Scan a corpus for ratio-shaped figures
and report which conditions are not stated near them.

```bash
python3 -m pip install -e ".[test]"     # from this directory; src/ layout, not on PyPI
python3 -m claimlint .
```

If you got this inside an HST Studio download, `./install.sh` at the top of that
tree has already installed it.

Install once, then zero configuration. No dependencies outside the standard
library. (Commands in this README use `python3` — see **Requirements** below
for why, and for the floor this package actually needs.)

Terms below used without a formal definition — **element**, **profile**,
**ratchet** — are in the shared [`../GLOSSARY.md`](../GLOSSARY.md), covering
this package and its four siblings (`spdelta`, `bindnum`, `hst-evidence`,
`magnitude-guard`). "Ratchet" in particular has three referents across two of
those siblings; the glossary is where that gets sorted out once instead of
five times.

---

## The precedent, and the difference

statcheck (Nuijten, Hartgerink, van Assen, Epskamp & Wicherts, *Behavior
Research Methods* 48, 2016) recomputes the p-values reported in psychology
papers from the test statistics printed beside them, and flags the ones that do
not follow. It is not a better statistics course. It is a mechanical check on
text that already exists, run across a corpus nobody is going to rewrite — and
it found inconsistencies in roughly half the papers it scanned.

claimlint is that shape of intervention, aimed at a different check. It does not
recompute anything, because a performance ratio is not derivable from the
sentence containing it. What it checks is whether the **conditions that make the
ratio mean something** are stated near it:

> what it was measured **against**, on what **hardware**, over how many **runs**,
> with which **toolchain**.

That is the weaker check. It is also the one that catches what actually goes
wrong. A ratio quoted without its baseline is not a wrong number — it is a
number the reader cannot evaluate, cannot reproduce, and will re-quote somewhere
the missing condition matters.

*(If you want the numbers themselves held to their data, that is the sibling
package, `bindnum`.)*

---

## Fifteen minutes

```bash
python3 -m pip install -e ".[test]"               # skip if you already installed it above

# 1. see it on the worked example
python3 -m claimlint examples/corpus              # 4 documents flagged, exit 1
python3 -m claimlint examples/corpus --ratchet    # allowlist applied, exit 0

# 2. run it on your own docs, zero config
python3 -m claimlint ~/my-project

# 3. it will be noisy. Generate the allowlist:
python3 -m claimlint ~/my-project --stanza >> ~/my-project/.claimlint.toml

# 4. replace every TODO with a real reason, then:
python3 -m claimlint ~/my-project --ratchet       # exit 0 — and now it ratchets
```

Step 4 is the work, and it is deliberately not automated. Writing "why is this
document exempt" is the point — and it is now **enforced**, not merely asked
for. `--ratchet` refuses any reason still carrying the generator's placeholder
(`TODO`, and `FIXME`/`TBD`/`XXX`/`WIP` alongside it), so steps 3 and 4 cannot be
run as one green command. Both sides read the same `STANZA_PLACEHOLDER`
constant, so the generator and the check that rejects it cannot drift apart.

---

## The ratchet is the product

Point a scanner at an inherited corpus and you get a wall of red. Nobody
retrofits fifty documents in an afternoon, so the check fails for months, and a
check that fails for months teaches people to ignore the suite. That is worse
than not having it: the suite is now noise, and the next real failure hides in
it.

So the current gaps are recorded, each with a reason, and three rules are
enforced instead:

1. **No new incomplete document.** The debt cannot grow.
2. **No allowlisted document may lose an element it currently has.**
3. **An allowlisted document that is now clean must LEAVE the list.**

Rule 3 is the one usually missing, and the one that matters. An allowlist nobody
prunes becomes a permanent exemption — and a permanent exemption is how a
retracted rule survives a full propagation pass: the place it lives is never
re-read, because a passing test says it need not be.

Every entry carries a reason, and the reason must begin `n/a —` (the element
genuinely does not apply to what this document measured) or `GAP —` (real debt,
not yet paid). The distinction is enforced, because a list where every line
reads "n/a" has stopped meaning anything and nobody outside can tell which it
is. The dash is not part of the contract, only the word is: `n/a -` (ASCII
hyphen) and `n/a —` (em dash) are both accepted, here and in the sibling
`magnitude-guard`, which enforces the same shape of allowlist entry under a
different vocabulary (`PUBLIC` / `SYNTHETIC` / `GAP` — see its README).

### Wiring it into pytest

Three tests, mirroring the three rules, plus the floor:

```python
import claimlint

RESULT = claimlint.run(".")

def test_no_new_incomplete_document():
    assert not RESULT.ratchet.new_incomplete, RESULT.ratchet.messages()

def test_no_allowlisted_document_lost_an_element():
    assert not RESULT.ratchet.widened, RESULT.ratchet.messages()

def test_fixed_documents_leave_the_allowlist():
    assert not RESULT.ratchet.stale, RESULT.ratchet.messages()

def test_the_scan_still_has_teeth():
    assert not RESULT.floor_failures, RESULT.floor_failures
```

---

## Three scanner decisions, each from a real failure

These are not stylistic. Each one is the difference between a scan that catches
something and a scan that reports zero because it never looked. All three ship
as **tested behaviour**, in `tests/test_scan.py`, rather than as something users
rediscover.

### 1. The ratio pattern matches bare integers

`\d+\.\d+\s*[x×]` is the obvious first draft and it is wrong. It never sees
`15x` or `21x` — and in practice the roundest figures are the most quoted, so a
decimal-only scan misses exactly the claims that travel furthest, while
reporting a clean corpus.

Matching bare integers needs two negative lookaheads:

```
\b\d+(?:\.\d+)?\s*[x×](?!\w)(?!\s*\d)
                        │      └── kills `60,000 × 60,000`, `3 × 60 s`
                        └───────── kills `0x3fffffff`, `1920x1080`, `2x2`
```

Both are load-bearing. Without the first, one line of ordinary prose produces
three false positives on hex constants and video resolutions — and a linter that
cries wolf on hex constants is a linter somebody switches off this afternoon.

### 2. Window, not file

An element must appear **near** the claim. File-wide matching passed a
repudiated benchmark block because a machine name appeared 130 lines away, at
the top of the document, describing a customer's own deployment.

The window is a character count either side of the match (default 1200), chosen
so a document that states its method once in a dedicated section still covers
numbers a few paragraphs away, while a term mentioned somewhere unrelated does
not count.

### 3. Code spans, link targets and fenced blocks are stripped first

A filename satisfies a prose requirement it was never meant to. A document that
had stopped naming its compiler anywhere in prose still passed a toolchain check
because a data file in a link target was called `discovery_gcc.csv`.

What a document *says* and what its files are *named* are different claims. Only
the first is being linted. Markdown, HTML and LaTeX each get their own stripping
pass, and stripping preserves offsets so reported line numbers stay real.

### And a fourth: the floors

If the corpus builder collapses or the ratio regex stops matching, all three
ratchet rules pass — vacuously. So three separate floors, because they collapse
for different reasons:

| floor | collapses when |
|---|---|
| `files` | the corpus builder returned less than it should (bad pathspec, missing `git`) |
| `claim_bearing_files` | the ratio pattern stopped matching |
| `clean_files` | an element regex broke — if *nothing* is clean, the patterns are wrong, not the corpus |

The floors are calibrated per project from a real run, so they default to `0`
— which means a zero-config user gets none of that protection. Two things are
therefore checked **before** the floors and independently of them, because
neither is a calibration question:

- **A root that does not exist is an error (exit 2), naming the path.** Green on
  a bad pathspec is the exact failure this section is about.
- **A corpus of zero documents is an error (exit 2)**, naming the `include`
  globs and the corpus builder that produced nothing. No tuning makes "read
  nothing, report clean" a meaningful answer. If an empty corpus is genuinely
  expected — a new repository, a docs tree not yet written — say so with
  `--allow-empty-corpus`.

### Reading `--ratchet` output

Every flagged document is marked by its ratchet status, because the findings
themselves look identical whether a document is exempt or not:

```
allowlisted MISSING_TWO.md   (GAP — a one-line note quoting 21x with nothing attached)
  allowed baseline: 21x (line 3)
NEW       DRAFT.md   (not allowlisted -- this fails the ratchet)
  missing baseline: 3.5x (line 3)
WIDENED   OLD.md   (allowlisted, but newly missing ['toolchain'])
```

`allowed` vs `missing` per element, and the exemption's own reason quoted next
to it — an exemption a reader can see is an exemption a reader can challenge.

### Unknown configuration keys are an error

Misspell `required` as `requird` and TOML is perfectly happy: the key is inert,
`required` silently falls back to the profile's, and an element check you
believed you had configured is not the one running. For a tool whose whole
thesis is that a check which stops checking is worse than no check, that is the
worst available silence — so any key claimlint would ignore fails the load
(exit 2) with a spelling suggestion.

---

## Configuration

Everything tunable is configuration. Nothing project-specific appears anywhere
in the library, and the shipped default profile is domain-free — a test asserts
it.

`.claimlint.toml` at your project root:

```toml
[claimlint]
profile = "default"           # or "strict"
window = 1200
required = ["baseline", "hardware", "sample_size", "toolchain"]
corpus = "auto"               # "auto" | "git" | "walk"
private_overlay = "private/.claimlint.private.toml"   # optional

[elements]
# add or replace one pattern; the rest come from the profile
hardware = "\\bx86\\b|\\barm64\\b|our-bench-box"

[allowlist."docs/OLD_FINDINGS.md"]
missing = ["toolchain"]
reason = "GAP — timing ratios with no compiler named"

[floors]
files = 20
claim_bearing_files = 12
clean_files = 1
```

See **`PUBLIC_PRIVATE.md`** for the public/private split and the overlay hook.

### A note on writing element regexes

Use `\s+`, never a literal space, in any multi-word alternative. Prose wraps,
and a pattern with a literal space silently stops matching whenever the phrase
straddles a line break. That is a false report — and a false report is how a
linter gets switched off.

---

## Command line

```
python3 -m claimlint [ROOT] [options]

  --ratchet        apply the three ratchet rules (exit 0 when they pass)
  --stanza         print an allowlist for the currently-incomplete documents
  --show-config    what layered onto what, and from where
  --json           machine-readable, for CI
  --profile NAME   builtin profile to start from (default / strict)
  --overlay PATH   private overlay TOML, layered last
  --no-overlay     ignore any configured overlay
  --allow-empty-corpus   permit a run over zero documents (default: an error)
  -q, --quiet      summary line only
```

| exit | meaning |
|---|---|
| 0 | clean, or the ratchet rules pass |
| 1 | findings: incomplete documents, a ratchet rule broken, or a floor failure |
| 2 | usage or configuration: no such root, an empty corpus, bad TOML, an unknown key |

Exit codes: `0` clean, `1` findings, `2` configuration error.

## On the tests

Every test in `tests/` has been mutation-tested: the guard it protects was
removed or weakened, the test was observed to fail, and the guard was restored.
The mutation is recorded in the test's own docstring so the next person can
repeat it rather than trust it. Two guards did not survive that process — a
redundant `if floor and ...` clause and a `no-ratios` assertion that could not
see a broadened pattern — and both were changed rather than papered over.

claimlint deliberately does not depend on `bindnum`, so it records those runs in
prose rather than with `@mutation_verified`. If you already have bindnum
installed, `pytest --mutation-todo` works here too.

## Requirements

Python 3.11+ (for `tomllib`, used to read `.claimlint.toml`). Standard library
only. `pytest` for the tests. Below 3.11, `import claimlint` raises
`ImportError` naming this requirement directly, rather than the bare
`ModuleNotFoundError: No module named 'tomllib'` that `tomllib`'s own import
line would otherwise surface.

Commands in this README use `python3` rather than bare `python` — on some
machines the two resolve to different interpreters or different major
versions. Every package in this estate (`bindnum`, `spdelta`, `hst-evidence`,
`magnitude-guard`) follows the same convention.

## Licence

Apache-2.0, the same as the rest of the tree this ships in. See `LICENSE`.
