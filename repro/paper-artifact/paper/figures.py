#!/usr/bin/env python3
"""Generate every figure in the paper from the measured CSVs.

No number in any figure is typed by hand; each is read from the raw sweep
output in the parent directory. Run from anywhere:

    python figures.py [--outdir figs]

Emits PDF (for LaTeX) and SVG (for the HTML build) side by side.
"""
import argparse, csv, math, os, sys, textwrap
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, Rectangle, FancyBboxPatch, Circle
from matplotlib.lines import Line2D
from matplotlib.colors import TwoSlopeNorm, LinearSegmentedColormap

HERE = os.path.dirname(os.path.abspath(__file__))          # paper/
ROOT = os.path.dirname(HERE)                                 # paper-artifact/, where agg.py/vintage.py live
DATA = os.path.join(ROOT, "data")                            # the released CSVs
sys.path.insert(0, ROOT)
import vintage  # noqa: E402

# --- design tokens (palette validated: all six checks PASS, light surface) ---
COL_EXACT = "#0072B2"   # column-exact arm
COL_BLOCK = "#D55E00"   # block-scheduled arm
COL_ROUTER = "#009E73"  # measured router
COL_PRED = "#7B5AA6"    # learned predictor
COL_ALT = "#B08600"     # fifth slot
INK = "#1a1a1a"
INK2 = "#5c5c5c"
MUTED = "#8a8a8a"
GRID = "#dcdcdc"
SURF = "#ffffff"
PANEL = "#f4f3f0"

plt.rcParams.update({
    "figure.facecolor": SURF, "axes.facecolor": SURF,
    "savefig.facecolor": SURF, "savefig.bbox": "tight", "savefig.pad_inches": 0.02,
    "font.family": "sans-serif",
    "font.sans-serif": ["Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"],
    "font.size": 8, "axes.titlesize": 8.5, "axes.labelsize": 8,
    "xtick.labelsize": 7.2, "ytick.labelsize": 7.2, "legend.fontsize": 7.2,
    "axes.edgecolor": "#c8c8c8", "axes.linewidth": 0.6,
    "axes.labelcolor": INK, "text.color": INK,
    "xtick.color": INK2, "ytick.color": INK2,
    "xtick.major.width": 0.6, "ytick.major.width": 0.6,
    "xtick.major.size": 2.5, "ytick.major.size": 2.5,
    "grid.color": GRID, "grid.linewidth": 0.5,
    "legend.frameon": False, "lines.linewidth": 1.6,
    "pdf.fonttype": 42, "ps.fonttype": 42,
})


def tidy(ax, grid="y"):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    if grid:
        ax.set_axisbelow(True)
        ax.grid(axis=grid, linewidth=0.5, color=GRID)
        ax.grid(axis="x" if grid == "y" else "y", visible=False)


def placeholder(name, reason, outdir):
    """Write a visible 'withheld' panel where a figure cannot be built.

    paper.tex has 14 \\includegraphics calls; this script can produce 6 from
    the public export. The other 8 are withheld columns (7) or a missing
    optional dependency (1). Until 2026-08-05 the skip was reported honestly
    HERE and nowhere else, so tectonic hit `LaTeX Error: File 'fig_frozen' not
    found` and the whole build failed -- meaning `./build.sh`, the artifact's
    headline command, could never succeed for any recipient.

    Emitting a placeholder keeps paper.tex untouched (which figures the paper
    references is a content decision, not this script's call) and puts the gap
    where a reader actually sees it: in the PDF, on the page where the figure
    would have been, naming the reason. A missing figure that fails the build
    is invisible; a missing figure that silently vanishes is worse. This is
    the third option.
    """
    fig, ax = plt.subplots(figsize=(5.4, 2.4))
    ax.axis("off")
    ax.add_patch(plt.Rectangle((0, 0), 1, 1, transform=ax.transAxes,
                               fill=False, linestyle="--", linewidth=1.0,
                               edgecolor="#999999"))
    ax.text(0.5, 0.66, f"{name} — not reproducible from this release",
            ha="center", va="center", transform=ax.transAxes,
            fontsize=9, weight="bold")
    ax.text(0.5, 0.36, textwrap.fill(reason, 74), ha="center", va="center",
            transform=ax.transAxes, fontsize=6.2, color="#555555")
    for ext in ("pdf", "svg"):
        fig.savefig(os.path.join(outdir, f"{name}.{ext}"))
    plt.close(fig)


def save(fig, name, outdir):
    for ext in ("pdf", "svg"):
        fig.savefig(os.path.join(outdir, f"{name}.{ext}"))
    plt.close(fig)
    print(f"  {name}")


import agg  # noqa: E402
from agg import geomean  # noqa: E402  (was: no empty guard -> ZeroDivisionError)
import columns  # noqa: E402


# ---------------------------------------------------------------- data ------
import router_data as RD  # noqa: E402  (DATA is on sys.path above)

#: The two motion models, always side by side and never averaged into each
#: other. `cyclic` is absent by construction -- router_data refuses it.
MODELS = list(RD.MODELS)
MLAB = RD.MODEL_LABEL
RHOS = [0.0, 0.002, 0.01, 0.05, 0.25]


def load_router(model):
    """One motion model's cells, exclusion rule applied. See router_data."""
    return RD.load(model)


def med_by_seed(rows, f):
    """Median across seeds of f, per (matrix, rho).

    A single seed's ratio is not the operator's ratio -- CONTRIBUTION.md 4c
    measures a harness floor of up to +-12% per operator on cells where the
    answer cannot have changed. Five seeds, and the median of them, is the unit.
    """
    d = {}
    for r in rows:
        d.setdefault((r["matrix"], r["rho"]), []).append(f(r))
    return {k: float(np.median(v)) for k, v in d.items()}


def two_panel(w=6.6, h=2.3, sharey=True):
    fig, axes = plt.subplots(1, 2, figsize=(w, h), sharey=sharey)
    for ax, m in zip(axes, MODELS):
        ax.set_title(MLAB[m], fontsize=8, pad=4,
                     color=COL_BLOCK if m == "drift" else COL_ALT)
    return fig, axes


DOMAIN = {
    "TSOPF_RS_b39_c30": "power flow", "TSOPF_RS_b162_c3": "power flow",
    "TSOPF_RS_b300_c1": "power flow", "case9": "power flow",
    "bcspwr09": "power network", "bcspwr10": "power network",
    "scircuit": "circuit sim", "memplus": "circuit sim", "add32": "circuit sim",
    "circuit_3": "circuit sim", "rajat03": "circuit sim", "wang3": "device sim",
    "ct20stif": "structural FEM", "bcsstk18": "structural FEM",
    "bcsstk25": "structural FEM", "msc10848": "structural FEM",
    "nasa2910": "structural FEM", "s3rmt3m3": "shell FEM",
    "olafu": "structural FEM", "raefsky3": "fluid/structure", "epb2": "plate/beam",
}


def label(ax, x, y, t, color=None, size=6.4, weight="normal", ha="center",
          va="center", pad=0.22, z=6):
    """Text on an opaque plate, so an edge label can never collide with a line."""
    return ax.text(x, y, t, ha=ha, va=va, fontsize=size, color=color or INK,
                   fontweight=weight, zorder=z, linespacing=1.25,
                   bbox=dict(boxstyle="round,pad=%s" % pad, fc=SURF, ec="none"))


