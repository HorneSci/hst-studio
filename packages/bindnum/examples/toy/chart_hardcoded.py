"""The counterexample. Do not fix this file -- it is the specimen.

It draws the same chart, with the same numbers, and every one of those numbers
is *correct*. Its only file operation is `open("chart.svg", "w")`; the CSV is
named in a comment. A value-equality check over this script passes.

That is the whole point. If RESULTS.md claims the curve is read from the data,
the claim is false here and no amount of checking the values will say so.
test_press_numbers.py asserts that assert_reads catches it.
"""

from __future__ import annotations

# data source: results.csv  <- named, never opened
BARS = [
    ("bracket", 2.402),
    ("flange", 1.9042),
    ("gasket", 1.0192),
    ("spindle", 0.9793),
]


def svg(bars: list[tuple[str, float]]) -> str:
    width, row_height = 320, 24
    lines = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
             f'height="{row_height * len(bars) + 10}">']
    for i, (label, value) in enumerate(bars):
        lines.append(
            f'  <rect x="80" y="{i * row_height + 4}" width="{value * 90:.1f}" height="16"/>'
            f'<text x="0" y="{i * row_height + 17}">{label} {value:.2f}</text>'
        )
    lines.append("</svg>")
    return "\n".join(lines)


if __name__ == "__main__":
    with open("chart.svg", "w", encoding="utf-8") as handle:
        handle.write(svg(BARS))
