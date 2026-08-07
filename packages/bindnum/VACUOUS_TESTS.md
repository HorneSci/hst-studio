# Eight ways a test passes without checking anything

A failing test tells you something. A passing test tells you something only if
it *could* have failed. Most of the tests in this document were green for
months, in suites people trusted, while checking nothing at all.

They are not sloppy tests. Every one of them was written deliberately, by
someone who understood the thing being tested, and every one reads correctly
until you look at what it would take to break it. That is what makes the
category worth naming: you cannot spot these by reading for quality. You spot
them by asking one question of every assertion —

> **What edit to the system under test would turn this red?**

If the answer is "an edit to the test itself", or "nothing", you have found
one.

Each pattern below is drawn from a real instance, anonymized. Where the fix is
a `bindnum` or `pytest-teeth` helper, it is named; most of them are not, and
just need the question asked.

---

## 1. Excuse-too-broad

**Shape.** A test derives a *reason to skip* from the data, and the reason is
broader than the case it was written for. Everything it was supposed to catch
falls inside the excuse.

**Instance.** A cross-reference checker walked a documentation tree and
asserted that every `[text](path)` link resolved to a file that exists. Some
documents legitimately referenced siblings in a directory that had not been
created yet, so a skip rule was added: *if the target's directory contains no
files at all, the reference is to future work — skip it.*

The directory in question was empty. So every broken link pointing into it was
skipped — including four ordinary typos in filenames that were supposed to be
in a *different*, fully-populated directory, because a typo in the directory
component pointed them at the empty one too. The skip rule was derived from
emptiness, and a typo produces emptiness. The excuse swallowed exactly the
class of defect the test existed to find.

**Why it passed.** The skip was computed from the same property the failure
produces. A test whose exemption is *derived from the symptom* cannot
distinguish the exemption from the symptom.

**How to catch it.** Write the exemption as an explicit list of paths, never as
a predicate over the data. A list is inert: it cannot grow to cover a new
defect on its own, and somebody has to type a reason next to each entry.
Predicate-shaped exemptions grow silently.

**The assertion that would have failed.** Count the skips. If the number of
skipped references is not itself pinned, a skip rule that starts matching
everything looks identical to a clean corpus.

---

## 2. Substring collision

**Shape.** A guard checks for the presence or absence of a short string, and
that string is a substring of ordinary words that appear everywhere.

**Instance.** A documentation check asserted that a particular caveat had been
removed from a set of files: `assert "not" not in text.lower()` was the
tightened form of a rule about a specific negation. It cleared instantly on
every file — because `"not"` is a substring of `Note`, `Another`, `Cannot`,
`notation`, `notably`. The guard was reporting on the English language, not on
the caveat.

The same shape appears in the opposite direction: a denylist that must *find* a
token, written with word boundaries, when the token only ever occurs inside
longer identifiers. `\bfixed\b` never fires on `fixedWidth`. Two of eleven
tokens in one such list were dead for months, and the list's own self-test
passed because its canary happened to use the one token that did sit on a word
boundary.

**Why it passed.** Nobody re-read the guard after tightening it, and the
tightening moved from a phrase to a fragment.

**How to catch it.** Two rules. First, guards match phrases or anchored
patterns, never bare fragments — and when a fragment is genuinely what you
want, say so in a comment with the collisions you checked. Second, every
denylist ships a **canary per token**, not one canary for the list: plant a
string that must be caught, and assert it is caught, for each entry
separately. A single canary tests one token and reports on all of them.

---

## 3. Subsuming alternation

**Shape.** `assert X in text or Y in text`, where one of the two strings
contains the other. Only the weaker clause ever decides.

**Instance.** A test on a corrected figure read

```python
assert "0.197 µs/lane, measured at B=16" in text or "0.197 µs/lane" in text
```

The second clause is a substring of the first, so the disjunction is exactly
the second clause. The correction the test was written to protect — the
condition attached to the number — could be deleted and the test would still
pass. It had been written as "the full form, or at least the number", which
sounds like defence in depth and is in fact no defence at all.

**Why it passed.** Alternation reads as *more* thorough. It is not: a
disjunction is only as strong as its weakest branch, and a branch that is a
substring of another is strictly weaker.

**How to catch it.** A lint you can run on your own suite: for every
`A in t or B in t`, check whether either literal contains the other. It is a
five-line script and it finds them all. Then split the assertion in two, or
delete the weak branch.

---

## 4. Short-circuited OR (the same defect, wearing a helpful face)

**Shape.** `assert banner in text or header in text` across a corpus, where one
of the two is present in almost every file for unrelated reasons.

**Instance.** A check asserted every published page carried a provenance
header. Because two page templates spelled it differently, the assertion became
`assert BANNER in text or HEADER in text`. Six of seven pages included the
banner as part of an unrelated shared layout, so their headers were never
checked at all. The seventh — the only page whose template lacked the banner —
was the only page the test ever actually examined.

The distinguishing symptom: the test passes on files where the thing is
missing, and the pass rate is a property of the *layout*, not the content.

**Why it passed.** The two branches were not two spellings of one requirement.
One of them was an unrelated string that happened to be common.

