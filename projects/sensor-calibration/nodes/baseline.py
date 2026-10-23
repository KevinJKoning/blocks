"""A straight-line fit of reference on reading: the bar the calibration curve must clear."""
import numpy as np

GROUP = "Modelling"
METRICS = {"baseline_rmse": {"label": "baseline RMSE", "goal": "min"}}


def baseline(prepare):
    train, test = prepare["train"], prepare["test"]
    slope, intercept = np.polyfit(train[:, 0], train[:, 1], 1)
    err = slope * test[:, 0] + intercept - test[:, 1]
    return {"baseline_rmse": float(np.sqrt(np.mean(err ** 2))), "slope": float(slope), "intercept": float(intercept)}
