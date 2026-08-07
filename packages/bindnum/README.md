# bindnum

**Bind the numbers already in your prose to the data behind them, and fail when
they diverge.**

```bash
# not yet published to PyPI -- install from source (src/ layout)
python3 -m pip install -e ".[test]"      # from this directory
# or: PYTHONPATH=src, it is stdlib-only
```

If you got this inside an HST Studio download, `./install.sh` at the top of that
tree has already done it.

Terms below that this README uses without a formal definition — **arm**,
**cell**, **teeth** — are in the shared
[`../GLOSSARY.md`](../GLOSSARY.md), covering this package and its four
siblings (`spdelta`, `claimlint`, `hst-evidence`, `magnitude-guard`).

---

## The gap this fills

Every literate-programming tool solves the **generative** direction. knitr,
Quarto, showyourwork, myst-nb: you write a template, the build produces the
number, and prose and data cannot disagree because only one of them exists.

That is an excellent design for a document you are about to write. It is no
help at all for the document you already have — the findings file, the
whitepaper, the customer deck, the README with the benchmark table in it. To
adopt a generative tool you must rewrite the corpus, and nobody rewrites the
corpus.

bindnum solves the **assertive** direction. Your prose keeps its numbers, its
formatting, and its sentences. You bind each number to a derivation, and the
suite fails when the two stop agreeing — **in either direction**:

```
somebody edits a number in prose        ->  stated != derived  ->  fail
somebody regenerates the source data    ->  stated != derived  ->  fail
```

The second direction is the one generative tools cannot have, because they
regenerate rather than notice. It is also the one that catches the expensive
mistake: the data moved, the document did not, and everybody kept quoting the
old figure.

---

## Fifteen minutes to your first bound number

**Minutes 0–3 — see it work.** (Skip the clone/install if you already did it above.)

```bash
python3 -m pytest examples/toy -q          # 9 passed
```

Now break it, and watch it care. Do it on a copy, not the tracked files —
this repo's own rule is a clean working tree, and `git checkout` is the wrong
habit to build for a tutorial step whose whole point is editing a number by
hand. `sed -i ''` is also macOS-only (the empty `''` after `-i` is BSD sed's
"no backup suffix"; GNU sed reads that same empty string as the start of its
*script* argument and errors), so the copy is edited with `python3` instead —
one line that behaves identically everywhere:

```bash
# the prose direction
cp -R examples/toy /tmp/bindnum-toy-scratch && cd /tmp/bindnum-toy-scratch
python3 -c "import pathlib as p; f = p.Path('RESULTS.md'); f.write_text(f.read_text().replace('1.46×', '1.47×'))"
python3 -m pytest -q          # fails, naming RESULTS.md:16
cd - >/dev/null && rm -rf /tmp/bindnum-toy-scratch

# the data direction -- a fresh copy, so this mutation stands alone
cp -R examples/toy /tmp/bindnum-toy-scratch && cd /tmp/bindnum-toy-scratch
python3 -c "import pathlib as p; f = p.Path('results.csv'); f.write_text(f.read_text().replace('bracket,11,1,40.00', 'bracket,11,1,44.00'))"
python3 -m pytest -q          # 3 fail, not 1: the bound bracket ratio; the
                              # reduction check (bracket can no longer prove
                              # "median" is the declared method); and the
                              # hardcoded-chart specimen, whose literal 2.40
                              # happened to equal the ORIGINAL derived value
                              # and stops matching once the source data moves
                              # under it -- a coincidence worth noticing, not
                              # a fourth real defect
cd - >/dev/null && rm -rf /tmp/bindnum-toy-scratch   # nothing tracked was ever touched
```

