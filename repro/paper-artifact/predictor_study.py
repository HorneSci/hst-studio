#!/usr/bin/env python3
"""Can a structural predictor replace measurement?

Contribution-2 evidence. Trains every reasonable offline predictor of the
better delta arm and scores it under leave-one-operator-out cross-validation --
the protocol that matches deployment, where the operator is new.

Three feature regimes are scored separately, because conflating them is the
mistake that makes prediction look better than it is:

  structure  matrix-intrinsic only (dens, size, row density, dirty fraction).
             This is the regime a *predictive router* actually operates in:
             choose the arm from the operator, before observing behaviour.
  churn      the observed drift rate alone. Not a prediction from structure --
             it is a runtime measurement, and a cheap one. Included to show
             how much of any predictor's apparent skill is just this.
  both       everything.

Reports accuracy AND the regret distribution (geomean / p90 / worst slowdown
vs the hindsight oracle), because the mis-route penalty is asymmetric by more
than an order of magnitude and accuracy alone therefore misprices every model.
Effect sizes against the measured router come with 95% intervals from a paired
bootstrap over operators, not as bare point estimates.

The offline side of every contrast is a NESTED procedure (`nested_lomo`): the
learner is chosen inside each training fold, so the choice never sees the rows
that score it. What the contrast prices is therefore a model-selection
procedure and not any single model named in advance -- a distinction that
matters here, because two defensible pre-registrations disagree about the sign
on two of the three scopes (`selection_reexam.py`).

Accuracy is reported and is not used as an argument: on the scope where a
selection problem is live, 87-100% of the accuracy gaps in this table sit on
cells whose labels this harness cannot resolve (`selection_reexam_o3.csv`).

**Input is the pooled-scratch vintage, one motion model at a time**
(`router_data.py`). The pre-fix `router_v3.csv` this study used to read is
retired: it charged an M*B zero-fill to every HST lane and to no baseline, which
moved the *labels* this study is fitted to separate, not merely the noise.

Output: predictor_study.csv (model scores) + predictor_bootstrap.csv (paired
effect sizes) + summary tables on stdout.

--- vendored into oss/paper-artifact 2026-08-05 ---
Verbatim copy of `learn/pytorch_fit/predictor_study.py`. `paper/figures.py`'s
`fig_regret_cdf` imports this module (`import predictor_study as ps`) to
recompute the leave-one-operator-out predictors live, "from the same
committed loader so the curve and the table cannot disagree" -- it was never
copied into the released artifact, so that figure could not even be
imported, let alone run. `ps.load()` reads through `router_data.RD.load()`,
which already fails honestly (`columns.ColumnUnavailable`) when a released
CSV withholds `dens`/`router_probes` (CONFLICTS.md #1, #2) -- both of
`fig_regret_cdf`'s source CSVs do, so this module's own row-building fails
the same clean way `figures.py`'s per-figure skip handler already catches.
This copy's `main()` (regenerating `predictor_study.csv` /
`predictor_bootstrap.csv` from scratch) is not part of the documented public
pipeline and needs `scikit-learn`, per README's own dependency table for
`figures.py`; `--out`/`--boot-out` default beside this file rather than into
`data/` and are not rewired here, since nothing in the released pipeline
invokes `main()`. Edit the source of truth in
`learn/pytorch_fit/predictor_study.py`, not this copy.
"""
import argparse, csv, math, os, sys
import numpy as np
# scikit-learn is imported inside models(), not here. Importing it at module
# scope made `import predictor_study` fail on a machine without it, and the
# caller that pays for that -- paper/figures.py's fig_regret_cdf -- would then
# report a missing dependency for a figure whose actual blocker is a withheld
# column, which is still there after you install ~100 MB of scikit-learn.
# Deferring the import lets load() run and name the real reason first.

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import router_data as RD  # noqa: E402

STRUCTURE = ["dens", "log_N", "log_nnz", "row_nnz", "dirty_frac"]
CHURN = ["rho"]
REGIMES = {"structure": STRUCTURE, "churn": CHURN, "both": STRUCTURE + CHURN}

#: scopes, in the order they are reported. Frozen and churning are scored
#: separately and never averaged into one another; the mixture is scored too,
#: but it is *named* a mixture -- it is the only scope in which "is rho the
#: decisive variable" is even a well-posed question, because rho has no
#: variance inside either pure regime.
SCOPES = ["frozen only", "churning only", "workload mix (frozen + churning)"]

BOOT = 4000
RNG_SEED = 0


from agg import geomean  # noqa: E402