def leader(ax, xy, xytext, color):
    """A real leader line: terminates exactly on its target, no stray stub."""
    ax.annotate("", xy=xy, xytext=xytext,
                arrowprops=dict(arrowstyle="-", lw=.7, color=color,
                                shrinkA=0, shrinkB=0))


# =========================================================== schematics =====
def fig_task(outdir):
    fig, ax = plt.subplots(figsize=(6.6, 2.3))
    ax.set_xlim(0, 100); ax.set_ylim(-7, 47); ax.axis("off")
    Y0, H = 9, 26
    bands = [(13.5, 4.5), (23.0, 3.0)]

    def box(x0, w, cap, fc="#eceae6"):
        ax.add_patch(Rectangle((x0, Y0), w, H, fc=fc, ec="#b5b0a8", lw=.8))
        ax.text(x0 + w / 2, Y0 - 2.2, cap, ha="center", va="top", fontsize=7.3)

    box(4, 30, "$A$   fixed sparse operator, $N \\times M$")
    for bx, bw in bands:
        ax.add_patch(Rectangle((bx, Y0), bw, H, fc=COL_BLOCK, alpha=.32, ec="none"))
    lx, ly = 19, 42
    label(ax, lx, ly, "dirty columns $D$", color=COL_BLOCK, size=7, weight="bold")
    for bx, bw in bands:
        leader(ax, (bx + bw / 2, Y0 + H), (lx, ly - 2.0), COL_BLOCK)

    ax.text(37.5, Y0 + H / 2, r"$\times$", ha="center", va="center", fontsize=13)

    box(41, 7, "$dx$", fc="#f8f7f5")
    rows = [(Y0 + H * .60, 2.8), (Y0 + H * .26, 2.8)]
    for ry, rh in rows:
        ax.add_patch(Rectangle((41, ry), 7, rh, fc=COL_BLOCK, alpha=.55, ec="none"))
    label(ax, 52.5, 42.5, "one row per dirty column", color=INK2, size=6.4)
    for ry, rh in rows:
        leader(ax, (48.2, ry + rh / 2), (49.8, 40.8), COL_BLOCK)

    ax.text(52.2, Y0 + H / 2, "=", ha="center", va="center", fontsize=13)
    box(55.5, 7, "$dy$", fc="#f8f7f5")
    ax.add_patch(Rectangle((55.5, Y0), 7, H, fc=COL_EXACT, alpha=.20, ec="none"))
    ax.text(66.5, Y0 + H / 2, r"$\Rightarrow$", ha="center", va="center", fontsize=13)

    ax.add_patch(FancyBboxPatch((71, Y0 + 3), 26, H - 6,
                                boxstyle="round,pad=0.6,rounding_size=1.2",
                                fc=PANEL, ec="#cfcac2", lw=.8))
    ax.text(84, Y0 + H - 6.5, r"$y \leftarrow y + dy$", ha="center", fontsize=9.5)
    ax.text(84, Y0 + H - 12.5, "costs nnz$(A[:,D])$", ha="center", fontsize=7, color=INK2)
    ax.text(84, Y0 + H - 17.5, "not nnz$(A)$", ha="center", fontsize=7.4,
            color=COL_BLOCK, fontweight="bold")

    ax.text(4, -1.4, "Recomputing $A(x{+}dx)$ from scratch costs nnz$(A)$ every step. "
                     "The delta form pays only for the dirty\ncolumns — provided the "
                     "implementation can restrict to them without re-preparing itself "
                     "each time $D$ moves.",
            fontsize=7.1, color=INK2, va="top", linespacing=1.4)
    save(fig, "fig_task", outdir)


def fig_workload(outdir):
    """The two motion models, at each churn rate, on one fixed topology.

    Both models retire the same fraction of the dirty set per step and hold
    |D| constant; they differ only in where the replacements come from. That
    single difference is the variable the rest of the paper is organized
    around, so it gets a schematic rather than a sentence.
    """
    fig, axes = plt.subplots(2, len(RHOS), figsize=(6.6, 3.05))
    G = 12
    base = {(5, 6), (5, 7), (6, 6), (6, 7), (4, 6), (6, 8), (7, 7), (5, 5)}
    for row, model in enumerate(MODELS):
        rng = np.random.default_rng(4)
        for col, rho in enumerate(RHOS):
            ax = axes[row, col]
            s, target = set(base), len(base)
            for _ in range(14):  # advance a few steps at this churn rate
                k = min(max(0, int(round(rho * target * 4))), target - 1)
                if not k:
                    continue
                order = sorted(s)
                rng.shuffle(order)
                s -= set(order[:k])
                guard = 0
                while len(s) < target and guard < 500:
                    guard += 1
                    if model == "drift":
                        # refill from the structural neighbourhood of a survivor
                        cx, cy = sorted(s)[rng.integers(len(s))]
                        cand = [(cx + dx, cy + dy)
                                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                                if 0 <= cx + dx < G and 0 <= cy + dy < G
                                and (cx + dx, cy + dy) not in s]
                        if cand:
                            s.add(cand[rng.integers(len(cand))])
                    else:
                        # redraw uniformly from every live column
                        s.add((int(rng.integers(G)), int(rng.integers(G))))
            for i in range(G):
                for j in range(G):
                    on = (i, j) in s
                    ax.add_patch(Rectangle(
                        (i, j), .82, .82, ec="none",
                        fc=(COL_BLOCK if model == "drift" else COL_ALT) if on
                        else "#ececea"))
            ax.set_xlim(-.4, G + .2); ax.set_ylim(-.4, G + .2)
            ax.set_aspect("equal")
            # axis("off") hides the tick labels but leaves the artists, and the
            # layout gate reads artists, not visibility. Clear them outright.
            ax.set_xticks([]); ax.set_yticks([]); ax.axis("off")
            if row == 0:
                ax.set_title(r"$\rho=0$" "\nfrozen" if rho == 0
                             else rf"$\rho={rho:g}$", fontsize=7.0, pad=3)
        axes[row, 0].text(-.05, .5, MLAB[model], transform=axes[row, 0].transAxes,
                          rotation=90, ha="right", va="center", fontsize=7.4,
                          color=COL_BLOCK if model == "drift" else COL_ALT)
    fig.subplots_adjust(bottom=0.12, hspace=0.06, wspace=0.04)
    save(fig, "fig_workload", outdir)


