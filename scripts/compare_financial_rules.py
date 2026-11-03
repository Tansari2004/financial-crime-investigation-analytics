"""Capacity-matched rule comparisons and date/payment-group diagnostics.

Requires features and scores from the SAME full-precision rebuilt experiment.
No rule thresholds or models are fitted using the test labels.
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from financial_crime.train_model import TRAIN_END, VALIDATION_END, evaluate, file_sha256


def compare(frame):
    labels = frame.is_laundering.to_numpy(dtype=int)
    # Amount is relative to the account's earlier same-currency average,
    # rather than comparing raw dollar/Bitcoin/etc amounts across currencies.
    amount = np.divide(frame.amount_paid.to_numpy(), frame.prior_average_amount.to_numpy(),
                       out=np.zeros(len(frame)), where=frame.prior_average_amount.to_numpy() > 0)
    scores = {"logistic": frame.review_score.to_numpy(),
              "amount_vs_prior_same_currency_average": amount,
              "prior_transaction_frequency": frame.prior_transaction_count.to_numpy()}
    return {name: evaluate(labels, values) for name, values in scores.items()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--features", type=Path, required=True)
    parser.add_argument("--scores", type=Path, required=True)
    parser.add_argument("--precision-evidence", type=Path, required=True)
    parser.add_argument("--model-metrics", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    evidence = json.loads(args.precision_evidence.read_text())
    digest = file_sha256(args.features)
    if evidence["features_sha256"] != digest:
        raise ValueError("Features do not match full-precision import evidence")
    metrics = json.loads(args.model_metrics.read_text())
    if metrics.get("features_sha256") != digest or metrics.get("scores_sha256") != file_sha256(args.scores):
        raise ValueError("Scores/metrics do not belong to these exact rebuilt features")
    scores = pd.read_csv(args.scores, float_precision="round_trip")
    if scores.transaction_id.duplicated().any():
        raise ValueError("Score IDs must be unique")
    scores = scores.set_index("transaction_id")
    parts = []
    for features in pd.read_csv(args.features, chunksize=200_000, parse_dates=["transaction_time"]):
        mask = features.transaction_time >= TRAIN_END
        selected = features.loc[mask].copy()
        if not selected.transaction_id.isin(scores.index).all():
            raise ValueError("Missing evaluation scores for feature IDs")
        matched = scores.loc[selected.transaction_id]
        expected_split = np.where(selected.transaction_time < VALIDATION_END, "validation", "test")
        if not np.array_equal(matched.data_split.to_numpy(), expected_split):
            raise ValueError("Score split does not match feature timestamps")
        selected["review_score"] = matched.review_score.to_numpy()
        parts.append(selected)
    frame = pd.concat(parts, ignore_index=True).sort_values("transaction_id", kind="stable")
    results = {"precision_import": evidence,
               "ap_definition": "Tie-aware non-interpolated average precision; regression-checked against scikit-learn",
               "capacity_ties": "Stable transaction_id source order, never truth labels; rule ties at K may affect found counts",
               "amount_rule": "Amount / earlier-days account average in the same currency; zero when no positive prior average",
               "frequency_rule": "Count of account transactions on earlier days, within the same currency",
               "evaluation_status": "Retrospective synthetic-data diagnostic; no new final holdout",
               "splits": {}, "test_slices": {}}
    for name, mask in {"validation": frame.transaction_time < VALIDATION_END,
                       "test": frame.transaction_time >= VALIDATION_END}.items():
        results["splits"][name] = compare(frame.loc[mask])
    test = frame.loc[frame.transaction_time >= VALIDATION_END].copy()
    test["date"] = test.transaction_time.dt.strftime("%Y-%m-%d")
    for field in ("date", "payment_currency", "payment_format"):
        results["test_slices"][field] = {str(value): compare(part) for value, part in test.groupby(field)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps({"output": str(args.output), "test_rows": len(test)}))


if __name__ == "__main__":
    main()
