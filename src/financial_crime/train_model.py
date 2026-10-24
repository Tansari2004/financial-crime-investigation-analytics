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
EVALUATION_VERSION = "grouped_tie_ap_id_ranking_v2"


def validate_features(frame: pd.DataFrame) -> None:
    required = {"transaction_id", "transaction_time", "is_laundering",
                "amount_paid", "prior_transaction_count", "prior_average_amount",
                "same_bank", "self_transfer", "has_prior_history", "transaction_hour",
                "transaction_weekday", *CATEGORICAL_FEATURES}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"Missing feature columns: {sorted(missing)}")
    split_names(frame["transaction_time"])
    if not frame["is_laundering"].isin([0, 1]).all():
        raise ValueError("Labels must be binary 0/1")
    numeric_columns = ["transaction_id", "amount_paid", "prior_transaction_count",
                       "prior_average_amount", "same_bank", "self_transfer",
                       "has_prior_history", "transaction_hour", "transaction_weekday"]
    if not np.isfinite(frame[numeric_columns].to_numpy(dtype="float64")).all():
        raise ValueError("Numeric features must be finite")
    if (frame[["amount_paid", "prior_transaction_count", "prior_average_amount"]] < 0).any().any():
        raise ValueError("Amounts and prior counts must be nonnegative")
    ids = frame["transaction_id"].to_numpy(dtype="float64")
    if np.any(ids <= 0) or np.any(ids != np.floor(ids)) or frame.transaction_id.duplicated().any():
        raise ValueError("Transaction IDs must be positive integers, unique within a chunk")
    for column in ("same_bank", "self_transfer", "has_prior_history"):
        if not frame[column].isin([0, 1]).all():
            raise ValueError(f"{column} must be binary")
    if not frame.transaction_hour.isin(range(24)).all() or not frame.transaction_weekday.isin(range(1, 8)).all():
        raise ValueError("Hour or weekday is outside its valid range")


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
    times = pd.to_datetime(times, errors="coerce")
    if times.isna().any() or times.dt.tz is not None:
        raise ValueError("Every transaction needs a valid timezone-naive timestamp")
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
    labels, scores = validated_predictions(labels, scores)
    positives = int(labels.sum())
    if positives == 0: return 0.0
    # A threshold includes every row with the same score. Do not award a
    # favourable ordering to positives tied with negatives.
    order = np.argsort(-scores, kind="stable")
    ordered = labels[order]
    ends = np.r_[np.flatnonzero(np.diff(scores[order])), len(scores) - 1]
    true_positives = np.cumsum(ordered)[ends]
    precision = true_positives / (ends + 1)
    recall_steps = np.diff(np.r_[0, true_positives]) / positives
    return float(np.sum(recall_steps * precision))


def validated_predictions(labels, scores):
    labels, scores = np.asarray(labels), np.asarray(scores, dtype="float64")
    if labels.ndim != 1 or scores.ndim != 1 or len(labels) != len(scores) or len(labels) == 0:
        raise ValueError("Labels and scores must be nonempty matching one-dimensional arrays")
    if not np.isin(labels, [0, 1]).all():
        raise ValueError("Labels must be binary 0/1")
    if not np.isfinite(scores).all():
        raise ValueError("Scores must be finite")
    return labels, scores


def roc_auc(labels: np.ndarray, scores: np.ndarray) -> float | None:
    labels, scores = validated_predictions(labels, scores)
    positives = int(labels.sum()); negatives = len(labels) - positives
    if positives == 0 or negatives == 0: return None
    order = np.argsort(scores); sorted_scores = scores[order]; ranks = np.empty(len(scores))
    start = 0
    while start < len(scores):
        end = start + 1
        while end < len(scores) and sorted_scores[end] == sorted_scores[start]: end += 1
        ranks[order[start:end]] = (start + 1 + end) / 2; start = end
    return float((ranks[labels == 1].sum() - positives * (positives + 1) / 2) / (positives * negatives))


def ranking_at_k(labels: np.ndarray, scores: np.ndarray, k: int, transaction_ids=None) -> dict:
    labels, scores = validated_predictions(labels, scores)
    if k <= 0:
        raise ValueError("k must be positive")
    ids = np.arange(len(labels)) if transaction_ids is None else np.asarray(transaction_ids)
    if ids.shape != labels.shape or len(np.unique(ids)) != len(ids):
        raise ValueError("Ranking IDs must be unique and match labels")
    actual_k = min(k, len(labels)); chosen = np.lexsort((ids, -scores))[:actual_k]
    found = int(labels[chosen].sum()); total = int(labels.sum())
    return {"k": actual_k, "positives_found": found, "precision": found / actual_k,
            "recall": found / total if total else 0.0}