def fig_frozen(outdir):
    """The frozen loss, and how much of it padding accounts for.

    Left: the ratio at three batch widths on the ten-configuration ladder.
    Right: the per-operator version of the padding argument on the 21-operator
    sweep. Padding is the mechanism and it is not the whole gap -- the residual
    is the vertical distance from the diagonal, and it is what the prose has to
    report beside the correlation.
    """
    rows = list(csv.DictReader(open(os.path.join(DATA, "baseline_best.csv"))))
    fig, axes = plt.subplots(1, 2, figsize=(6.6, 2.3))
    ax = axes[0]
    Bs = ["1", "8", "16"]
    cfgs = sorted({(r["matrix"], r["ordering"]) for r in rows})
    x = np.arange(len(Bs))
    for m, o in cfgs:
        v = [float(next(r for r in rows if r["matrix"] == m and r["ordering"] == o
                        and r["B"] == b)["hst_vs_delta_baseline_best"]) for b in Bs]
        ax.plot(x, v, marker="o", ms=2.8, lw=.9, color=MUTED, alpha=.7, zorder=2)
    g = [geomean([float(r["hst_vs_delta_baseline_best"]) for r in rows if r["B"] == b]) for b in Bs]
    ax.plot(x, g, marker="o", ms=5.5, lw=2.4, color=COL_BLOCK, zorder=4)
    for xi, v in zip(x, g):
        label(ax, xi, v + 0.08, f"{v:.2f}", color=COL_BLOCK, size=7, weight="bold")
    ax.axhline(1.0, color=COL_EXACT, lw=1.2, zorder=3)
    ax.text(2.02, 1.0, "parity", fontsize=6.4, color=COL_EXACT, va="center")
    ax.set_xticks(x); ax.set_xticklabels([f"B={b}" for b in Bs])
    ax.set_ylabel("block-sched. ÷ column-exact")
    ax.set_xlim(-.35, 2.45); ax.set_ylim(0, 1.40)
    ax.set_title(f"{len(cfgs)} configurations, B ladder", fontsize=7.6, pad=4)
    tidy(ax)

    ax = axes[1]
    for model, col, mk in (("drift", COL_BLOCK, "o"), ("jump", COL_ALT, "^")):
        froz = RD.split(load_router(model))[0]
        per = {}
        for r in froz:
            per.setdefault(r["matrix"], []).append((r["hst"] / r["csr"], 1 / r["dens"]))
        pad = [float(np.median([b for _, b in v])) for v in per.values()]
        slow = [float(np.median([a for a, _ in v])) for v in per.values()]
        r_ = float(np.corrcoef(pad, slow)[0, 1])
        ax.scatter(pad, slow, s=13, color=col, marker=mk, lw=0, alpha=.8,
                   label=f"{MLAB[model]}  r={r_:+.2f}")
        if model == "drift":
            worst = max(range(len(pad)), key=lambda i: slow[i] / pad[i])
            names = list(per)
            label(ax, pad[worst] + .55, slow[worst] + .28, names[worst],
                  size=5.8, color=INK2)
    lim = 6.2
    ax.plot([1, lim], [1, lim], color=INK, lw=1.0, ls=(0, (4, 2)), zorder=1)
    label(ax, 4.3, 3.35, "padding alone", size=6.2, color=INK)
    ax.set_xlabel("entries scanned ÷ entries needed", labelpad=2)
    ax.set_ylabel("frozen slowdown")
    ax.set_xlim(.8, lim); ax.set_ylim(.8, lim)
    ax.set_title("21 operators, frozen, B=8", fontsize=7.6, pad=4)
    ax.legend(loc="upper left", fontsize=6.2, handletextpad=.3)
    tidy(ax, grid="both")
    save(fig, "fig_frozen", outdir)


def fig_churn_response(outdir):
    fig, axes = two_panel(6.6, 2.35)
    for ax, model in zip(axes, MODELS):
        R = load_router(model)
        best = med_by_seed(R, lambda r: r["oracle_vs_csr"])
        mats = sorted({r["matrix"] for r in R})
        for m in mats:
            v = [best[(m, p)] for p in RHOS]
            hi = v[-1] > 3
            ax.plot(range(len(RHOS)), v, marker="o", ms=2.4, lw=.85,
                    color=COL_BLOCK if hi else MUTED,
                    alpha=.75 if hi else .55, zorder=2 if hi else 1)
        for m in ("TSOPF_RS_b39_c30", "scircuit"):
            v = [best[(m, p)] for p in RHOS]
            label(ax, len(RHOS) - 1.12, v[-1], m, size=5.8, ha="right",
                  color=COL_BLOCK if v[-1] > 3 else INK2)
        ax.axhline(1.0, color=COL_EXACT, lw=1.1)
        ax.set_yscale("log")
        ax.set_yticks([1, 2, 5, 10, 20, 35])
        ax.set_yticklabels(["1×", "2×", "5×", "10×", "20×", "35×"])
        ax.set_xticks(range(len(RHOS)))
        ax.set_xticklabels([f"{p:g}" for p in RHOS], fontsize=6.4)
        ax.set_xlabel(r"churn rate $\rho$", labelpad=2)
        ax.set_xlim(-.2, len(RHOS) - .75)
        tidy(ax)
    axes[0].set_ylabel("best arm ÷ column-exact")
    save(fig, "fig_churn_response", outdir)


def fig_heatmap(outdir):
    fig, axes = plt.subplots(1, 2, figsize=(6.6, 3.9), sharey=True)
    # order operators by their strongest local-drift cell, and hold that order
    # in both panels so a row is the same operator on both sides
    Rd = load_router("drift")
    bd = med_by_seed(Rd, lambda r: r["oracle_vs_csr"])
    mats = sorted({r["matrix"] for r in Rd},
                  key=lambda m: -max(bd[(m, p)] for p in RHOS))
    cmap = LinearSegmentedColormap.from_list(
        "arm", [COL_BLOCK, "#f2efe9", COL_EXACT])  # low=block faster, high=col-exact faster
    panels = []
    for model in MODELS:
        R = load_router(model)
        ratio = med_by_seed(R, lambda r: r["hst"] / r["csr"])
        panels.append(np.array([[ratio[(m, p)] for p in RHOS] for m in mats]))
    lim = max(np.abs(np.log10(M)).max() for M in panels)
    for ax, model, M in zip(axes, MODELS, panels):
        L = np.log10(M)
        ax.imshow(L, cmap=cmap, norm=TwoSlopeNorm(vcenter=0, vmin=-lim, vmax=lim),
                  aspect="auto")
        for i in range(len(mats)):
            for j in range(len(RHOS)):
                v = 1 / M[i, j]
                t = (f"{v:.0f}×" if v >= 9.5 else
                     (f"{v:.1f}×" if (v >= 1.05 or v <= 0.95) else "·"))
                ax.text(j, i, t, ha="center", va="center", fontsize=5.4,
                        color="white" if abs(L[i, j]) > lim * .55 else INK)
        ax.set_xticks(range(len(RHOS)))
        ax.set_xticklabels([f"{p:g}" for p in RHOS], fontsize=6.2)
        ax.set_xlabel(r"churn rate $\rho$", labelpad=2)
        ax.set_title(MLAB[model], fontsize=8, pad=4,
                     color=COL_BLOCK if model == "drift" else COL_ALT)
        for s in ax.spines.values():
            s.set_visible(False)
        ax.tick_params(length=0)
    axes[0].set_yticks(range(len(mats)))
    axes[0].set_yticklabels(list(mats), fontsize=6.0)
    h = [Line2D([], [], marker="s", ls="", ms=6, color=COL_BLOCK, label="block-scheduled faster"),
         Line2D([], [], marker="s", ls="", ms=6, color=COL_EXACT, label="column-exact faster")]
    fig.legend(handles=h, loc="lower center", bbox_to_anchor=(.55, -.055), ncol=2,
               handletextpad=.5, fontsize=6.4, frameon=False)
    save(fig, "fig_heatmap", outdir)


