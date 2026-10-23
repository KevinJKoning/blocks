"""Clean the rig's raw readings and split them into training and held-out rows.

Rows with a missing value are dropped. Connector spikes are screened against a robust cubic
trend: a row whose residual exceeds `outlier_z` MAD-scaled standard deviations is removed.
What is left is split at random (`seed`) into training rows and a held-out
`test_fraction`, on which the curve is later scored.
"""
from typing import Annotated

import duckdb
import numpy as np

from blocks import Note, Range, ui

GROUP = "Data preparation"
SCHEMA = {
    "measurements": {"fields": [
        {"name": "reading", "type": "number", "constraints": {"minimum": 0, "maximum": 12},
         "description": "Raw reading of the low-cost sensor (0–10 on the calibrated range)."},
        {"name": "reference", "type": "number", "description": "The reference instrument's value for the same sample."},
    ]},
}
METRICS = {
    "n_raw": "rows read",
    "n_train": "train rows",
    "n_outliers": {"label": "outliers dropped", "goal": "min"},
}


def prepare(measurements, *,
            test_fraction: Annotated[float, Range(0.1, 0.5, 0.05)] = 0.25,
            seed: int = 42,
            outlier_z: Annotated[float, Range(1.5, 6, 0.5), Note("robust z cut for spikes")] = 3.0):
    # DuckDB reads the Parquet file in place (it is mounted read-only, never copied).
    data = np.array(duckdb.sql(f"SELECT reading, reference FROM read_parquet('{measurements}')").fetchall(), dtype=float)
    n_raw = len(data)
    data = data[~np.isnan(data).any(axis=1)]
    x, y = data[:, 0], data[:, 1]
    resid = y - np.polyval(np.polyfit(x, y, 3), x)
    mad = np.median(np.abs(resid - np.median(resid))) * 1.4826
    keep = np.abs(resid - np.median(resid)) <= outlier_z * max(mad, 1e-12)
    kept = data[keep]
    idx = np.random.default_rng(seed).permutation(len(kept))
    n_test = int(round(len(kept) * test_fraction))
    test, train = kept[idx[:n_test]], kept[idx[n_test:]]
    return {"train": train, "test": test, "screen": {"x": x, "y": y, "keep": keep},
            "n_raw": n_raw, "n_missing": n_raw - len(data), "n_outliers": int((~keep).sum()),
            "n_train": len(train), "n_test": len(test)}


def view(out):
    s = out["screen"]
    return [
        ui.metrics(),
        ui.markdown(f"Of {out['n_raw']} readings, {out['n_missing']} had a missing value and {out['n_outliers']} were "
                    f"screened out as spikes; {out['n_train']} train the curve and {out['n_test']} are held out."),
        ui.chart(s["x"], {"kept": np.where(s["keep"], s["y"], np.nan), "screened out": np.where(s["keep"], np.nan, s["y"])},
                 kind="scatter", title="Readings against the reference", x_label="reading", y_label="reference", id="screen"),
        ui.data({"reading": out["train"][:, 0], "reference": out["train"][:, 1]}, title="Training rows", id="train"),
    ]
