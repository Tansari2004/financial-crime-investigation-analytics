"""Train and evaluate a chronological transaction-level logistic baseline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

NUMERIC_FEATURES = [
    "log_amount_paid", "log_prior_transaction_count", "log_prior_average_amount",
    "log_amount_to_prior_average", "same_bank", "self_transfer",
    "has_prior_history", "hour_sin", "hour_cos", "weekday_sin", "weekday_cos",
]
CATEGORICAL_FEATURES = ["payment_currency", "receiving_currency", "payment_format"]
TRAIN_END = pd.Timestamp("2022-09-08")
VALIDATION_END = pd.Timestamp("2022-09-09")
MODEL_VERSION = "numpy_logistic_v1"


def numeric_matrix(frame: pd.DataFrame) -> np.ndarray:
    amount = frame["amount_paid"].clip(lower=0).to_numpy(dtype="float64")
    prior_count = frame["prior_transaction_count"].clip(lower=0).to_numpy(dtype="float64")
    prior_average = frame["prior_average_amount"].clip(lower=0).to_numpy(dtype="float64")
    ratio = np.divide(amount, prior_average, out=np.zeros_like(amount), where=prior_average > 0)
    hour = frame["transaction_hour"].to_numpy(dtype="float64")
    weekday = frame["transaction_weekday"].to_numpy(dtype="float64")
    return np.column_stack([
        np.log1p(amount), np.log1p(prior_count), np.log1p(prior_average),
        np.log1p(np.clip(ratio, 0, 1e9)), frame["same_bank"], frame["self_transfer"],
        frame["has_prior_history"], np.sin(2 * np.pi * hour / 24),
        np.cos(2 * np.pi * hour / 24), np.sin(2 * np.pi * (weekday - 1) / 7),
        np.cos(2 * np.pi * (weekday - 1) / 7),
    ]).astype("float64")


def split_names(times: pd.Series) -> np.ndarray:
    names = np.full(len(times), "test", dtype=object)
    names[times < VALIDATION_END] = "validation"
    names[times < TRAIN_END] = "train"
    return names


def design_matrix(frame, mean, scale, category_maps) -> np.ndarray:
    numeric = (numeric_matrix(frame) - mean) / scale
    width = len(NUMERIC_FEATURES) + sum(len(values) + 1 for values in category_maps.values())
    result = np.zeros((len(frame), width), dtype="float32")
    result[:, :len(NUMERIC_FEATURES)] = numeric
    offset = len(NUMERIC_FEATURES); rows = np.arange(len(frame))
    for column in CATEGORICAL_FEATURES:
        mapping = category_maps[column]; unknown = len(mapping)
        codes = frame[column].fillna("UNKNOWN").astype(str).map(mapping).fillna(unknown).astype(int).to_numpy()
        result[rows, offset + codes] = 1.0; offset += len(mapping) + 1
    return result


def sigmoid(values: np.ndarray) -> np.ndarray:
    values = np.clip(values, -30, 30)
    return 1.0 / (1.0 + np.exp(-values))


def average_precision(labels: np.ndarray, scores: np.ndarray) -> float:
    positives = int(labels.sum())
    if positives == 0: return 0.0
    ordered = labels[np.argsort(scores)[::-1]]
    precision = np.cumsum(ordered) / np.arange(1, len(ordered) + 1)
    return float(precision[ordered == 1].sum() / positives)


def roc_auc(labels: np.ndarray, scores: np.ndarray) -> float:
    positives = int(labels.sum()); negatives = len(labels) - positives
    if positives == 0 or negatives == 0: return 0.0
    order = np.argsort(scores); sorted_scores = scores[order]; ranks = np.empty(len(scores))
    start = 0
    while start < len(scores):
        end = start + 1
        while end < len(scores) and sorted_scores[end] == sorted_scores[start]: end += 1
        ranks[order[start:end]] = (start + 1 + end) / 2; start = end
    return float((ranks[labels == 1].sum() - positives * (positives + 1) / 2) / (positives * negatives))


def ranking_at_k(labels: np.ndarray, scores: np.ndarray, k: int) -> dict:
    actual_k = min(k, len(labels)); chosen = np.argsort(scores)[::-1][:actual_k]
    found = int(labels[chosen].sum()); total = int(labels.sum())
    return {"k": actual_k, "positives_found": found, "precision": found / actual_k,
            "recall": found / total if total else 0.0}


def evaluate(labels: np.ndarray, scores: np.ndarray) -> dict:
    predictions = scores >= 0.5
    tp = int((predictions & (labels == 1)).sum()); fp = int((predictions & (labels == 0)).sum())
    tn = int(((~predictions) & (labels == 0)).sum()); fn = int(((~predictions) & (labels == 1)).sum())
    return {"rows": int(len(labels)), "positives": int(labels.sum()),
            "prevalence": float(labels.mean()), "pr_auc": average_precision(labels, scores),
            "roc_auc": roc_auc(labels, scores),
            "precision_at_0_5": tp / (tp + fp) if tp + fp else 0.0,
            "recall_at_0_5": tp / (tp + fn) if tp + fn else 0.0,
            "confusion_matrix_at_0_5": [[tn, fp], [fn, tp]],
            "ranking": [ranking_at_k(labels, scores, k) for k in (100, 500, 1000, 5000)]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--features", type=Path, default=Path("data/processed/model_features.csv"))
    parser.add_argument("--scores", type=Path, default=Path("data/processed/model_scores.csv"))
    parser.add_argument("--model", type=Path, default=Path("models/numpy_logistic_v1.npz"))
    parser.add_argument("--metrics", type=Path, default=Path("reports/model_metrics.json"))
    parser.add_argument("--chunk-size", type=int, default=200_000)
    parser.add_argument("--epochs", type=int, default=3)
    args = parser.parse_args()

    total = np.zeros(len(NUMERIC_FEATURES)); square_total = np.zeros(len(NUMERIC_FEATURES))
    categories = {column: set() for column in CATEGORICAL_FEATURES}; train_rows = train_positives = 0
    for chunk in pd.read_csv(args.features, chunksize=args.chunk_size, parse_dates=["transaction_time"]):
        train = chunk.loc[chunk["transaction_time"] < TRAIN_END]
        if train.empty: continue
        matrix = numeric_matrix(train); total += matrix.sum(axis=0); square_total += np.square(matrix).sum(axis=0)
        train_rows += len(train); train_positives += int(train["is_laundering"].sum())
        for column in CATEGORICAL_FEATURES:
            categories[column].update(train[column].fillna("UNKNOWN").astype(str).unique())
    mean = total / train_rows
    scale = np.sqrt(np.maximum(square_total / train_rows - np.square(mean), 1e-12))
    category_maps = {column: {value: i for i, value in enumerate(sorted(values))}
                     for column, values in categories.items()}

    width = len(NUMERIC_FEATURES) + sum(len(values) + 1 for values in category_maps.values())
    weights = np.zeros(width); bias = 0.0; gradient_square = np.full(width, 1e-8); bias_square = 1e-8
    negative_count = train_rows - train_positives
    class_weight = {0: train_rows / (2 * negative_count), 1: train_rows / (2 * train_positives)}
    for _ in range(args.epochs):
        for chunk in pd.read_csv(args.features, chunksize=args.chunk_size, parse_dates=["transaction_time"]):
            train = chunk.loc[chunk["transaction_time"] < TRAIN_END]
            if train.empty: continue
            x = design_matrix(train, mean, scale, category_maps).astype("float64")
            y = train["is_laundering"].to_numpy(dtype="float64")
            row_weight = np.where(y == 1, class_weight[1], class_weight[0])
            error = (sigmoid(x @ weights + bias) - y) * row_weight
            gradient = x.T @ error / len(x) + 1e-5 * weights; bias_gradient = float(error.mean())
            gradient_square += np.square(gradient); bias_square += bias_gradient ** 2
            weights -= 0.15 * gradient / np.sqrt(gradient_square); bias -= 0.15 * bias_gradient / np.sqrt(bias_square)

    args.scores.parent.mkdir(parents=True, exist_ok=True)
    collected_labels = {"validation": [], "test": []}; collected_scores = {"validation": [], "test": []}
    wrote_header = False
    for chunk in pd.read_csv(args.features, chunksize=args.chunk_size, parse_dates=["transaction_time"]):
        scores = sigmoid(design_matrix(chunk, mean, scale, category_maps) @ weights + bias)
        names = split_names(chunk["transaction_time"])
        pd.DataFrame({"transaction_id": chunk["transaction_id"].astype("int64"), "review_score": scores,
                      "data_split": names, "model_version": MODEL_VERSION}).to_csv(
            args.scores, mode="w" if not wrote_header else "a", header=not wrote_header, index=False)
        wrote_header = True; labels = chunk["is_laundering"].to_numpy(dtype="int8")
        for name in ("validation", "test"):
            mask = names == name
            if mask.any(): collected_labels[name].append(labels[mask]); collected_scores[name].append(scores[mask])

    feature_names = list(NUMERIC_FEATURES)
    for column in CATEGORICAL_FEATURES:
        feature_names += [f"{column}={value}" for value in category_maps[column]] + [f"{column}=UNKNOWN"]
    coefficients = sorted(zip(feature_names, weights, strict=True), key=lambda pair: pair[1])
    metrics = {"model_version": MODEL_VERSION,
               "model_type": "logistic regression implemented with NumPy mini-batch gradient descent",
               "score_warning": "Class weighting changes calibration; review_score is a ranking score, not a crime probability.",
               "split": {"train": "before 2022-09-08", "validation": "2022-09-08", "test": "2022-09-09 onward"},
               "train": {"rows": train_rows, "positives": train_positives}}
    for name in ("validation", "test"):
        metrics[name] = evaluate(np.concatenate(collected_labels[name]), np.concatenate(collected_scores[name]))
    metrics["largest_negative_coefficients"] = [[n, float(v)] for n, v in coefficients[:8]]
    metrics["largest_positive_coefficients"] = [[n, float(v)] for n, v in coefficients[-8:][::-1]]
    args.model.parent.mkdir(parents=True, exist_ok=True); args.metrics.parent.mkdir(parents=True, exist_ok=True)
    np.savez(args.model, weights=weights, bias=bias, mean=mean, scale=scale,
             feature_names=np.array(feature_names), model_version=MODEL_VERSION)
    args.metrics.write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