def fig_overlap(outdir):
    """Is the arm separable from operator structure alone, once the set moves?

    Under local drift the question dissolves: the column-exact class is empty at
    every churn rate measured, on every operator. Under uniform jump both
    classes exist and dens does not separate them.
    """
    fig, axes = plt.subplots(1, 2, figsize=(6.6, 1.85), sharey=True)
    rng = np.random.default_rng(1)
    for ax, model in zip(axes, MODELS):
        R = [r for r in load_router(model) if r["rho"] > 0]
        hi = [r["dens"] for r in R if r["arm"] == "hst"]
        lo = [r["dens"] for r in R if r["arm"] == "csr"]
        ax.scatter(hi, .72 + rng.normal(0, .045, len(hi)), s=8, color=COL_BLOCK,
                   alpha=.55, lw=0, label=f"block-scheduled better  (n={len(hi)})")
        if lo:
            ax.scatter(lo, .28 + rng.normal(0, .045, len(lo)), s=8, color=COL_EXACT,
                       alpha=.55, lw=0, label=f"column-exact better  (n={len(lo)})")
            a, b = max(min(hi), min(lo)), min(max(hi), max(lo))
            ax.axvspan(a, b, color="#c9302c", alpha=.075, lw=0, zorder=0)
            inside = sum(1 for v in hi + lo if a <= v <= b)
            label(ax, (a + b) / 2, 1.16,
                  f"overlap {a:.2f}–{b:.2f}: {inside}/{len(R)} cells", color="#a8332f",
                  size=6.2)
        else:
            ax.scatter([], [], s=8, color=COL_EXACT, lw=0,
                       label="column-exact better  (n=0)")
            label(ax, .58, 1.16, f"the column-exact class is empty: "
                                 f"{len(hi)}/{len(R)} cells", color=COL_BLOCK, size=6.2)
            label(ax, .58, .28, "nothing to separate", color=MUTED, size=6.2)
        ax.set_xlabel(r"tile density $\mathrm{dens}$", labelpad=2)
        ax.set_title(MLAB[model], fontsize=8, pad=4,
                     color=COL_BLOCK if model == "drift" else COL_ALT)
        ax.set_yticks([]); ax.set_ylim(0, 1.34); ax.set_xlim(.08, 1.08)
        ax.set_xticks([.2, .4, .6, .8, 1.0])
        ax.legend(loc="lower center", bbox_to_anchor=(.5, -.86), ncol=1, fontsize=6.2)
        for s in ("top", "right", "left"):
            ax.spines[s].set_visible(False)
    save(fig, "fig_overlap", outdir)


def fig_asymmetry(outdir):
    """Churning cells only.

    An earlier version pooled frozen and churning cells into one histogram,
    which breaks the paper's own aggregation rule and puts the frozen
    block-scheduled penalty (5.85x/5.87x) inside a distribution the caption
    describes as churning. The frozen numbers are reported in the prose.
    """
    fig, axes = two_panel(6.6, 1.95, sharey=False)
    bins = np.logspace(0, np.log10(40), 24)
    for ax, model in zip(axes, MODELS):
        R = RD.split(load_router(model))[1]
        a = [r["pen_csr"] for r in R if r["arm"] == "hst"]   # chose column-exact, wrong
        b = [r["pen_hst"] for r in R if r["arm"] == "csr"]   # chose block-sched, wrong
        ax.hist(a, bins=bins, color=COL_EXACT, alpha=.85,
                label=f"chose column-exact\nwhen block was right (n={len(a)})")
        if b:
            ax.hist(b, bins=bins, color=COL_BLOCK, alpha=.85,
                    label=f"chose block-sched.\nwhen column was right (n={len(b)})")
        else:
            ax.plot([], [], color=COL_BLOCK, lw=4,
                    label="chose block-sched.\nwhen column was right (n=0)")
        ax.set_xscale("log")
        top = ax.get_ylim()[1]
        ax.axvline(max(a), color=COL_EXACT, lw=1, ls=(0, (3, 2)))
        label(ax, max(a) * .92, top * .95, f"{max(a):.0f}×", ha="right",
              size=6.8, color=COL_EXACT, weight="bold")
        if b:
            ax.axvline(max(b), color=COL_BLOCK, lw=1, ls=(0, (3, 2)))
            label(ax, max(b) * 1.10, top * .95, f"{max(b):.1f}×", ha="left",
                  size=6.8, color=COL_BLOCK, weight="bold")
        else:
            label(ax, 6.0, top * .55, "no churning cell where\nthe block arm is "
                                      "the wrong choice", size=6.0, color=COL_BLOCK)
        ax.set_xticks([1, 2, 5, 10, 20, 40])
        ax.set_xticklabels(["1×", "2×", "5×", "10×", "20×", "40×"], fontsize=6.4)
        ax.set_xlabel("slowdown paid for choosing wrong", labelpad=2)
        tidy(ax)
    axes[0].set_ylabel("cells")
    axes[0].legend(loc="upper center", fontsize=6.0, bbox_to_anchor=(.5, -.36))
    axes[1].legend(loc="upper center", fontsize=6.0, bbox_to_anchor=(.5, -.36))
    save(fig, "fig_asymmetry", outdir)


def _pred_table(model=None, scope=None):
    rows = list(csv.DictReader(open(os.path.join(DATA, "predictor_study.csv"))))
    if model:
        rows = [r for r in rows if r["churn_model"] == model]
    if scope:
        rows = [r for r in rows if r["scope"] == scope]
    return rows


#: the scope the paper's selection argument lives in. Named a mixture on
#: purpose: frozen and churning cells are never averaged into one another
#: without saying so.
MIX = "workload mix (frozen + churning)"
CHURNING = "churning only"


#: the three files that carry `sched_rows` for all three emission strategies
P4_FROZEN = "p4_frozen.csv"
P4_CHURN = {"drift": "p4_churn_drift_pooled.csv", "jump": "p4_churn_jump_pooled.csv"}


#: the 21-operator merge sweep. The five-operator `p4_churn_*` files carry the
#: same ratio and are kept for the row-count identity and the arena numbers;
#: every merge FACTOR plotted or quoted comes from this file.
MERGE = "merge_rows.csv"


def _merge_rows(fname, model=None):
    """{(matrix, rho): [merge factor per seed]} from one sched_rows file.

    The merge factor is `p3_rows / p2_rows`: distinct output rows a per-tile
    schedule touches, divided by the rows the same work costs once the schedule
    is consolidated by global row. It is an integer ratio read off the built
    schedule, not a timing, so the harness floor does not enter it.

    `merge_rows.csv` samples the run, so only its last step is a cell.
    """
    d = {}
    for r in csv.DictReader(open(os.path.join(DATA, fname))):
        if "is_last" in r and r["is_last"] != "True":
            continue
        if model is not None and r.get("churn_model") not in (model, None):
            continue
        d.setdefault((r["matrix"], float(r["rho"])), []).append(
            float(r["rows_per_block"]) / float(r["rows_merged"]))
    return d


