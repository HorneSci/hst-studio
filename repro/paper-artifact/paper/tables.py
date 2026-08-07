#!/usr/bin/env python3
"""Emit every LaTeX table in the paper from the measured CSVs.

Same rule as figures.py: no number is typed by hand. Writes tab_*.tex into
--outdir (default: alongside this file), which paper.tex \\input{}s.
"""
import argparse, csv, math, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))          # paper/
ROOT = os.path.dirname(HERE)                                 # paper-artifact/, where agg.py/vintage.py live
DATA = os.path.join(ROOT, "data")                            # the released CSVs
sys.path.insert(0, ROOT)

DOMAIN = {
    "TSOPF_RS_b39_c30": "power flow", "TSOPF_RS_b162_c3": "power flow",
    "TSOPF_RS_b300_c1": "power flow", "case9": "power flow",
    "bcspwr09": "power network", "bcspwr10": "power network",
    "scircuit": "circuit sim", "memplus": "circuit sim", "add32": "circuit sim",
    "circuit_3": "circuit sim", "rajat03": "circuit sim", "wang3": "device sim",
    "ct20stif": "structural FEM", "bcsstk18": "structural FEM",
    "bcsstk25": "structural FEM", "msc10848": "structural FEM",
    "nasa2910": "structural FEM", "s3rmt3m3": "shell FEM",
    "olafu": "structural FEM", "raefsky3": "fluid/struct.", "epb2": "plate/beam",
}
import numpy as np  # noqa: E402
import router_data as RD  # noqa: E402

RHOS = [0.0, 0.002, 0.01, 0.05, 0.25]
MODELS = list(RD.MODELS)
MIX = "workload mix (frozen + churning)"


from agg import geomean  # noqa: E402  (was: no empty guard -> ZeroDivisionError)
import columns  # noqa: E402


def esc(s):
    return s.replace("_", r"\_")


def med_by_seed(rows, f):
    """Median across seeds per (matrix, rho). One seed's ratio is not the
    operator's ratio -- the harness floor is several percent per operator."""
    d = {}
    for r in rows:
        d.setdefault((r["matrix"], r["rho"]), []).append(f(r))
    return {k: float(np.median(v)) for k, v in d.items()}


def tab_operators(out):
    """Per operator, both motion models, five churn rates. Never averaged: each
    operator gets one row per motion model and the model is named in the row."""
    data = {m: load_med(m) for m in MODELS}
    order = sorted(data["drift"][1],
                   key=lambda m: -max(data["drift"][0][(m, p)] for p in RHOS))
    ncol = len(RHOS)
    L = [r"\begin{tabular}{llrrrl" + "c" * ncol + "}", r"\toprule",
         r"operator & domain & $N$ & nnz & dens & motion & "
         r"\multicolumn{%d}{c}{best arm $\div$ column-exact, by $\rho$}\\" % ncol,
         r"\cmidrule(lr){7-%d}" % (6 + ncol),
         r" & & & & & & " + " & ".join(f"${p:g}$" for p in RHOS) + r" \\", r"\midrule"]
    for m in order:
        for i, model in enumerate(MODELS):
            best, mats, meta, arm = data[model]
            cells = []
            for p in RHOS:
                v = best[(m, p)]
                s = f"{v:.2f}" if v < 9.95 else f"{v:.1f}"
                if arm[(m, p)] >= 0.5:      # block-scheduled is the majority arm
                    s = r"\textbf{" + s + "}"
                cells.append(s)
            head = (f"{esc(m)} & {DOMAIN[m]} & {meta[m][0]:,} & {meta[m][1]:,} & "
                    f"{meta[m][2]:.2f}" if i == 0 else " &  &  &  & ")
            L.append(f"{head} & {RD.MODEL_LABEL[model]} & " + " & ".join(cells) + r" \\")
    L += [r"\bottomrule", r"\end{tabular}"]
    open(os.path.join(out, "tab_operators.tex"), "w").write("\n".join(L) + "\n")


def load_med(model):
    R = RD.load(model)
    best = med_by_seed(R, lambda r: r["oracle_vs_csr"])
    arm = med_by_seed(R, lambda r: 1.0 if r["arm"] == "hst" else 0.0)
    mats = sorted({r["matrix"] for r in R})
    meta = {}
    for m in mats:
        rs = [r for r in R if r["matrix"] == m]
        meta[m] = (rs[0]["N"], rs[0]["nnz"], float(np.median([r["dens"] for r in rs])))
    return best, mats, meta, arm