**Minutes 3–8 — write the derivation module.** One file, `derive_<topic>.py`,
holding pure functions from your committed data to a value. **It must contain
no expected values.** That absence is the design: a derivation module carrying
its own expected values can only compare a document to a staler copy of itself
(see `VACUOUS_TESTS.md` #5).

```python
# derive_press.py
import csv, statistics

def read_rows(path="results.csv"):
    with open(path) as handle:
        return list(csv.DictReader(handle))

def part_ratio(part):
    values = [float(r["fold_ms"]) / float(r["press_ms"])
              for r in read_rows() if r["part"] == part]
    return statistics.median(values)
```

**Minutes 8–13 — bind it.** One file, `test_<topic>.py`. Point `Doc` at the
document, and each derivation at the *site* where its number is written —
section and label, never the magnitude.

```python
# test_press_numbers.py
import pytest
from bindnum import Doc, binds, bindings
import derive_press as derive

DOC = Doc("RESULTS.md")

@binds(DOC, section="Per-part table", label="| bracket |")
def bracket_ratio():
    return derive.part_ratio("bracket")

@pytest.mark.parametrize("binding", bindings(), ids=lambda b: b.name)
def test_bindings_hold(binding):
    binding.check()
```

There is no tolerance to choose. The default is *exact at the precision the
document states*: `2.40` asserts two decimal places, so `2.4020` agrees and
`2.41` does not. The writer already decided how precise the claim was; the
binding holds them to that.

**Minutes 13–15 — prove it can fail.** Edit the number in the document. Run the
suite. Watch it go red. Put it back.

That last step is not ceremony. Until you have seen an assertion fail, it is a
hypothesis — and roughly half the failure modes catalogued in
`VACUOUS_TESTS.md` are assertions that were never once observed to bite.

---

## The five surfaces

Each exists because of a distinct failure that an ordinary value check cannot
see.

### `Doc` + `@binds` — locate by label, never by magnitude

```python
DOC = Doc("RESULTS.md")

@binds(DOC, section="Headline", label="faster than the fold arm")
def headline():
    return derive.headline_ratio()
```

A binding that searched the document for the string `1.02` would still find it
after the document swapped which arm that number described. The site is
`(section, label)`; the number is whatever is written there. An ambiguous label
is an error, not a silent first match — a label matching two lines is a binding
that will quietly follow the wrong one the first time somebody adds a
paragraph.

### `@binds_pair` — the arm swap, not the typo

```python
@binds_pair(DOC,
            first=dict(section="near unity", label="gasket:"),
            second=dict(section="near unity", label="spindle:"),
            window=0.02)
def near_unity():
    return derive.gasket_ratio(), derive.spindle_ratio()
```

Three-significant-figure ratios near 1 collide constantly. `1.02×` and `0.98×`
are exactly the shape where matching on magnitude has nothing to say, and where
the real failure is not a typo but a **swap**: the right two numbers attached to
the wrong two labels, in the document or in the test that binds it.

So `check()` runs the swap itself and requires it to fail. If the
cross-assignment also passes, the binding proves nothing, and it raises
`NonDiscriminatingPair` rather than going green. `window` additionally requires
a visible separation between the two derived values.

### `assert_reads` — proof the derivation touched its data

```python
assert_reads(build_chart, ["results.csv"],
             why="RESULTS.md says the curve is read from results.csv")
```

This one is load-bearing and the reason is worth stating precisely.

A chart script's surrounding prose claimed the curve was "re-derived directly
from the CSVs". It was not. The script's only file operation was
`open("chart.svg", "w")`; the CSV paths appeared in a comment; the curve was a
list of hand-transcribed literals. **The literals were numerically correct.**
So every value-equality check over that script passed, and the claim in the
prose was false anyway — because what made it false was not the numbers but
that no read ever happened.

Provenance sentences ("computed from", "read directly from", "regenerated by")
are claims about *behaviour*. Only a structural check can see them. `bindnum`
patches `builtins.open` and `io.open`, records every path opened for reading,
and asserts the expected ones appear. Readers that open files in C — `numpy`,
some `pandas` engines, `sqlite3` — need `extra_patches`; the module docstring
says so rather than pretending otherwise.

Use it *with* a value check, not instead of one. The structural check proves the
read happened; the value check proves what was read is what was used. Neither
implies the other.

### `assert_unique_reduction` — does the declared method actually decide the table?

```python
assert_unique_reduction(
    {"bracket": "2.40", "flange": "1.90", "gasket": "1.02", "spindle": "0.98"},
    {name: (lambda part, r=name: derive.part_ratio(part, r))
     for name in derive.REDUCTIONS},
    declared="median")
```

Documents name a reduction. Analysis scripts often implement another. When both
are in circulation, "the number reproduces" is not a check — it is a coin flip
with a documented answer.

So run every plausible reduction against the whole published table and require
**exactly one** to reproduce it:

| outcome | meaning |
|---|---|
| **none** | the table and the data have diverged — a cell was hand-edited, or the source was regenerated and the table was not |
| **one** | the declared method is verified, and the table is evidence of it |
| **many** | the cells do not discriminate. The declared method is **unverifiable from this table**: swap it for another and no published number moves |
| **a rival raised** | uniqueness was never tested. See below — this one used to certify. |

The third outcome is the one nothing else reports, and it is a finding, not a
pass. A single-cell check collapses to "does 1.42 equal 1.42", which several
reductions will satisfy at two decimal places; only running the candidates
across every cell at once separates them. `assert_unique_reduction` refuses
one-cell tables and single-candidate sets outright, for that reason.

**The fourth row is a bug this package shipped with, fixed 2026-08-05.** A
candidate that *raised* — an import error, a typo'd column name, an empty
group — was scored as a candidate that lost. So when the rivals broke, the
honest reduction won by walkover and was returned as verified. Every argument
above is about ambiguity collapsing the verdict toward *many*, which is
reported loudly; the symmetric collapse toward *one* was reported as the
strongest pass this module can give, and one broken import was enough to
trigger it.

Now a rival that raised on cells it might have reproduced raises
`CandidateCouldNotRun`. A rival that raised on some cells but *mismatched* one
it did run was beaten on the merits and is not reported — without that
carve-out the guard cries wolf, and a guard that cries wolf gets switched off.
Pass `allow_candidate_errors=True` when a rival raising is itself the result
you mean, and say why at the call site.

### `assert_aggregation_unit` — count operators, not rows

```python
assert_aggregation_unit(rows, "part", 4, unit="part", source="results.csv")
```

A sweep that dies half way through leaves a **perfectly well-formed** file.
Every row is valid, the header is right, it parses and it plots. Nothing about
it says it is a prefix.

One findings document was published from 11 of an intended 21 units. Every
aggregate in it was roughly 2× optimistic, and nothing flagged it — the values
were correctly computed over the rows that were there. A row-count check would
not have helped either: the count was plausible, and nobody knew the right one.

What catches it is counting the *unit the reduction aggregates over*. Pin that
once, beside the derivation.

---

## `bindnum.teeth` — the two standing rules

Shipped inside bindnum as a pytest plugin, under the name **pytest-teeth**.

```python
from bindnum.teeth import assert_corpus_floor, mutation_verified

@mutation_verified("2026-08-04", "deleted the six spindle rows from results.csv")
def test_the_sweep_covers_every_part():
    ...

def test_the_registry_is_not_empty():        # always last in the module
    assert_corpus_floor(bindings(), 4, what="registered bindings")
```

```bash
pytest --mutation-todo          # list assertions with no recorded mutation run
pytest --mutation-todo-strict   # ...and exit non-zero
```

The report is not a failure by default. Mutation coverage is a discipline you
ratchet toward, and a plugin that fails the suite on day one gets removed on
day one.

---

## Reading order

- **`VACUOUS_TESTS.md`** — eight patterns of tests that pass without checking
  anything, each with a real anonymized instance, plus the two standing rules.
  Read it before writing the first binding; it is the reason most of bindnum's
  API refuses degenerate inputs instead of accepting them.
- **`examples/toy/`** — the worked example, ~90 lines, no dependencies. Includes
  `chart_hardcoded.py`, the specimen whose numbers are correct and whose
  provenance claim is false.
- **module docstrings** — each one leads with the failure it exists to catch.

## Public and private tuning

bindnum ships no domain defaults, so there is nothing to split: every knob is an
argument at the binding site, in your own repository.

| Decision | Where it lives |
|---|---|
| comparison tolerance | `places` / `abs_tol` / `rel_tol` on `@binds`, defaulting to the precision the document states |
| pair separation | `window` on `@binds_pair` |
| candidate reductions | the `candidates` mapping you pass, usually a `REDUCTIONS` dict in your derivation module |
| expected unit counts | the `expected` argument to `assert_aggregation_unit` |
| corpus floors | the `minimum` argument to `assert_corpus_floor` |

If some of those values are themselves sensitive, keep the bindings in a private
test module and import the derivations from the public one. The derivations are
pure functions over committed data and carry no expected values, which is what
makes that split work without forking anything.

(The sibling package, `claimlint`, *does* ship defaults, so it has a documented
private-overlay hook. See its `PUBLIC_PRIVATE.md`.)

## Sibling

**`claimlint`** is the other half: it scans a corpus for ratio-shaped claims and
reports which conditions are missing near each one. bindnum checks that the
numbers you state are *true*; claimlint checks that they are *interpretable*.
They share nothing but a philosophy and can be adopted separately.

## Requirements

Python 3.11+. Stdlib only. `pytest` is needed for the plugin and the tests, not
for the library. Commands in this README use `python3` rather than bare
`python` — on some machines the two resolve to different interpreters or
different major versions (pyenv shims, `python` unset entirely, etc.), and
`python3` is the one guaranteed to mean "Python 3" everywhere. Every package
in this estate (`spdelta`, `claimlint`, `hst-evidence`, `magnitude-guard`)
follows the same convention.

## Licence

Apache-2.0, the same as the rest of the tree this ships in. See `LICENSE`.