**How to catch it.** Parametrize over the corpus so each file is its own test
id, then assert *which* branch matched and count them. If one branch accounts
for every pass, the other branch has never run. `pytest-teeth`'s coverage floor
is the coarse version; counting branch hits is the sharp one.

---

## 5. Assertion-against-a-transcription

**Shape.** The test's expected values are a copy of the document's values. The
test can detect edits to itself, and nothing else.

**Instance.** A numbers suite asserted that a published table matched an
`EXPECTED` dict at the top of the test file. The dict had been produced by
copying the table. Both were wrong in the same way — the table had been written
from a partial data file — and the suite was green throughout. When the data
was later regenerated correctly, the suite went **red**, and the first instinct
was to update the expected values to match the old table again.

**Why it passed.** There is only one source of truth in the loop, and it is the
document. A test comparing a document to a copy of itself is a checksum on the
transcription, not on the claim.

**How to catch it.** The split this whole package is built around:

```
derive_<topic>.py   committed data -> value.  NO expected values in this file.
test_<topic>.py     asserts the DOCUMENT's stated value equals the derived one.
```

Two independent failure directions fall out of it: prose moves, or data moves,
and either one fails. `bindnum.binds` enforces the shape — the derivation never
sees the expected value, and the expected value is read out of the document at
check time rather than transcribed.

The tell, if you are auditing an existing suite: search for a literal in a test
file that also appears verbatim in a document. If nobody can say which one was
written first, it is a transcription.

---

## 6. Guard-on-an-artifact-CI-lacks

**Shape.** A test is wrapped in a skip that depends on something present on the
author's machine and absent in CI. It runs once, locally, and never again.

**Instance.** A module of twelve assertions began

```python
pytest.importorskip("torch")
```

and the data directory it read was gitignored. On the machine where the
benchmark ran, all twelve executed. In CI, the module collected, skipped, and
reported green. It stayed that way through a refactor that broke four of the
twelve. Nobody noticed, because a skipped test and a passing test are the same
colour in a summary line.

The variant that hides better: `if not os.path.exists(DATA): pytest.skip(...)`.
That reads as defensive and is indistinguishable from a permanent skip.

**Why it passed.** Skips are not failures, and a summary line reports `12
skipped` in the same green as `12 passed`.

**How to catch it.** Two moves. First, `--strict-markers` plus an explicit
allowlist of skip reasons — an unlisted skip reason fails the run. Second, and
more useful: assert the *count* of executed tests in CI, or make the skip
condition itself an assertion in one place (`test_the_data_is_present`) so its
absence is one loud failure rather than twelve quiet skips.

---

## 7. Corpus vacuity

**Shape.** Every assertion in a module iterates a corpus. The corpus builder
returns nothing. Every assertion passes.

**Instance.** A module scanned tracked documents via
`subprocess.run(["git", "ls-files", "<pathspec>"])`. The pathspec was changed
during a rename, matched nothing, and returned an empty list. All eleven tests
in the module passed, in under a millisecond, having opened zero files. The
module stayed green for three weeks.

Its cousins, all with the same symptom: a `glob` written against the old
directory layout; a `git` binary absent from a slimmed-down CI image, so the
subprocess failed and the empty stdout was used as data; an `include` pattern
that stopped matching after a file extension changed.

**Why it passed.** `for x in []: assert ...` is a passing test. There is no
Python construct that objects to it.

**How to catch it.** End every corpus-iterating module in a floor:

```python
from bindnum.teeth import assert_corpus_floor

def test_the_corpus_is_not_empty():
    assert_corpus_floor(documents(), 20,
                        what="tracked findings documents",
                        built_by="git ls-files '*FINDINGS*.md'",
                        was="25 on 2026-08-04")
```

Set the floor a little below the current count: high enough that a collapse
fails, low enough that deleting one stale document does not. And check the
*subset* floors separately — a corpus of the right size whose ratio regex stops
matching is a different collapse with the same green.

---

## 8. Unreadable-is-not-clean

**Shape.** The corpus loop swallows an error and continues. The document
silently disappears from every assertion below.

**Instance.** A scanner over a mixed corpus read each file inside

```python
try:
    text = open(path).read()
except OSError:
    continue
```

Three files were symlinks into a directory that had moved. They vanished from
every check in the module. The report said the corpus was clean; what it meant
was that it had read fewer documents than it listed, and could not tell you
which. The same shape with `UnicodeDecodeError` is more common still — one
Latin-1 byte in a document is enough to drop it from the run.

**Why it passed.** `continue` is not an error. The count of documents *listed*
and the count *examined* were never compared.

**How to catch it.** Never `continue` past a read failure. Record it as a
distinct outcome — not clean, not failing, *unreadable* — and fail the run on
it. `claimlint`'s `FileReport.error` is that third state, and its `clean`
property is deliberately false when `error` is set, so an unreadable document
can never be counted as a pass.

---

## 9. Expected-failure-without-a-reason

**Shape.** The test asserts that something *fails*. It does not assert **why**.
Any breakage at all then satisfies it — including breakage that has nothing to
do with the property under test, and including breakage introduced by the test
itself.

