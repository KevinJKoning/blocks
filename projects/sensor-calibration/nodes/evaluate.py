"""Score the calibration curve on held-out rows it never saw.

RMSE and R² of the reference value predicted from the reading, the worst single error, and
RMSE relative to the straight-line baseline (below 1 means the curve earns its keep).
"""
import numpy as np

from blocks import ui

GROUP = "Modelling"
METRICS = {
    "test_rmse": {"label": "RMSE", "goal": "min", "headline": True},
    "test_r2": {"label": "R²", "goal": "max", "headline": True},
    "max_abs_error": {"label": "max error", "goal": "min", "headline": True},
    "rmse_vs_baseline": {"label": "RMSE vs baseline", "goal": "min"},
}


def evaluate(train, featurize, baseline):
    pred = featurize["Xte"] @ train["coef"] + train["intercept"]
    y, x = featurize["yte"], featurize["xte"]
    err = pred - y
    rmse = float(np.sqrt(np.mean(err ** 2)))
    order = np.argsort(x)
    return {"test_rmse": rmse, "rmse_vs_baseline": rmse / baseline["baseline_rmse"],
            "test_r2": 1.0 - float(np.sum(err ** 2)) / float(np.sum((y - y.mean()) ** 2)),
            "max_abs_error": float(np.max(np.abs(err))),
            "reading": x[order], "reference": y[order], "predicted": pred[order], "residual": err[order]}


def view(out):
    worst = int(np.argmax(np.abs(out["residual"])))
    return [
        ui.metrics(),
        ui.markdown(f"{len(out['reading'])} held-out readings. The worst is off by {abs(out['residual'][worst]):.2f} at "
                    f"reading {out['reading'][worst]:.2f}; RMSE is {out['rmse_vs_baseline']:.0%} of the straight line's."),
        ui.chart(out["reading"], {"reference": out["reference"], "predicted": out["predicted"]},
                 kind={"reference": "scatter", "predicted": "line"}, title="Calibration curve on held-out rows",
                 x_label="reading", id="curve"),
        ui.chart(out["reading"], {"residual": out["residual"]}, kind="scatter", title="Residuals on held-out rows",
                 x_label="reading", id="residuals"),
    ]
