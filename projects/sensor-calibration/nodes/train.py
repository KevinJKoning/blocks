"""Closed-form ridge regression of the reference value on the standardized features.

The intercept is the training mean and is not penalized; `alpha` shrinks the coefficients,
trading a little training fit for a curve that behaves past the calibrated range.
"""
from typing import Annotated

import numpy as np

from blocks import Note, Range

GROUP = "Modelling"
METRICS = {"train_rmse": {"label": "train RMSE", "goal": "min"}}


def train(featurize, *, alpha: Annotated[float, Range(0.0001, 10, log=True), Note("ridge penalty")] = 0.1):
    X, y = featurize["Xtr"], featurize["ytr"]
    y_mean = y.mean()
    w = np.linalg.solve(X.T @ X + alpha * np.eye(X.shape[1]), X.T @ (y - y_mean))
    pred = X @ w + y_mean
    return {"intercept": float(y_mean), "coef": w, "train_rmse": float(np.sqrt(np.mean((pred - y) ** 2)))}
