"""Apply the fitted curve to every reading the rig recorded: what the calibration delivers.

The curve is fitted on standardized powers of the reading; here it is expanded into plain
polynomial coefficients, so that `reference ≈ c0 + c1·r + c2·r² + …` can be used anywhere
without this app. It is applied to every row of the measurements, the ones dropped as
missing or as spikes included, so the delivered file has the rig's data as it came, with
the calibrated value and its residual appended.
"""
import duckdb
import numpy as np

from blocks import ui

GROUP = "Delivery"
METRICS = {"rows": "rows calibrated"}


def calibrated(measurements, featurize, train, evaluate):
    reading, reference = np.array(duckdb.sql(f"SELECT reading, reference FROM read_parquet('{measurements}')").fetchall(), dtype=float).T
    w = np.asarray(train["coef"]) / featurize["sd"]                    # per power of the raw reading
    coef = np.concatenate([[train["intercept"] - float(w @ featurize["mu"])], w])
    value = np.polyval(coef[::-1], reading)
    return {"table": {"reading": reading, "reference": reference, "calibrated": value, "residual": value - reference},
            "coefficients": coef, "rows": len(reading),
            "quality": {"test_rmse": evaluate["test_rmse"], "test_r2": evaluate["test_r2"], "max_abs_error": evaluate["max_abs_error"]}}


def equation(coef) -> str:
    terms = [f"{coef[0]:.6g}"] + [f"{c:+.6g}·r" + (f"^{k}" if k > 1 else "") for k, c in enumerate(coef) if k]
    return "reference ≈ " + " ".join(terms).replace("+", "+ ").replace("-", "- ").replace("≈ - ", "≈ -")


def view(out):
    return [
        ui.markdown(f"The calibration curve, for a raw reading `r`:\n\n`{equation(out['coefficients'])}`\n\n"
                    f"Applied to all {out['rows']} recorded readings (rows with a missing value give no calibrated value)."),
        ui.data(out["table"], title="Calibrated readings", id="table"),
    ]


def downloads(out):
    q = out["quality"]
    report = "\n".join([
        "# Sensor calibration", "",
        "The curve that maps the low-cost sensor's raw reading `r` to the reference instrument:", "",
        f"    {equation(out['coefficients'])}", "",
        "| coefficient | value |", "|---|---|",
        *[f"| c{k} (r^{k}) | {c:.10g} |" for k, c in enumerate(out["coefficients"])], "",
        "On held-out rows the curve never saw:", "",
        f"- RMSE: {q['test_rmse']:.4g}", f"- R²: {q['test_r2']:.4g}", f"- largest error: {q['max_abs_error']:.4g}", "",
        f"Applied to {out['rows']} readings in calibrated.csv (reading, reference, calibrated, residual).", ""])
    return [ui.file("calibrated.csv", out["table"], title="every reading with its calibrated value and residual"),
            ui.file("calibration.md", report, title="the curve's equation, coefficients and quality")]
