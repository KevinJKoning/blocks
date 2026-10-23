"""Small statistical summaries shared by the descriptive analysis nodes."""
from math import sqrt


def survival_summary(rows):
    """Counts and a 95% Wilson binomial interval, in percent; empty groups stay unknown."""
    n = len(rows)
    survived = sum(row["Survived"] for row in rows)
    if not n:
        return {"passengers": 0, "survivors": 0, "survival_pct": None,
                "ci95_low_pct": None, "ci95_high_pct": None}
    p, z = survived / n, 1.959963984540054
    denominator = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denominator
    half = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return {"passengers": n, "survivors": survived, "survival_pct": 100 * p,
            "ci95_low_pct": 100 * (center - half), "ci95_high_pct": 100 * (center + half)}


def labelled_rows(ingest):
    """Retain observed binary outcomes; never treat a missing outcome as a death."""
    rows = ingest["table"].to_pylist()
    kept = [row for row in rows if row["Survived"] in (0, 1)]
    return kept, len(rows) - len(kept)


def display_summary(summary):
    return {"Passengers": summary["passengers"], "Survivors": summary["survivors"],
            "Survival (%)": round(summary["survival_pct"], 2) if summary["survival_pct"] is not None else None,
            "95% CI lower (%)": round(summary["ci95_low_pct"], 2) if summary["ci95_low_pct"] is not None else None,
            "95% CI upper (%)": round(summary["ci95_high_pct"], 2) if summary["ci95_high_pct"] is not None else None}
