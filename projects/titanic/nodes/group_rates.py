"""2. Compare survival rates by sex and passenger class.

Break the labelled passengers into groups and show survivors, denominators,
survival percentages, and 95% Wilson intervals. The sex-by-class table shows
how the two characteristics overlap. Each table is a separate partition of the
same population; do not add counts across tables.

These are descriptive, unadjusted associations. A difference between groups
does not establish that changing a characteristic would cause survival to change.
"""
from blocks import ui
from analysis_helpers import display_summary, labelled_rows, survival_summary

METRICS = {"passengers": "Passengers analysed", "n_excluded": "Missing or invalid outcomes excluded"}


def group_rates(ingest):
    rows, excluded = labelled_rows(ingest)
    if not rows:
        raise ValueError("No passengers have a known binary survival outcome.")
    def label(value):
        return "Unknown" if value is None or value == "" else str(value)

    tables = {}
    for title, fields in (("By sex", ["Sex"]), ("By passenger class", ["Pclass"]),
                          ("By sex and class", ["Sex", "Pclass"])):
        buckets = {}
        for row in rows:
            key = tuple(label(row[field]) for field in fields)
            buckets.setdefault(key, []).append(row)
        tables[title] = [{**dict(zip(fields, key)), **survival_summary(buckets[key])}
                         for key in sorted(buckets)]
    return {"passengers": len(rows), "n_excluded": excluded, "tables": tables}


def view(out):
    blocks = [ui.metrics(), ui.markdown("Rates use each group's own passenger count as the denominator. "
              "Missing group labels remain visible as Unknown. Class 1 is first class; class 3 is third class.", id="method")]
    for title, rows in out["tables"].items():
        shown = [{**{k: v for k, v in row.items() if k in ("Sex", "Pclass")}, **display_summary(row)} for row in rows]
        blocks.append(ui.table(shown, title=f"{title} · survival and 95% Wilson intervals",
                               id={"By sex": "sex", "By passenger class": "class", "By sex and class": "sex_class"}[title]))
    blocks.append(ui.markdown("Intervals assume independent binomial observations. Small groups are less precise; "
                  "selection and family dependence are not accounted for. These comparisons do not adjust for age "
                  "or other differences between passengers and do not establish causation.", id="limitations"))
    return blocks