def fig_merge_value(outdir):
    """What consolidating a schedule by global row is worth, by motion model.

    This is the mechanism figure for the paper's spine. A global row merge pays
    only for output rows that more than one dirty tile contributes to, so its
    value measures how much row sharing the motion leaves behind. Under local
    drift the dirty tiles stay adjacent and the merge holds; under uniform
    redraw they scatter and it collapses toward 1.0 -- same operators, same
    |D|, same rho, same seeds, differing only in the motion.

    The separation is not uniform across the 21 operators, and the right panel
    is there so that the two counter-examples are visible rather than only
    stated: on two operators the merge is worth MORE under uniform jump.
    """
    fig, axes = plt.subplots(1, 2, figsize=(6.6, 2.6),
                             gridspec_kw=dict(width_ratios=[1.05, 1]))
    ax = axes[0]
    series = {}
    for model in MODELS:
        d = _merge_rows(MERGE, model)
        mats = sorted({k[0] for k in d})
        col = COL_BLOCK if model == "drift" else COL_ALT
        series[model] = {m: [float(np.median(d[(m, p)])) for p in RHOS]
                         for m in mats}
        for m in mats:
            ax.plot(range(len(RHOS)), series[model][m], marker="o", ms=2.0, lw=.6,
                    color=col, alpha=.28, zorder=2)
        g = [geomean([series[model][m][i] for m in mats]) for i in range(len(RHOS))]
        ax.plot(range(len(RHOS)), g, marker="o", ms=5.0, lw=2.4, color=col,
                zorder=4, label=MLAB[model])
        for xi, v in zip(range(len(RHOS)), g):
            if xi == 0 and model == "jump":
                continue                     # rho=0 is one point, not two
            label(ax, xi, v + .55, f"{v:.2f}", color=col, size=6.4, weight="bold")
    ax.axhline(1.0, color=COL_EXACT, lw=1.1, zorder=1)
    ax.set_xticks(range(len(RHOS)))
    ax.set_xticklabels([f"{p:g}" for p in RHOS], fontsize=6.4)
    ax.set_xlabel(r"churn rate $\rho$   ($\rho{=}0$ is the frozen set)", labelpad=2)
    ax.set_ylabel("row touches saved by the merge")
    ax.set_xlim(-.3, len(RHOS) - .6)
    ax.set_ylim(.75, 9.6)
    ax.legend(loc="upper right", fontsize=6.4, handletextpad=.5)
    tidy(ax)

    # per operator: drift value against jump value at rho >= 0.01, so an
    # operator below the diagonal is one the motion model does not move, and an
    # operator above it is one where the merge collapses.
    #
    # MATCHED rho on both axes, and the paper's stated aggregation rule --
    # median across the five dirty-set seeds within an (operator, rho) cell,
    # then geomean over rho. An earlier version put drift over all churning rho
    # against jump at rho >= 0.01 and pooled the seeds flat, which moved
    # TSOPF_RS_b300_c1 across a band boundary in the prose that describes this
    # panel.
    ax = axes[1]
    dr = _merge_rows(MERGE, "drift")
    jp = _merge_rows(MERGE, "jump")
    mats = sorted({k[0] for k in dr})
    xs, ys = [], []
    for m in mats:
        x = geomean([float(np.median(jp[(m, p)])) for p in RHOS[2:]])
        y = geomean([float(np.median(dr[(m, p)])) for p in RHOS[2:]])
        xs.append(x); ys.append(y)
        if y / x <= 1.05:
            ax.annotate(m, (x, y), fontsize=5.6, color=INK2,
                        textcoords="offset points", xytext=(-5, 4), ha="right")
    inv = [i for i in range(len(mats)) if ys[i] / xs[i] < 0.95]
    flat = [i for i in range(len(mats)) if 0.95 <= ys[i] / xs[i] <= 1.05]
    rest = [i for i in range(len(mats)) if i not in inv and i not in flat]
    ax.scatter([xs[i] for i in rest], [ys[i] for i in rest], s=15,
               color=COL_BLOCK, lw=0, alpha=.8,
               label=f"motion model matters ({len(rest)})")
    ax.scatter([xs[i] for i in flat], [ys[i] for i in flat], s=22, marker="s",
               facecolors="none", edgecolors=INK2, lw=.9,
               label=f"indifferent ({len(flat)})")
    ax.scatter([xs[i] for i in inv], [ys[i] for i in inv], s=30, marker="D",
               color=COL_EXACT, lw=0, label=f"worth more under jump ({len(inv)})")
    lim = 8.2
    ax.plot([1, lim], [1, lim], color=INK, lw=1.0, ls=(0, (4, 2)), zorder=1)
    ax.set_xscale("log"); ax.set_yscale("log")
    for a in (ax.xaxis, ax.yaxis):
        a.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:g}"))
        a.set_minor_locator(matplotlib.ticker.NullLocator())
    ax.set_xticks([1, 2, 4, 8]); ax.set_yticks([1, 2, 4, 8])
    ax.set_xlim(.95, lim); ax.set_ylim(.95, lim)
    ax.set_xlabel(r"merge under uniform jump, $\rho\geq0.01$", labelpad=2)
    ax.set_ylabel(r"merge under local drift, $\rho\geq0.01$")
    ax.legend(loc="upper left", fontsize=6.0, handletextpad=.3, borderpad=.2)
    tidy(ax, grid="both")
    save(fig, "fig_merge_value", outdir)


