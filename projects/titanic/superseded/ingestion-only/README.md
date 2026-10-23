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
Every row is retained, with blank cells represented as nulls. No survival model
has been created yet.