def tab_headline(out):
    """Frozen and churning, side by side, per motion model. The four blocks are
    never collapsed into one another -- that is the whole point of the table."""
    L = [r"\begin{tabular}{lcccc}", r"\toprule"]
    for model in MODELS:
        R = RD.load(model)
        froz, ch = RD.split(R)
        L += [r"\multicolumn{5}{l}{\emph{" + RD.MODEL_LABEL[model] + r"}}\\",
              r"\cmidrule(lr){1-5}",
              r"& \multicolumn{2}{c}{frozen ($n{=}%d$)} & "
              r"\multicolumn{2}{c}{churning ($n{=}%d$)}\\" % (len(froz), len(ch)),
              r"\cmidrule(lr){2-3}\cmidrule(lr){4-5}",
              r"strategy & speedup & worst cell & speedup & worst cell \\", r"\midrule"]

        def line(name, key, bold=False):
            c = []
            for S in (froz, ch):
                sp = geomean([r["csr"] / r[key] for r in S])
                worst = max(r[key] / r["oracle"] for r in S)
                c += [f"{sp:.2f}$\\times$", f"{worst:.2f}$\\times$"]
            n = r"\textbf{" + name + "}" if bold else name
            L.append(f"{n} & " + " & ".join(c) + r" \\")

        line("always column-exact", "csr")
        line("always block-scheduled", "hst")
        line("measured router (steady state)", "router_steady")
        line("measured router (incl. calibration)", "router_full", bold=True)
        L.append(r"\midrule")
        line("hindsight oracle \\emph{(not achievable)}", "oracle")
        L.append(r"\midrule" if model != MODELS[-1] else r"\bottomrule")
    L.append(r"\end{tabular}")
    open(os.path.join(out, "tab_headline.tex"), "w").write("\n".join(L) + "\n")


def tab_predictors(out):
    T = list(csv.DictReader(open(os.path.join(DATA, "predictor_study.csv"))))
    L = [r"\begin{tabular}{llccccc}", r"\toprule",
         r"features & model & LOMO acc. & in-sample & "
         r"\multicolumn{3}{c}{regret vs oracle}\\",
         r"\cmidrule(lr){5-7}",
         r" & & & & geomean & p90 & worst \\"]
    for model in MODELS:
        S = [r for r in T if r["churn_model"] == model and r["scope"] == MIX]
        L += [r"\midrule",
              r"\multicolumn{7}{l}{\emph{" + RD.MODEL_LABEL[model] +
              r" --- " + MIX + r"}}\\", r"\midrule"]
        seen = set()
        for r in S:
            if r["regime"] == "measured":
                continue
            if r["model"].startswith("always"):
                if r["model"] in seen:
                    continue
                seen.add(r["model"])
                reg = "---"
            else:
                reg = r["regime"].replace("churn", r"observed $\rho$")
            L.append(f"{reg} & {r['model']} & {float(r['lomo_acc']):.3f} & "
                     f"{float(r['insample_acc']):.3f} & {float(r['regret_geo']):.3f} & "
                     f"{float(r['regret_p90']):.2f} & {float(r['regret_worst']):.2f}" + r" \\")
        L.append(r"\cmidrule(lr){1-7}")
        for r in S:
            if r["regime"] != "measured":
                continue
            nm = r["model"].replace("MEASURED ROUTER ", "measured router ")
            L.append(r"\multicolumn{2}{l}{\textbf{" + nm + "}} & " +
                     f"{float(r['lomo_acc']):.3f} & --- & "
                     f"\\textbf{{{float(r['regret_geo']):.3f}}} & "
                     f"{float(r['regret_p90']):.2f} & "
                     f"\\textbf{{{float(r['regret_worst']):.2f}}}" + r" \\")
    L += [r"\bottomrule", r"\end{tabular}"]
    open(os.path.join(out, "tab_predictors.tex"), "w").write("\n".join(L) + "\n")


