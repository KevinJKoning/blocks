"""3. Model survival with sex, passenger class, and age together.

A binomial logistic regression models the log-odds of `Survived = 1` using sex,
class as two categorical indicators (first class is the reference), and age per
10 years. All three characteristics enter together; age has a linear relationship
with log-odds and no interactions are fitted.

Use complete cases: exclude missing/invalid outcomes, unknown sex or class, and
missing/non-finite or negative age. No values are imputed. This is an explanatory
fit to the observed sample, not a held-out prediction evaluation or a causal model.
"""
import numpy as np
import statsmodels.api as sm

from blocks import ui
from analysis_helpers import labelled_rows

METRICS = {
    "n_used": "Passengers fitted",
    "n_excluded": "Passengers excluded (all reasons)",
    "n_survivors": "Survivors in fitted sample",
    "iterations": "Fitting iterations",
}


def logistic(ingest):
    labelled, invalid_target = labelled_rows(ingest)
    rows = [r for r in labelled if r["Sex"] in ("male", "female") and r["Pclass"] in (1, 2, 3)
            and r["Age"] is not None and np.isfinite(r["Age"]) and r["Age"] >= 0]
    n = len(rows)
    if n <= 5:
        raise ValueError("Need more than five complete passenger records for this model.")
    y = np.array([r["Survived"] for r in rows], dtype=float)
    if len(np.unique(y)) != 2:
        raise ValueError("Both survival outcomes must be present in the complete-case sample.")
    X = np.array([[1, r["Sex"] == "female", r["Pclass"] == 2, r["Pclass"] == 3, r["Age"] / 10]
                  for r in rows], dtype=float)
    if np.linalg.matrix_rank(X) != X.shape[1]:
        raise ValueError("Predictors are not independently estimable in this sample.")
    result = sm.GLM(y, X, family=sm.families.Binomial()).fit(maxiter=100, tol=1e-10)
    if not result.converged or not np.isfinite(result.params).all() or not np.isfinite(result.bse).all():
        raise ValueError("Logistic fit did not converge to finite estimates.")
    intervals = result.conf_int(alpha=0.05)
    terms = ["Female vs male", "Second vs first class", "Third vs first class", "Age: +10 years"]
    effects = [{"term": term, "odds_ratio": float(np.exp(result.params[i])),
                "ci95_low": float(np.exp(intervals[i, 0])), "ci95_high": float(np.exp(intervals[i, 1]))}
               for i, term in enumerate(terms, start=1)]
    return {"n_used": n, "n_excluded": ingest["n_passengers"] - n,
            "n_invalid_target": invalid_target, "n_incomplete_predictors": len(labelled) - n,
            "n_survivors": int(y.sum()), "iterations": int(result.fit_history["iteration"]),
            "effects": effects, "coefficients": result.params.tolist(),
            "passenger_ids": [r["PassengerId"] for r in rows],
            "log_likelihood": float(result.llf), "converged": bool(result.converged)}


def view(out):
    effects = [{"Comparison (other predictors held fixed)": r["term"],
                "Odds ratio": round(r["odds_ratio"], 3),
                "95% CI lower": round(r["ci95_low"], 3),
                "95% CI upper": round(r["ci95_high"], 3)} for r in out["effects"]]
    return [
        ui.metrics(),
        ui.markdown(f"Fitted to **{out['n_used']} passengers**, including {out['n_survivors']} survivors. "
                    f"Excluded {out['n_invalid_target']} missing/invalid outcomes and "
                    f"{out['n_incomplete_predictors']} labelled passengers with incomplete/invalid predictors. "
                    "The descriptive branches use a larger population when age is missing.", id="sample"),
        ui.table(effects, title="Adjusted odds ratios · 95% Wald confidence intervals", id="effects"),
        ui.markdown("An odds ratio above 1 means higher fitted survival odds; below 1 means lower odds, "
                    "holding the model's other predictors fixed. For example, 2 means twice the odds, "
                    "not twice the probability. First class and male are the reference categories. "
                    "Intervals spanning 1 are compatible with no association under this model.", id="interpretation"),
        ui.markdown("These are associations, not causal effects. Complete-case selection can bias estimates; "
                    "the model omits other characteristics and assumes independent passengers, linear age "
                    "effects on log-odds, and no interactions. The intervals are approximate model-based "
                    "uncertainty. No test set was used, so this does not measure prediction performance.", id="limitations"),
    ]
