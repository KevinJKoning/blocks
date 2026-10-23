# Titanic survival

Starting point for a collaborative machine learning analysis.

## Data

`data/titanic.csv` was downloaded on 2026-10-23 from the
[Data Science Dojo public mirror](https://github.com/datasciencedojo/datasets/blob/master/titanic.csv).
The original downloaded CSV is retained unchanged.

This is the familiar 891-passenger labelled training dataset, with 12 columns:
PassengerId, Survived, Pclass, Name, Sex, Age, SibSp, Parch, Ticket, Fare, Cabin,
and Embarked. Survived is the prediction target (0 = died, 1 = survived).
It is a subset of passengers, not a complete manifest. Age, Cabin, and Embarked
contain missing values; we will decide how to handle them when building the analysis.

## Project status

The dataset is registered as `passengers` in `app.yaml`. The `ingest` node loads it
into a PyArrow table in the browser and shows a preview and missing-value counts.
Every row is retained, with blank cells represented as nulls.

Three independent branches read `ingest`, using `Survived` as the binary target:

1. `overall`: survivor counts, survival percentage, and a 95% Wilson interval.
2. `group_rates`: the same summaries by sex, class, and their combinations.
3. `logistic`: binomial logistic regression on sex, categorical class, and age per
   decade, with adjusted odds ratios and 95% Wald intervals. This branch uses
   complete cases and displays all exclusions. No imputation or test split is used.

The analyses describe associations within this subset of passengers. They do not
establish causation or held-out predictive performance. Confidence intervals assume
independent observations and do not account for family/travel-group dependence or
selection into this dataset.

The ingestion-only version and its baseline are preserved in
`superseded/ingestion-only/` and shipped for comparison.
