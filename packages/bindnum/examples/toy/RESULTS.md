# Press vs fold — bench results

A toy corpus for bindnum. Four parts, three seeds, two runs each: 24 rows in
`results.csv`. The "press" arm and the "fold" arm do the same job; the ratio
reported everywhere below is `fold_ms / press_ms`, so a value above 1 means the
press arm finished sooner.

Reduction: **median across the six runs within a part, then geometric mean
across parts.** Nothing else. Everything in this document is bound to
`derive_press.py` by `test_press_numbers.py`; if a number here stops matching
the CSV, the suite fails, and if the CSV is regenerated and this file is not,
the suite also fails.

## Headline

Across the four parts, the press arm is **1.46×** faster than the fold arm.

The envelope chart in `chart.svg` is drawn by `make_chart.py`, which reads
`results.csv` directly — it does not carry a copy of the curve.

## Per-part table

| part | ratio |
|---|---|
| bracket | 2.40× |
| flange | 1.90× |
| gasket | 1.02× |
| spindle | 0.98× |

Those four cells are what pin the reduction. A mean over runs would publish
2.48 / 1.94 / 1.04 / 0.99, and a geometric mean 2.47 / 1.94 / 1.03 / 0.99, so
the table discriminates between all three and the declared method is checkable
rather than merely stated.

## The two parts near unity

These are the interesting ones, and they are the ones easiest to get backwards.

- gasket: 1.02× — the press arm is barely ahead.
- spindle: 0.98× — the press arm is barely behind.

Two figures three significant figures apart in opposite directions from 1 are
exactly where a swap hides. Each is bound to its own label, and the pair
binding runs the swap itself and requires it to fail.

## Coverage

The sweep covers **4** parts. That count is asserted directly: a run that died
after two parts would leave a perfectly well-formed CSV, every aggregate above
would be computed correctly over what was there, and nothing but a unit count
would notice.