def fig_motion_control(outdir):
    """Two controls on the paper's spine.

    Left: local drift and uniform jump are the endpoints alpha=0 and alpha=1 of
    one axis, so the contrast is a curve rather than a dichotomy. Right: what
    each of the two localities is worth, isolated. Relabelling the operator
    destroys index locality while holding the graph and the structural
    trajectory fixed; it costs less than destroying motion locality does.
    """
    fig, axes = plt.subplots(1, 2, figsize=(6.6, 2.45),
                             gridspec_kw=dict(width_ratios=[1.15, 1]))
    # alpha400_mix.csv, not alpha_mix.csv: the axis was re-run at the main
    # sweep's own 400 steps and five seeds, and §7's prose quotes those levels.
    # Drawing the 200-step file under 400-step prose would put a figure and a
    # paragraph on the same page disagreeing about the same curve.
    _alpha_src = "alpha400_mix.csv"
    if not os.path.exists(os.path.join(DATA, _alpha_src)):
        _alpha_src = "alpha_mix.csv"
    A = list(csv.DictReader(open(os.path.join(DATA, _alpha_src))))
    # `agg.moved()` reads an ABSENT `router_probes` key as "did not move"
    # (`.get(...) or 0.0`) -- correct for a row that never carried the column,
    # silently wrong here where this release specifically withholds it
    # (CONFLICTS.md #2). Checked explicitly so the figure skips honestly
    # instead of silently plotting every cell as frozen.
    columns.require_row(_alpha_src, A[0] if A else {}, "router_probes")
    alphas = sorted({float(r["churn_alpha"]) for r in A})
    rhos = sorted({float(r["rho"]) for r in A})
    ax = axes[0]
    ax2 = ax.twinx()
    for rho, ls, mk in zip(rhos, ["-", (0, (4, 2))], ["o", "s"]):
        g, w = [], []
        for a in alphas:
            rows = [r for r in A if float(r["churn_alpha"]) == a
                    and float(r["rho"]) == rho and agg.moved(r)]
            per = {}
            for r in rows:
                per.setdefault(r["matrix"], []).append(
                    float(r["always_delta_baseline_ms"]) / float(r["always_hst_ms"]))
            g.append(geomean([float(np.median(v)) for v in per.values()]))
            w.append(100 * sum(1 for r in rows if float(r["always_hst_ms"])
                               < float(r["always_delta_baseline_ms"])) / len(rows))
        ax.plot(alphas, g, marker=mk, ms=4.0, lw=1.9, ls=ls, color=COL_BLOCK,
                label=rf"margin, $\rho={rho:g}$", zorder=4)
        ax2.plot(alphas, w, marker=mk, ms=3.0, lw=1.1, ls=ls, color=COL_ROUTER,
                 alpha=.85, label=rf"cells won, $\rho={rho:g}$", zorder=3)
    ax.set_yscale("log")
    ax.set_yticks([1, 2, 4, 8])
    ax.set_yticklabels(["1×", "2×", "4×", "8×"])
    ax.yaxis.set_minor_locator(matplotlib.ticker.NullLocator())
    ax.set_ylim(.9, 9)
    ax.set_ylabel("column-exact ÷ block-scheduled")
    ax2.tick_params(colors=COL_ROUTER, labelsize=6.4)
    ax2.set_ylim(40, 104)
    ax.set_xlabel(r"$\alpha$: fraction of refills drawn uniformly", labelpad=2)
    ax.set_xticks(alphas)
    ax.set_xlim(-.05, 1.05)
    label(ax, 0.0, 7.6, "local drift", size=6.2, color=INK, ha="left")
    label(ax, 1.0, 7.6, "uniform jump", size=6.2, color=INK, ha="right")
    for s in ("top",):
        ax.spines[s].set_visible(False); ax2.spines[s].set_visible(False)
    ax.set_axisbelow(True); ax.grid(axis="y", linewidth=.5, color=GRID)
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, loc="lower left", fontsize=5.8, ncol=2,
              columnspacing=.8, handletextpad=.4)
    ax2.text(1.14, .5, "cells the block arm wins (%)", transform=ax.transAxes,
             rotation=90, ha="center", va="center", fontsize=6.6, color=COL_ROUTER,
             bbox=dict(boxstyle="round,pad=0.2", fc=SURF, ec="none"))

    # right: the decomposition
    _ord_rows = list(csv.DictReader(open(os.path.join(DATA, "ordering_drift.csv"))))
    columns.require_row("ordering_drift.csv", _ord_rows[0] if _ord_rows else {},
                        "router_probes")
    O = [r for r in _ord_rows if float(r["rho"]) > 0 and agg.moved(r)]
    by = {o: {(r["matrix"], r["seed"], r["rho"]): r
              for r in O if r["ordering"] == o} for o in ("native", "relabelled")}
    ch = sorted(set(by["native"]) & set(by["relabelled"]))

    # NOTE: named `_ratio_geo`, not `agg` -- a local `def agg(...)` here used to
    # shadow the module-level `agg` import (the geomean/exclusion-rule module)
    # for this function's ENTIRE body, since Python marks a name local to a
    # function the moment it is assigned anywhere in that function. That made
    # `agg.moved(r)` above (line ~636) raise `UnboundLocalError` on every call,
    # not just when the release policy withholds a column -- a latent crash
    # independent of this release's export policy.
    def _ratio_geo(num, den):
        per = {}
        for k in ch:
            per.setdefault((k[0], k[2]), []).append(float(num[k]) / float(den[k]))
        return geomean([float(np.median(v)) for v in per.values()])

    nat_c = {k: by["native"][k]["always_delta_baseline_ms"] for k in ch}
    rel_c = {k: by["relabelled"][k]["always_delta_baseline_ms"] for k in ch}
    nat_h = {k: by["native"][k]["always_hst_ms"] for k in ch}
    rel_h = {k: by["relabelled"][k]["always_hst_ms"] for k in ch}
    J = RD.split(load_router("jump"))[1]
    jper = {}
    for r in J:
        jper.setdefault((r["matrix"], r["rho"]), []).append(r["csr"] / r["hst"])
    bars = [
        ("local drift\nas the operator ships", _ratio_geo(nat_c, nat_h),
         sum(1 for k in ch if float(nat_h[k]) < float(nat_c[k])), len(ch), COL_BLOCK),
        ("local drift\nindex order destroyed", _ratio_geo(rel_c, rel_h),
         sum(1 for k in ch if float(rel_h[k]) < float(rel_c[k])), len(ch), COL_ROUTER),
        ("  …baseline held\nat its native time", _ratio_geo(nat_c, rel_h),
         sum(1 for k in ch if float(rel_h[k]) < float(nat_c[k])), len(ch), MUTED),
        ("uniform jump\nindex order intact",
         geomean([float(np.median(v)) for v in jper.values()]),
         sum(1 for r in J if r["csr"] > r["hst"]), len(J), COL_ALT),
    ]
    ax = axes[1]
    y = np.arange(len(bars))[::-1]
    for yi, (nm, v, w, n, c) in zip(y, bars):
        ax.barh(yi, v, height=.62, color=c, alpha=.9)
        ax.text(v + .12, yi, f"{v:.2f}×   {w}/{n}", va="center", fontsize=6.3,
                color=INK2)
    ax.axvline(1.0, color=COL_EXACT, lw=1.1)
    ax.set_yticks(y)
    ax.set_yticklabels([b[0] for b in bars], fontsize=5.9)
    ax.set_xlabel("column-exact ÷ block-scheduled", labelpad=2)
    ax.set_xlim(0, max(b[1] for b in bars) * 1.75)
    ax.set_ylim(-.7, len(bars) - .35)
    tidy(ax, grid="x")
    fig.subplots_adjust(wspace=.70)
    save(fig, "fig_motion_control", outdir)


