"""Expand the reading into polynomial features, standardized on the training rows.

Each power of the reading up to `degree` is a feature; every feature is centred and scaled
by its mean and standard deviation over the training rows only, so the held-out rows are
transformed exactly as new readings would be.
"""
from typing import Annotated

import numpy as np

from blocks import Range

GROUP = "Data preparation"
METRICS = {"n_features": "features", "condition_number": {"label": "condition number", "goal": "min"}}


def featurize(prepare, *, degree: Annotated[int, Range(1, 8, 1)] = 3):
    train, test = prepare["train"], prepare["test"]

    def poly(x):
        return np.column_stack([x ** k for k in range(1, degree + 1)])

    Xtr, Xte = poly(train[:, 0]), poly(test[:, 0])
    mu, sd = Xtr.mean(axis=0), Xtr.std(axis=0)
    sd[sd == 0] = 1.0
    Xtr, Xte = (Xtr - mu) / sd, (Xte - mu) / sd
    return {"Xtr": Xtr, "ytr": train[:, 1], "Xte": Xte, "yte": test[:, 1], "xtr": train[:, 0], "xte": test[:, 0],
            "mu": mu, "sd": sd, "n_features": degree, "condition_number": float(np.linalg.cond(Xtr))}