This is the mirror image of every pattern above. Those are checks that pass
when they should fail; this is a check that passes *because* something failed,
without ever establishing that the right thing failed. It is the harder one to
see, because the test's own name usually states the reason it never checks.

**Instance.** A Rust API encodes its central safety rule in the borrow checker:
holding a `&[f64]` view of internal state across a mutating call must not
compile. The rule was pinned with a rustdoc `compile_fail` doctest.

```rust
/// ```compile_fail,E0502
/// let view = ctx.state();
/// ctx.apply(&cols, &vals)?;   // must not compile: view is still borrowed
/// println!("{}", view[0]);
/// ```
```

Re-pinning the annotation from `E0382` to `E0499` — a *different, wrong* error
code — changed nothing; the test still passed. rustdoc does not enforce the
error code in `compile_fail,E0502`. Worse, misspelling a method name *inside*
the snippet also passes: the snippet fails to compile, which is all the test
ever asked. A doctest that was supposed to prove the borrow checker rejects
unsound code proves only that the code does not compile, and a typo achieves
that.

**Why it passed.** "Did it fail?" is a boolean with two ways to become true and
the test read only the boolean. Every mutation aimed at the *subject* was
caught; the mutations that survived were the ones aimed at the *test*.

**How to catch it.** Two things, and the second is the one everyone omits:

1. **Pin the reason.** Assert the specific error code, exception type or
   message — `pytest.raises(X, match=...)`, an explicit `rustc` invocation
   asserting `E0502`, a grep of the compiler output. Never a bare
   `pytest.raises(AssertionError)`, never `! cmd` in a shell test (command-not-
   found satisfies that too).
2. **Ship a control that must SUCCEED through the same harness.** If the
   harness itself is broken — wrong compiler flags, a bad path, a missing
   fixture — then *every* snippet "fails" and the whole file passes, proving
   nothing. The control is what distinguishes "the rule rejected this" from
   "nothing ran". Without it, pattern 9 fixes become pattern 7: a corpus that
   silently shrank to zero.

The same shape outside Rust: an expected-nonzero-exit test in a shell script
that does not check *which* exit code; a "this config must be rejected" test
that would also pass if the config file were missing; and — the one this
estate ships — a TLA+ runner whose fourth check expects a counterexample and
so is satisfied by a spec that fails to parse. That last one needed both fixes:
gate on the exit code being non-zero *and* grep the output for
`Invariant .* is violated`, so a parse error is no longer mistaken for the
lost-update trace the check exists to exhibit.

---

# The two standing rules

Everything above is a symptom. These two are the practice that catches the ones
not yet catalogued.

## Rule 1 — mutation-test every assertion before you commit it

Break the thing on purpose. Watch the test fail, and read the failure message
while you are there. Put it back. Watch it pass.

That is the whole method, and it is not optional: **an assertion nobody has
ever seen fail is a hypothesis.** Every one of the eight patterns above would
have been caught in about ninety seconds by one mutation run at the moment it
was written. None of them were, because the tests all passed the first time,
and a test that passes the first time feels finished.

Two practical notes:

- **Mutate the system, not the test.** Changing the expected value proves the
  comparison runs; it does not prove the comparison is attached to anything
  real. Change the data, the document, or the code path.
- **Record what you did.** A mutation you performed and did not write down is a
  mutation the next person will repeat, or skip. Use the marker:

  ```python
  from bindnum.teeth import mutation_verified

  @mutation_verified("2026-08-04",
                     "deleted the two spindle rows from results.csv")
  def test_the_sweep_covers_every_part():
      ...
  ```

  Then `pytest --mutation-todo` lists every test without one, and
  `--mutation-todo-strict` fails the run. Start with the report, not the
  failure: a plugin that fails the suite on day one is a plugin removed on day
  one.

## Rule 2 — every module ends in a coverage floor

The corpus builder is the least-tested line in a test module and the one most
likely to return nothing. Patterns 7 and 8 are both failures of the same
missing assertion.

```python
def test_the_corpus_is_not_empty():          # always last in the file
    assert_corpus_floor(...)
```

Where a module has more than one way to shrink, floor each one separately. A
scanner over documents has at least three: how many documents were listed, how
many of those contained anything to check, and how many passed. They collapse
for different reasons — a bad pathspec, a broken match pattern, a broken
requirement pattern — and a single floor catches only the first.

---

## A checklist, for reviewing somebody else's suite

1. For each assertion: what edit turns this red? If the answer is "editing the
   test", it is pattern 5.
2. Does any `assert A or B` have one literal containing the other? Pattern 3.
3. Does any `or` branch account for every pass? Pattern 4.
4. Is any exemption computed from the data rather than listed? Pattern 1.
5. Does any guard match a fragment rather than a phrase? Pattern 2.
6. What does the CI summary say about *skips*, not just failures? Pattern 6.
7. Does the last test in the module pin the corpus size? Patterns 7 and 8.
8. For every test that expects a *failure*: does it check which failure, and is
   there a control that must succeed through the same harness? Pattern 9.
9. Which assertions carry a recorded mutation run? Run `--mutation-todo`.