def fig_amortization(outdir):
    """The probe is a one-time cost, so it amortizes in SESSION LENGTH.

    `router_ms` is the mean per-step cost over all 400 steps and
    `router_steady_ms` the mean after the 32-step probe, so the one-time excess
    is exactly 400*(router_ms - router_steady_ms) and an S-step session costs
    steady + excess/S per step. That is an identity, not a fit. The sweep's own
    length is marked, because the fraction the paper used to report as a
    property of the policy is that one point on this curve.
    """
    S = list(csv.DictReader(open(os.path.join(DATA,
                                              "selection_reexam_session.csv"))))
    off = [k for k in S[0] if k.endswith("_held") and "nested selection" in k
           and "free" in k]
    scopes, seen = [], set()
    for r in S:
        k = (r["churn_model"], r["scope"])
        if k not in seen:
            seen.add(k); scopes.append(k)
    fig, ax = plt.subplots(figsize=(4.4, 2.5))
    styles = ["-", (0, (4, 2)), (0, (1, 1.4))]
    for (m, sc), ls in zip(scopes, styles):
        rows = [r for r in S if r["churn_model"] == m and r["scope"] == sc]
        x = [int(r["steps"]) for r in rows]
        ax.plot(x, [float(r["router_held"]) for r in rows], ls=ls, lw=1.8,
                color=COL_ROUTER,
                label=f"{MLAB[m]}, {sc.split(' (')[0]}")
        if off:
            ax.plot(x, [float(r[off[0]]) for r in rows], ls=ls, lw=1.0,
                    color=COL_PRED, alpha=.85)
    ax.set_xscale("log")
    ax.axvline(400, color=INK, lw=.9, ls=(0, (2, 2)))
    label(ax, 400, .30, "the sweep's\nown length", size=6.0, color=INK)
    ax.set_xlim(28, 2e5)
    ax.set_ylim(.20, 1.03)
    ax.set_xlabel("session length (steps)", labelpad=2)
    ax.set_ylabel("fraction of the hindsight ceiling held")
    ax.legend(loc="lower right", fontsize=6.0, handletextpad=.5)
    label(ax, 4.5e3, .965, "offline model", size=6.2, color=COL_PRED)
    label(ax, 4.5e3, .845, "online policy", size=6.2, color=COL_ROUTER)
    tidy(ax, grid="both")
    save(fig, "fig_amortization", outdir)


def fig_splice_events(outdir):
    """Why the merged schedule cannot be patched cheaply, in event counts.

    Both panels are per (operator, rho) cell of the splice harness. Left: how
    many placement events each strategy performs per step. Right: what one
    event costs against the from-scratch merged rebuild it replaces, and what
    entering the patchable form costs before any of that.
    """
    S = list(csv.DictReader(open(os.path.join(DATA, "splice.csv"))))
    S.sort(key=lambda r: (r["matrix"], float(r["rho"])))
    labs = [f"{r['matrix']}  " + r"$\rho$=" + f"{float(r['rho']):g}" for r in S]
    y = np.arange(len(S))[::-1]
    fig, axes = plt.subplots(1, 2, figsize=(6.6, 2.45),
                             gridspec_kw={"wspace": .30})

    ax = axes[0]
    h1 = ax.barh(y + .19, [float(r["splices"]) for r in S], height=.34,
                 color=COL_BLOCK, alpha=.9,
                 label="merged-and-patchable: tiles spliced")
    h2 = ax.barh(y - .19, [float(r["per_block_new"]) for r in S], height=.34,
                 color=COL_EXACT, alpha=.9,
                 label="per-tile compiled: tiles compiled")
    ax.set_xscale("log")
    ax.set_xlabel("placement events per step  (log)", labelpad=2)
    ax.set_yticks(y); ax.set_yticklabels(labs, fontsize=5.8)
    ax.set_xlim(.04, 300)
    ax.set_xticks([.1, 1, 10, 100])
    ax.set_ylim(-.75, len(S) - .25)
    tidy(ax, grid="x")

    ax = axes[1]
    h3 = ax.barh(y + .19, [float(r["merged_build_ms"]) / float(r["wall_ms"]) for r in S],
                 height=.34, color=COL_ROUTER, alpha=.9,
                 label="one splice ÷ the rebuild it replaces")
    h4 = ax.barh(y - .19, [float(r["patchable_build_ms"]) / float(r["merged_build_ms"]) for r in S],
                 height=.34, color=COL_PRED, alpha=.9,
                 label="entry fee: patchable build ÷ merged build")
    ax.axvline(1.0, color=INK, lw=.9, zorder=3)
    ax.set_xscale("log")
    ax.set_xlabel("ratio  (log)", labelpad=2)
    ax.set_yticks(y); ax.set_yticklabels([])
    ax.set_xlim(.75, 900)
    ax.set_xticks([1, 10, 100])
    ax.set_ylim(-.75, len(S) - .25)
    tidy(ax, grid="x")

    fig.legend(handles=[h1, h2, h3, h4], loc="lower center",
               bbox_to_anchor=(.5, -.30), ncol=2, fontsize=6.2, frameon=False,
               columnspacing=1.4, handlelength=1.3)
    save(fig, "fig_splice_events", outdir)


def fig_regret_cdf(outdir):
    """Where each strategy's cost lands, cell by cell, on the workload mix.

    The learned series are the leave-one-operator-out predictions from
    predictor_study, recomputed here from the same committed loader so the
    curve and the table cannot disagree.
    """
    import predictor_study as ps
    fig, axes = two_panel(6.6, 2.35, sharey=True)
    for ax, model in zip(axes, MODELS):
        rows = ps.scope_rows(ps.load(model), MIX)
        s_pred, _, _ = ps.lomo(rows, ps.STRUCTURE, "logistic regression")
        T = [r for r in _pred_table(model, MIX)
             if r["regime"] == "both" and not r["model"].startswith("always")]
        best_b = min(T, key=lambda r: float(r["regret_geo"]))["model"]
        b_pred, _, _ = ps.lomo(rows, ps.STRUCTURE + ps.CHURN, best_b)
        series = [
            ("always column-exact",
             [d["cost_csr"] / d["cost_oracle"] for d in rows], COL_EXACT, "-", 1.2),
            ("always block-scheduled",
             [d["cost_hst"] / d["cost_oracle"] for d in rows], COL_BLOCK, "-", 1.2),
            ("structure-only predictor (logistic)",
             ps.regret_vec(rows, s_pred), COL_PRED, (0, (3, 2)), 1.2),
            (f"structure+$\\rho$ predictor ({best_b})",
             ps.regret_vec(rows, b_pred), COL_PRED, "-", 1.5),
            ("measured router (+calibration)",
             [d["router_full"] / d["cost_oracle"] for d in rows], COL_ROUTER, (0, (3, 2)), 1.2),
            ("measured router (steady)",
             [d["router_steady"] / d["cost_oracle"] for d in rows], COL_ROUTER, "-", 1.7),
        ]
        for name, v, c, ls, lw in series:
            v = np.sort(np.asarray(v, float))
            ax.step(v, np.arange(1, len(v) + 1) / len(v), where="post", color=c,
                    ls=ls, lw=lw, label=name)
        ax.axvline(1.0, color=INK, lw=.8)
        ax.set_xscale("log")
        ax.set_xticks([1, 2, 5, 10, 35])
        ax.set_xticklabels(["1×", "2×", "5×", "10×", "35×"], fontsize=6.4)
        ax.set_xlabel("slowdown vs the hindsight oracle", labelpad=2)
        tidy(ax, grid="both")
    axes[0].set_ylabel(f"fraction of cells")
    fig.legend(*axes[0].get_legend_handles_labels(), loc="lower center",
               bbox_to_anchor=(.5, -.34), fontsize=6.2, ncol=2, frameon=False,
               columnspacing=1.2)
    save(fig, "fig_regret_cdf", outdir)