def tab_contrasts(out):
    r"""The effect sizes the selection argument rests on, with intervals.

    Straight out of predictor_bootstrap.csv. A point estimate without an
    interval is what let the pre-fix study read as decisive when it was not.

    EVERY non-degenerate scope is emitted, including the frozen ones. An
    earlier version filtered to ("churning only", MIX), which dropped the one
    scope where contrast (c) does not exclude zero -- exactly the row a reader
    checking the claim would look for.

    LAYOUT. The contrast name is a spanning group header rather than a repeated
    first column. Emitted as five columns it ran 117pt past the text block, and
    the offending column was pure repetition: each contrast string was printed
    two or three times, once per scope. Hoisting it costs no information, keeps
    all 24 data rows and all three statistics, and keeps the body at \small
    rather than shrinking the intervals into illegibility.

    Significance is marked with \boldmath, not \textbf: every cell is math, and
    \textbf leaves math untouched, so the caption's "bold marks intervals
    excluding zero" was describing a rule that did not render.
    """
    B = list(csv.DictReader(open(os.path.join(DATA, "predictor_bootstrap.csv"))))
    stats = ["geomean regret", "worst-case regret", "accuracy"]
    # Short forms so the table fits the column. The full contrast strings are in
    # predictor_bootstrap.csv, which is released.
    NAME = {"(a)": r"(a) nested structure-only $-$ policy",
            "(b)": r"(b) $\rho$-only tree $-$ nested structure-only",
            "(c)": r"(c) nested structure$+\rho$ $-$ policy",
            "(d)": r"(d) nested structure$+\rho$ $-$ policy (+calib.)"}
    SCOPE = {"frozen only": "frozen", "churning only": "churning",
             MIX: "mixture"}
    L = [r"\begin{tabular}{lccc}", r"\toprule",
         r"scope & " + " & ".join(
             s.replace("regret", "reg.") for s in stats) + r"\\"]
    for model in MODELS:
        L += [r"\midrule",
              r"\multicolumn{4}{l}{\emph{" + RD.MODEL_LABEL[model] + r"}}\\",
              r"\midrule"]
        rows = [r for r in B if r["churn_model"] == model]
        for k, tag in enumerate(("(a)", "(b)", "(c)", "(d)")):
            if k:
                L.append(r"\addlinespace[2pt]")
            L.append(r"\multicolumn{4}{l}{" + NAME[tag] + r"}\\")
            for scope in ("frozen only", "churning only", MIX):
                sel = {r["statistic"]: r for r in rows
                       if r["contrast"].startswith(tag) and r["scope"] == scope}
                if not sel:
                    continue
                cells = []
                for s in stats:
                    r = sel[s]
                    d, lo, hi = float(r["delta"]), float(r["ci_lo"]), float(r["ci_hi"])
                    c = f"${d:+.3f}$ {{\\scriptsize$[{lo:+.2f},{hi:+.2f}]$}}"
                    if r["significant"] == "1":
                        c = r"{\boldmath " + c + "}"
                    cells.append(c)
                n = next(iter(sel.values()))["n_cells"]
                L.append(f"\\quad {SCOPE[scope]} ($n{{=}}{n}$) & "
                         + " & ".join(cells) + r" \\")
    L += [r"\bottomrule", r"\end{tabular}"]
    open(os.path.join(out, "tab_contrasts.tex"), "w").write("\n".join(L) + "\n")


def tab_baselines(out):
    # key by (matrix, ordering): keying by matrix alone dropped one ordering
    Bb = {(r["matrix"], r["ordering"]): r
          for r in csv.DictReader(open(os.path.join(DATA, "baseline_best.csv")))
          if r["B"] == "8"}
    Tt = {(r["matrix"], r["ordering"]): r
          for r in csv.DictReader(open(os.path.join(DATA, "torch_native_t8.csv")))
          if r["B"] == "8" and r["mode"] == "neighborhood"}
    ms = sorted(set(Bb) & set(Tt))
    ladder = [
        ("PyTorch, delta re-sliced each step", geomean([float(Tt[m]["slice_ms"]) for m in ms])),
        (r"PyTorch \texttt{torch.sparse.mm}, full recompute", geomean([float(Tt[m]["full_recompute_ms"]) for m in ms])),
        ("PyTorch, delta pre-sliced once", geomean([float(Tt[m]["presliced_ms"]) for m in ms])),
        ("CSC delta, hand-written C++", geomean([float(Bb[m]["delta_csc_ms"]) for m in ms])),
        ("column-exact CSR delta, 1 thread", geomean([float(Bb[m]["delta_baseline_1thread_ms"]) for m in ms])),
        (r"\textbf{column-exact CSR delta, best thread count}",
         geomean([float(Bb[m]["delta_baseline_best_ms"]) for m in ms])),
    ]
    base = ladder[-1][1]
    L = [r"\begin{tabular}{lrr}", r"\toprule",
         r"delta implementation & ms/step & $\div$ our baseline \\", r"\midrule"]
    for name, v in ladder:
        L.append(f"{name} & {v:.3f} & {v/base:.1f}$\\times$" + r" \\")
    L += [r"\bottomrule", r"\end{tabular}"]
    open(os.path.join(out, "tab_baselines.tex"), "w").write("\n".join(L) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default=HERE)
    a = ap.parse_args()
    skipped = []
    for fn in (tab_operators, tab_headline, tab_predictors, tab_baselines,
               tab_contrasts):
        try:
            fn(a.outdir)
            print(" ", fn.__name__)
        except columns.ColumnUnavailable as e:
            print(f"  {fn.__name__}: skipped -- {e}")
            skipped.append((fn.__name__, str(e)))

    print(f"\n{5 - len(skipped)}/5 tables written"
          + (f", {len(skipped)} skipped:" if skipped else ""))
    for name, reason in skipped:
        print(f"  {name}: {reason}")
    return 0  # a documented, honestly-reported skip is not a crash


if __name__ == "__main__":
    raise SystemExit(main())