def load(model="drift"):
    """Feature/label/cost table for one motion model."""
    out = []
    for r in RD.load(model):
        N, nnz = float(r["N"]), float(r["nnz"])
        out.append(dict(
            model=model, matrix=r["matrix"], seed=r["seed"],
            rho=r["rho"], dens=r["dens"],
            N=N, nnz=nnz, log_N=math.log10(N), log_nnz=math.log10(nnz),
            row_nnz=nnz / N, dirty_frac=r["dirty_cols"] / N,
            y=1 if r["arm"] == "hst" else 0,
            cost_csr=r["csr"], cost_hst=r["hst"], cost_oracle=r["oracle"],
            router_steady=r["router_steady"], router_full=r["router_full"],
            router_arm_hst=1 if "hst" in r["router_arm"] else 0,
        ))
    return out


def scope_rows(rows, scope):
    if scope == "frozen only":
        return [d for d in rows if d["rho"] == 0]
    if scope == "churning only":
        return [d for d in rows if d["rho"] > 0]
    return rows


def regret_vec(rows, preds):
    """Per-cell slowdown vs the hindsight oracle for a vector of arm choices."""
    return np.array([(rows[i]["cost_hst"] if p == 1 else rows[i]["cost_csr"])
                     / rows[i]["cost_oracle"] for i, p in enumerate(preds)])


def regret_stats(v):
    v = np.sort(np.asarray(v, float))
    return dict(geo=geomean(list(v)), p90=float(v[int(0.9 * (len(v) - 1))]),
                worst=float(v[-1]), over2x=int((v > 2.0).sum()))


#: The two fixed arms are constants, not fitted models. sklearn's
#: DummyClassifier(constant=c) refuses to fit when c is absent from the training
#: labels -- which is exactly the case that matters here, since under local
#: drift the churning class collapses to one label. A constant arm is a
#: constant arm whether or not the data ever chose it, so express it as one.
CONST = {"always column-exact": 0, "always block-scheduled": 1}