def evaluate(labels: np.ndarray, scores: np.ndarray, transaction_ids=None) -> dict:
    labels, scores = validated_predictions(labels, scores)
    if np.any((scores < 0) | (scores > 1)):
        raise ValueError("Review scores must be between 0 and 1")
    predictions = scores >= 0.5
    tp = int((predictions & (labels == 1)).sum()); fp = int((predictions & (labels == 0)).sum())
    tn = int(((~predictions) & (labels == 0)).sum()); fn = int(((~predictions) & (labels == 1)).sum())
    return {"rows": int(len(labels)), "positives": int(labels.sum()),
            "prevalence": float(labels.mean()), "pr_auc": average_precision(labels, scores),
            "roc_auc": roc_auc(labels, scores),
            "precision_at_0_5": tp / (tp + fp) if tp + fp else 0.0,
            "recall_at_0_5": tp / (tp + fn) if tp + fn else 0.0,
            "confusion_matrix_at_0_5": [[tn, fp], [fn, tp]],
            "ranking": [ranking_at_k(labels, scores, k, transaction_ids) for k in (100, 500, 1000, 5000)]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--features", type=Path, default=Path("data/processed/model_features.csv"))
    parser.add_argument("--scores", type=Path, default=Path("data/processed/model_scores.csv"))
    parser.add_argument("--model", type=Path, default=Path("models/numpy_logistic_v1.npz"))
    parser.add_argument("--metrics", type=Path, default=Path("reports/model_metrics.json"))
    parser.add_argument("--chunk-size", type=int, default=200_000)
    parser.add_argument("--epochs", type=int, default=3)
    args = parser.parse_args()
    if args.chunk_size <= 0 or args.epochs <= 0:
        parser.error("--chunk-size and --epochs must be positive")
    if args.features.resolve() in {args.scores.resolve(), args.model.resolve(), args.metrics.resolve()}:
        parser.error("Output paths must not overwrite the input features")
    if len({args.scores.resolve(), args.model.resolve(), args.metrics.resolve()}) != 3:
        parser.error("Score, model and metric outputs need distinct paths")

    total = np.zeros(len(NUMERIC_FEATURES)); square_total = np.zeros(len(NUMERIC_FEATURES))
    categories = {column: set() for column in CATEGORICAL_FEATURES}; train_rows = train_positives = 0
    split_counts = {name: 0 for name in ("train", "validation", "test")}
    for chunk in pd.read_csv(args.features, chunksize=args.chunk_size, parse_dates=["transaction_time"]):
        validate_features(chunk)
        names = split_names(chunk["transaction_time"])
        for name in split_counts:
            split_counts[name] += int(np.sum(names == name))
        train = chunk.loc[chunk["transaction_time"] < TRAIN_END]
        if train.empty: continue
        matrix = numeric_matrix(train); total += matrix.sum(axis=0); square_total += np.square(matrix).sum(axis=0)
        train_rows += len(train); train_positives += int(train["is_laundering"].sum())
        for column in CATEGORICAL_FEATURES:
            categories[column].update(train[column].fillna("UNKNOWN").astype(str).unique())
    if not all(split_counts.values()) or not 0 < train_positives < train_rows:
        raise ValueError("Need nonempty train/validation/test splits and both training classes")
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
    collected_ids = {"validation": [], "test": []}
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
            if mask.any():
                collected_labels[name].append(labels[mask]); collected_scores[name].append(scores[mask])
                collected_ids[name].append(chunk.loc[mask, "transaction_id"].to_numpy(dtype="int64"))

    feature_names = list(NUMERIC_FEATURES)
    for column in CATEGORICAL_FEATURES:
        feature_names += [f"{column}={value}" for value in category_maps[column]] + [f"{column}=UNKNOWN"]
    coefficients = sorted(zip(feature_names, weights, strict=True), key=lambda pair: pair[1])
    metrics = {"model_version": MODEL_VERSION,
               "evaluation_version": EVALUATION_VERSION,
               "ranking_tie_policy": "review_score descending, transaction_id ascending",
               "model_type": "logistic regression implemented with NumPy mini-batch gradient descent",
               "score_warning": "Class weighting changes calibration; review_score is a ranking score, not a crime probability.",
               "split": {"train": "before 2022-09-08", "validation": "2022-09-08", "test": "2022-09-09 onward"},
               "train": {"rows": train_rows, "positives": train_positives}}
    for name in ("validation", "test"):
        metrics[name] = evaluate(np.concatenate(collected_labels[name]), np.concatenate(collected_scores[name]),
                                 np.concatenate(collected_ids[name]))
    metrics["largest_negative_coefficients"] = [[n, float(v)] for n, v in coefficients[:8]]
    metrics["largest_positive_coefficients"] = [[n, float(v)] for n, v in coefficients[-8:][::-1]]
    args.model.parent.mkdir(parents=True, exist_ok=True); args.metrics.parent.mkdir(parents=True, exist_ok=True)
    np.savez(args.model, weights=weights, bias=bias, mean=mean, scale=scale,
             feature_names=np.array(feature_names), model_version=MODEL_VERSION)
    args.metrics.write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
