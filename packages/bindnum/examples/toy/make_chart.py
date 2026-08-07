"""Draw chart.svg from results.csv.

RESULTS.md says this script "reads results.csv directly -- it does not carry a
copy of the curve". That sentence is a claim about behaviour, so
test_press_numbers.py proves it structurally with assert_reads rather than by
checking the numbers, which would pass either way.

Compare with chart_hardcoded.py, the counterexample: same output, same correct
values, no read.
"""

from __future__ import annotations

import derive_press

BARS = [(part, derive_press.part_ratio(part)) for part in derive_press.parts()]


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