def models():
    """The fitted arms. Imports scikit-learn here rather than at module scope --
    see the note beside the imports."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.tree import DecisionTreeClassifier
    from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
    from sklearn.neighbors import KNeighborsClassifier
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.dummy import DummyClassifier

    return {
        "always column-exact": DummyClassifier(strategy="constant", constant=0),
        "always block-scheduled": DummyClassifier(strategy="constant", constant=1),
        "1-D threshold (tree d=1)": DecisionTreeClassifier(max_depth=1, random_state=0),
        "decision tree d=3": DecisionTreeClassifier(max_depth=3, random_state=0),
        "logistic regression": make_pipeline(StandardScaler(), LogisticRegression(max_iter=5000)),
        "kNN (k=5)": make_pipeline(StandardScaler(), KNeighborsClassifier(n_neighbors=5)),
        "random forest (300)": RandomForestClassifier(n_estimators=300, random_state=0),
        "gradient boosting": GradientBoostingClassifier(random_state=0),
    }


def lomo(rows, feats, name):
    """Leave-one-operator-out predictions. Every row of a held-out operator --
    all of its seeds and churn rates -- leaves together, so no seed of an
    operator can leak into the fold that scores it."""
    X = np.array([[d[f] for f in feats] for d in rows], float)
    y = np.array([d["y"] for d in rows])
    grp = np.array([d["matrix"] for d in rows])
    if name in CONST:
        return np.full(len(y), CONST[name], int), X, y
    pred = np.zeros(len(y), int)
    for m in sorted(set(grp)):
        te, tr = grp == m, grp != m
        if len(set(y[tr])) < 2:            # training fold is single-class
            pred[te] = y[tr][0]
            continue
        mdl = models()[name]
        mdl.fit(X[tr], y[tr])
        pred[te] = mdl.predict(X[te])
    return pred, X, y


def nested_lomo(rows, feats, verbose=False):
    """Leave-one-operator-out with the learner chosen INSIDE each training fold.

    The outer split holds one operator out. Within the remaining 20 the learner
    is chosen by an inner leave-one-operator-out on the same geomean regret, so
    the choice never sees the rows that score it. What this prices is the whole
    procedure -- "fit six learners, keep the one with the best held-out
    regret" -- on an operator it has never seen, rather than any one model.

    `best_of` below picks the learner on the scoring rows and is kept as the
    optimism diagnostic. The contrasts the paper reports use this function.
    """
    X = np.array([[d[f] for f in feats] for d in rows], float)
    y = np.array([d["y"] for d in rows])
    grp = np.array([d["matrix"] for d in rows])
    pred = np.zeros(len(y), int)
    chosen = {}
    for m in sorted(set(grp)):
        te, tr = grp == m, grp != m
        if len(set(y[tr])) < 2:
            pred[te] = y[tr][0]
            chosen[m] = "(single-class training fold)"
            continue
        tr_rows = [rows[i] for i in np.flatnonzero(tr)]
        best, best_sc = None, float("inf")
        for name in models():
            if name in CONST:
                continue
            sc = geomean(list(regret_vec(tr_rows, lomo(tr_rows, feats, name)[0])))
            if sc < best_sc:
                best, best_sc = name, sc
        chosen[m] = best
        mdl = models()[best]
        mdl.fit(X[tr], y[tr])
        pred[te] = mdl.predict(X[te])
        if verbose:
            print(f"      outer fold {m:20s} -> {best} "
                  f"(inner regret {best_sc:.4f})", flush=True)
    return pred, chosen


def insample(X, y, name):
    """Accuracy of the model fitted on every operator -- the overfitting yardstick."""
    if name in CONST:
        return float((y == CONST[name]).mean())
    if len(set(y)) < 2:                    # nothing to separate
        return 1.0
    mdl = models()[name]
    mdl.fit(X, y)
    return float((mdl.predict(X) == y).mean())


def evaluate(rows, feats, tag, scope, model, out):
    y = np.array([d["y"] for d in rows])
    degenerate = len(set(y)) < 2
    hdr = (f"{'model':28s} {'LOMO acc':>9s} {'in-samp':>8s} "
           f"{'regret':>7s} {'p90':>6s} {'worst':>6s} {'>2x':>4s}")
    print(f"\n--- feature regime: {tag}  ({', '.join(feats)}) ---")
    if degenerate:
        print("    LABEL COLLAPSE: one class only -- every model is trivially "
              "perfect here and the accuracy column carries no information.")
    print(hdr); print("-" * len(hdr))

    for name in models():
        pred, X, _ = lomo(rows, feats, name)
        acc = float((pred == y).mean())
        s = regret_stats(regret_vec(rows, pred))
        ins = insample(X, y, name)
        print(f"{name:28s} {acc:9.3f} {ins:8.3f} {s['geo']:7.3f} "
              f"{s['p90']:6.2f} {s['worst']:6.2f} {s['over2x']:4d}")
        out.append(dict(churn_model=model, scope=scope, regime=tag, model=name,
                        lomo_acc=round(acc, 4), insample_acc=round(ins, 4),
                        regret_geo=round(s["geo"], 4), regret_p90=round(s["p90"], 4),
                        regret_worst=round(s["worst"], 4), cells_over_2x=s["over2x"],
                        n_cells=len(rows), n_positive=int(y.sum()),
                        label_collapse=int(degenerate)))


def measured(rows, scope, model, out):
    """The router. It does not train, so there is no CV -- only its realised cost."""
    y = np.array([d["y"] for d in rows])
    agree = float(np.mean([d["router_arm_hst"] == d["y"] for d in rows]))
    for label, key in [("MEASURED ROUTER (steady)", "router_steady"),
                       ("MEASURED ROUTER (+calib)", "router_full")]:
        v = np.array([d[key] / d["cost_oracle"] for d in rows])
        s = regret_stats(v)
        print(f"\n{label:28s} {agree:9.3f} {'--':>8s} {s['geo']:7.3f} "
              f"{s['p90']:6.2f} {s['worst']:6.2f} {s['over2x']:4d}")
        out.append(dict(churn_model=model, scope=scope, regime="measured", model=label,
                        lomo_acc=round(agree, 4), insample_acc="",
                        regret_geo=round(s["geo"], 4), regret_p90=round(s["p90"], 4),
                        regret_worst=round(s["worst"], 4), cells_over_2x=s["over2x"],
                        n_cells=len(rows), n_positive=int(y.sum()), label_collapse=""))


# ------------------------------------------------------- paired bootstrap ---
def paired_ci(rows, a_vec, b_vec, stat, n=BOOT, seed=RNG_SEED):
    """CI for stat(a) - stat(b), resampling OPERATORS with replacement.

    Paired: one resample indexes both vectors, so the operator-to-operator
    variance that both methods share cancels instead of inflating the interval.
    Operators are the unit because that is what a new deployment draws.
    """
    rng = np.random.default_rng(seed)
    mats = np.array([d["matrix"] for d in rows])
    um = sorted(set(mats))
    idx_of = {m: np.where(mats == m)[0] for m in um}
    d = np.empty(n)
    for i in range(n):
        pick = rng.choice(um, len(um), replace=True)
        idx = np.concatenate([idx_of[m] for m in pick])
        d[i] = stat(a_vec[idx]) - stat(b_vec[idx])
    return float(d.mean()), float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5))


STATS = {
    "geomean regret": lambda a: math.exp(np.log(a).mean()),
    "worst-case regret": lambda a: float(a.max()),
    "accuracy": lambda a: float(a.mean()),
}


def contrasts(rows, scope, model, out):
    """The claims the paper rests on, each as an effect size with an interval.

    (a) does an offline STRUCTURE-only procedure tie the measured router?
    (b) is the observed drift rate the decisive variable -- i.e. does a depth-1
        tree on rho alone beat the structure-only procedure?
    (c) does the strongest hybrid -- structure PLUS the observed rho, which is
        the fairest offline competitor the data admits -- beat the router?
        (a) alone cannot answer that, and on the corrected vintage (c) is the
        contrast that most threatens the online-measurement argument.
    (d) the same, with the router charged for its own calibration.

    The offline side of all four is `nested_lomo`, not the best of six learners
    picked on the scoring rows. A review objected that picking the learner on
    the metric that then scores it inflates the contrast; the optimism that buys
    is printed beside each pair (`best_of` minus nested), and is 0.000-0.005
    against effects of 0.044-0.078. Reporting the nested number costs almost
    nothing and is what the paper quotes, so the two cannot disagree.
    """
    y = np.array([d["y"] for d in rows])
    router_arm = np.array([d["router_arm_hst"] for d in rows])
    r_regret = np.array([d["router_steady"] / d["cost_oracle"] for d in rows])

    def best_of(feats):
        """Best learner on `feats` by LOMO regret, chosen on the scoring rows.
        Diagnostic only -- this is the procedure the review objected to."""
        cands = {n: lomo(rows, feats, n)[0] for n in models() if n not in CONST}
        k = min(cands, key=lambda k: geomean(list(regret_vec(rows, cands[k]))))
        return k, cands[k], regret_vec(rows, cands[k])

    s_pred, s_chosen = nested_lomo(rows, STRUCTURE)
    b_pred, b_chosen = nested_lomo(rows, STRUCTURE + CHURN)
    s_regret, b_regret = regret_vec(rows, s_pred), regret_vec(rows, b_pred)

    # the optimism the review's objection is about, measured rather than bounded
    for feats, fname, nested_r in ((STRUCTURE, "structure", s_regret),
                                   (STRUCTURE + CHURN, "structure+rho", b_regret)):
        kb, _, br = best_of(feats)
        print(f"\n  selection optimism [{fname}]: best_of({kb}) "
              f"{geomean(list(br)):.4f} vs nested {geomean(list(nested_r)):.4f} "
              f"= {geomean(list(nested_r)) - geomean(list(br)):+.4f}")
        print(f"    learners the inner folds chose: "
              f"{sorted(set((b_chosen if feats != STRUCTURE else s_chosen).values()))}")

    # (b) the rho-only depth-1 tree. One feature, one split: there is no
    # selection to nest, which is the point of quoting it.
    rho_pred, _, _ = lomo(rows, CHURN, "1-D threshold (tree d=1)")
    rho_regret = regret_vec(rows, rho_pred)

    NEST_S, NEST_B = "nested selection [structure]", "nested selection [structure+rho]"
    pairs = [
        ("(a) nested structure-only vs measured router",
         NEST_S, s_pred, s_regret,
         "measured router (steady)", router_arm, r_regret),
        ("(b) rho-only tree d=1 vs nested structure-only",
         "1-D threshold on rho", rho_pred, rho_regret,
         NEST_S, s_pred, s_regret),
        ("(c) nested structure+rho vs measured router",
         NEST_B, b_pred, b_regret,
         "measured router (steady)", router_arm, r_regret),
        # (d) the deployment-honest version of (c). `router_steady` bills the
        # router nothing for finding out which arm is faster; `router_ms` bills
        # it for every millisecond of probing. rho, by contrast, is observable
        # for free -- it is a count of columns that changed. So (d) is the
        # comparison a deployer actually faces at this session length, and
        # (c) is the same comparison at an infinite one.
        ("(d) nested structure+rho vs measured router incl. calibration",
         NEST_B, b_pred, b_regret,
         "measured router (+calibration)", router_arm,
         np.array([d["router_full"] / d["cost_oracle"] for d in rows])),
    ]
    nops = len({d["matrix"] for d in rows})
    print("\n" + "-" * 78)
    print(f"EFFECT SIZES -- paired bootstrap over {nops} operators, "
          f"{BOOT} resamples, 95% CI")
    print("-" * 78)
    for tag, an, ap_, ar, bn, bp, br in pairs:
        print(f"\n{tag}\n  A = {an}\n  B = {bn}")
        for stat_name, fn in STATS.items():
            if stat_name == "accuracy":
                av = (ap_ == y).astype(float)
                bv = (bp == y).astype(float)
            else:
                av, bv = ar, br
            m, lo, hi = paired_ci(rows, av, bv, fn)
            sig = "  *" if not (lo <= 0 <= hi) else ""
            print(f"    {stat_name:18s} A-B = {m:+8.4f}  95% CI [{lo:+.4f}, {hi:+.4f}]{sig}")
            out.append(dict(churn_model=model, scope=scope, contrast=tag,
                            a=an, b=bn, statistic=stat_name,
                            delta=round(m, 5), ci_lo=round(lo, 5), ci_hi=round(hi, 5),
                            significant=int(not (lo <= 0 <= hi)),
                            n_cells=len(rows), n_operators=nops))


def separability(rows, model):
    """Class overlap on dens, the mechanistically motivated structural feature."""
    ch = [d for d in rows if d["rho"] > 0]
    hi = sorted(d["dens"] for d in ch if d["y"] == 1)
    lo = sorted(d["dens"] for d in ch if d["y"] == 0)
    print("\n" + "=" * 78)
    print(f"CLASS OVERLAP ON dens -- churning cells, {RD.MODEL_LABEL[model]}")
    if not hi or not lo:
        empty = "column-exact" if not lo else "block-scheduled"
        print(f"  the {empty}-better class is EMPTY: {len(hi)} block / {len(lo)} column "
              f"of {len(ch)} churning cells.")
        print("  There is no separation problem left to solve under this motion "
              "model -- the arm is decided by whether the set moves at all.")
        return
    print(f"  block-scheduled better : n={len(hi):3d}  dens {min(hi):.2f}-{max(hi):.2f}")
    print(f"  column-exact better    : n={len(lo):3d}  dens {min(lo):.2f}-{max(lo):.2f}")
    a, b = max(min(hi), min(lo)), min(max(hi), max(lo))
    inside = sum(1 for v in hi + lo if a <= v <= b)
    print(f"  overlap interval [{a:.2f}, {b:.2f}] contains {inside}/{len(ch)} cells")
    best = max(((sum(1 for v in hi if v >= t) + sum(1 for v in lo if v < t)) / len(ch), t)
               for t in sorted({d["dens"] for d in ch}))
    print(f"  best HINDSIGHT threshold: dens>={best[1]:.3f} -> {best[0]:.3f} accuracy "
          f"(fit on the test set; not achievable)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", default=list(RD.MODELS),
                    help="motion models to score, separately. cyclic is refused.")
    ap.add_argument("--out", default=os.path.join(HERE, "predictor_study.csv"))
    ap.add_argument("--boot-out", default=os.path.join(HERE, "predictor_bootstrap.csv"))
    a = ap.parse_args()

    scores, boots = [], []
    for model in a.models:
        allrows = load(model)
        print("\n" + "#" * 78)
        print(f"# MOTION MODEL: {model} ({RD.MODEL_LABEL[model]})   "
              f"source {RD.provenance(model)}")
        print(f"# {len(allrows)} cells kept, {len(RD.DROPPED[model])} dropped by the "
              f"exclusion rule (rho>0 but the set never moved)")
        print("#" * 78)
        for scope in SCOPES:
            rows = scope_rows(allrows, scope)
            y = [d["y"] for d in rows]
            print("\n" + "=" * 78)
            print(f"SCOPE: {scope}   n={len(rows)}   "
                  f"block-scheduled is the better arm in {sum(y)}/{len(y)}")
            print("=" * 78)
            for tag, feats in REGIMES.items():
                evaluate(rows, feats, tag, scope, model, scores)
            measured(rows, scope, model, scores)
            if len(set(y)) > 1:
                contrasts(rows, scope, model, boots)
            else:
                print("\n  contrasts skipped: single-class scope, every method ties "
                      "at zero regret by construction.")
        separability(allrows, model)

    with open(a.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(scores[0].keys()))
        w.writeheader(); w.writerows(scores)
    print(f"\nwrote {a.out}  ({len(scores)} rows)")
    if boots:
        with open(a.boot_out, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(boots[0].keys()))
            w.writeheader(); w.writerows(boots)
        print(f"wrote {a.boot_out}  ({len(boots)} rows)")


if __name__ == "__main__":
    main()