def fig_third_arm(outdir):
    """A third implementation was built and measured. Is two arms enough?

    Left: the third arm against the shipped block-scheduled one, per churn rate.
    Right: what a three-arm hindsight oracle would have been worth over the
    two-arm oracle the router actually chooses between. Both panels carry both
    motion models, and neither is averaged into the other.
    """
    fig, axes = plt.subplots(1, 2, figsize=(6.6, 2.2))
    col = {"drift": COL_BLOCK, "jump": COL_ALT}
    x = np.arange(len(RHOS))
    for model in MODELS:
        R = load_router(model)
        by = med_by_seed(R, lambda r: r["patchable_vs_per_block"])
        gain = med_by_seed(R, lambda r: r["oracle3_vs_oracle2"])
        mats = sorted({r["matrix"] for r in R})
        v = [geomean([by[(m, p)] for m in mats]) for p in RHOS]
        g = [geomean([gain[(m, p)] for m in mats]) for p in RHOS]
        axes[0].plot(x, v, marker="o", ms=3.4, lw=1.5, color=col[model], label=MLAB[model])
        axes[1].plot(x, [(q - 1) * 100 for q in g], marker="o", ms=3.4, lw=1.5,
                     color=col[model], label=MLAB[model])
    axes[0].axhline(1.0, color=INK, lw=.9)
    label(axes[0], 3.0, 1.02, "parity with the shipped arm", color=INK, size=6.2)
    axes[0].set_ylabel("third arm ÷ block-scheduled")
    axes[0].set_ylim(0, 1.35)
    axes[1].axhline(0.0, color=INK, lw=.9)
    axes[1].set_ylabel("three-arm oracle gain (%)")
    axes[1].set_ylim(-1, 11)
    for ax in axes:
        ax.set_xticks(x); ax.set_xticklabels([f"{p:g}" for p in RHOS], fontsize=6.4)
        ax.set_xlabel(r"churn rate $\rho$", labelpad=2)
        ax.set_xlim(-.25, len(RHOS) - .3)
        ax.legend(fontsize=6.2, loc="upper right")
        tidy(ax)
    save(fig, "fig_third_arm", outdir)


#: The figure set, in paper order. Single source of truth -- check_overlaps.py
#: and contact_sheet.py import it rather than keeping their own copies, which
#: is how a new figure used to escape the layout gate.

# ---------------------------------------------------------------- family control

def _family_rows():
    """family.csv with §3.2's exclusion rule applied.

    A churn-labelled cell whose dirty set never moved is a frozen cell wearing a
    churn label; the column-exact lane rebuilds on any change to D at all, so
    one rebuild over the whole run identifies it without reference to the
    generator.
    """
    # ⚠️ pre-fix vintage (ISSUES #055) -- same acknowledgement as
    # paper_numbers._fam(); the figure and the number must not disagree
    # about which vintage they show.
    rows = vintage.read(
        "family.csv",
        columns=("rho", "block_open_vs_delta_baseline", "hst_vs_delta_baseline", "seed", "delta_baseline_rebuilds"),
        accept_stale="§4 figure matches paper_numbers._fam(); see ADR-0001 (docs/adr/)",
        directory=DATA)
    out = []
    for r in rows:
        for k in ("rho", "block_open_vs_delta_baseline", "hst_vs_delta_baseline", "seed"):
            r[k] = float(r[k])
        r["delta_baseline_rebuilds"] = int(float(r["delta_baseline_rebuilds"]))
        if r["rho"] > 0 and r["delta_baseline_rebuilds"] <= 1:
            continue
        out.append(r)
    return out


def fig_family(outdir):
    """Two implementations of one strategy, against the shared baseline.

    The point is the overlap, not the level: if the open arm (written against
    the paper's prose, sharing no code with the proprietary one) traces the same
    curve, the dichotomy is a property of the strategy. Where the two curves
    separate is where the paper's claim is about a product instead.
    """
    rows = _family_rows()
    fig, axes = two_panel(6.6, 2.4, sharey=True)
    for ax, model in zip(axes, MODELS):
        sub = [r for r in rows if r["motion"] == model]
        for arm, colour, marker, name in (
                ("block_open_vs_delta_baseline", COL_BLOCK, "o", "open reference arm"),
                ("hst_vs_delta_baseline", INK2, "s", "proprietary arm")):
            ys = []
            for p in RHOS:
                cell = {}
                for r in sub:
                    if r["rho"] == p:
                        cell.setdefault(r["matrix"], []).append(r[arm])
                v = [sorted(x)[len(x) // 2] for x in cell.values()]
                ys.append(geomean(v) if v else float("nan"))
            ax.plot(range(len(RHOS)), ys, marker=marker, ms=3.4, lw=1.5,
                    color=colour, label=name, zorder=3)
        ax.axhline(1.0, color=COL_EXACT, lw=1.1, zorder=1)
        ax.set_yscale("log")
        ax.set_yticks([0.3, 0.5, 1, 2, 5, 10])
        ax.set_yticklabels(["0.3×", "0.5×", "1×", "2×", "5×", "10×"])
        ax.set_xticks(range(len(RHOS)))
        ax.set_xticklabels([f"{p:g}" for p in RHOS], fontsize=6.4)
        ax.set_xlabel(r"churn rate $\rho$", labelpad=2)
        ax.set_title(model.replace("_", " "), fontsize=7.2, color=INK2, pad=3)
    axes[0].set_ylabel("÷ column-exact")
    axes[0].legend(frameon=False, fontsize=6.2, loc="lower right")
    label(axes[0], 0.02, 0.36, "frozen: both lose", size=5.9, ha="left",
          color=INK2)
    save(fig, "fig_family", outdir)

ALL = ["fig_task", "fig_workload", "fig_frozen", "fig_churn_response",
       "fig_heatmap", "fig_motion_control", "fig_merge_value", "fig_overlap",
       "fig_asymmetry", "fig_regret_cdf", "fig_amortization",
       "fig_splice_events", "fig_third_arm", "fig_family"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default=os.path.join(HERE, "figs"))
    a = ap.parse_args()
    os.makedirs(a.outdir, exist_ok=True)
    print("figures ->", a.outdir)
    skipped = []
    for name in ALL:
        try:
            globals()[name](a.outdir)
        except columns.ColumnUnavailable as e:
            print(f"  {name}: skipped -- {e}")
            skipped.append((name, str(e)))
            placeholder(name, str(e), a.outdir)
        except ModuleNotFoundError as e:
            # fig_regret_cdf imports predictor_study, which needs
            # scikit-learn -- a real, README-documented dependency of this
            # script ("the figures ... Needs numpy, matplotlib,
            # scikit-learn"), not a withheld-column condition. Reported the
            # same non-crashing way rather than aborting the whole run.
            reason = f"missing dependency ({e}); see README's dependency table"
            print(f"  {name}: skipped -- {reason}")
            skipped.append((name, reason))
            placeholder(name, reason, a.outdir)

    print(f"\n{len(ALL) - len(skipped)}/{len(ALL)} figures written"
          + (f", {len(skipped)} skipped:" if skipped else ""))
    for name, reason in skipped:
        print(f"  {name}: {reason}")
    return 0  # a documented, honestly-reported skip is not a crash


if __name__ == "__main__":
    raise SystemExit(main())
