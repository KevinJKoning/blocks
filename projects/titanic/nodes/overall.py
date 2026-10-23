"""1. Count survival outcomes: the simplest starting point.

Survival is `Survived = 1`; `0` means died. Divide the number of survivors by
the number of passengers with a known binary outcome. No predictor is needed,
so missing age, cabin, or embarkation port does not remove a passenger.
"""
from blocks import ui
from analysis_helpers import display_summary, labelled_rows, survival_summary

METRICS = {
    "passengers": "Passengers with known outcome",
    "survivors": "Survivors",
    "survival_pct": "Observed survival (%)",
    "n_excluded": "Missing or invalid outcomes excluded",
}


def overall(ingest):
    rows, excluded = labelled_rows(ingest)
    if not rows:
        raise ValueError("No passengers have a known binary survival outcome.")
    return {**survival_summary(rows), "deaths": len(rows) - sum(row["Survived"] for row in rows),
            "n_excluded": excluded}


def view(out):
    return [
        ui.metrics(),
        ui.markdown(f"**{out['survivors']} of {out['passengers']} passengers survived "
                    f"({out['survival_pct']:.1f}%).** The other {out['deaths']} died. "
                    f"{out['n_excluded']} records excluded for missing or invalid outcomes.", id="answer"),
        ui.table([display_summary(out)], title="Overall survival and 95% Wilson interval", id="interval"),
        ui.markdown("The percentage describes this dataset exactly. The interval expresses binomial sampling "
                    "uncertainty under an independent-sampling assumption; it does not correct for this dataset's "
                    "selection or dependence between travelling companions. This is not an estimate for the full ship manifest.", id="limitations"),
    ]
