"""Explain the model score for a dashboard-sized investigation queue.

Contributions exactly reconstruct the logistic model's pre-sigmoid score.
They are associations in synthetic training data, not causal explanations.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from financial_crime.train_model import (
    CATEGORICAL_FEATURES,
    NUMERIC_FEATURES,
    design_matrix,
    sigmoid,
)

GROUPS = {
    "hour_sin": "Time of day",
    "hour_cos": "Time of day",
    "weekday_sin": "Day of week",
    "weekday_cos": "Day of week",
}


def model_components(model: np.lib.npyio.NpzFile) -> tuple[list[str], dict[str, dict[str, int]]]:
    names = [str(value) for value in model["feature_names"]]
    if names[: len(NUMERIC_FEATURES)] != NUMERIC_FEATURES:
        raise ValueError("Saved model feature order does not match the scoring code")
    category_maps: dict[str, dict[str, int]] = {}
    for column in CATEGORICAL_FEATURES:
        values = [name[len(column) + 1 :] for name in names if name.startswith(f"{column}=")]
        if not values or values[-1] != "UNKNOWN":
            raise ValueError(f"Saved model is missing the {column} unknown category")
        category_maps[column] = {value: index for index, value in enumerate(values[:-1])}
    return names, category_maps


def factor_text(name: str, row: pd.Series) -> str:
    if name == "log_amount_paid":
        return f"Payment amount: {row.amount_paid:,.2f} {row.payment_currency}"
    if name == "log_prior_transaction_count":
        return f"Earlier sender payments: {int(row.prior_transaction_count)}"
    if name == "log_prior_average_amount":
        return f"Earlier average payment: {row.prior_average_amount:,.2f} {row.payment_currency}"
    if name == "log_amount_to_prior_average":
        if row.prior_average_amount > 0:
            return f"Amount versus earlier average: {row.amount_paid / row.prior_average_amount:,.1f}x"
        return "No earlier average payment available"
    if name == "same_bank":
        return f"Same bank: {'yes' if row.same_bank else 'no'}"
    if name == "self_transfer":
        return f"Same sender and receiver: {'yes' if row.self_transfer else 'no'}"
    if name == "has_prior_history":
        return f"Earlier sender history: {'yes' if row.has_prior_history else 'no'}"
    if name == "Time of day":
        return f"Time of day: {int(row.transaction_hour):02d}:00 hour"
    if name == "Day of week":
        weekday = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
        return f"Day of week: {weekday[int(row.transaction_weekday) - 1]}"
    if "=" in name:
        column, value = name.split("=", 1)
        return f"{column.replace('_', ' ').capitalize()}: {value}"
    return name.replace("_", " ").capitalize()


def grouped_contributions(names: list[str], contributions: np.ndarray) -> dict[str, float]:
    grouped: dict[str, float] = {}
    for name, value in zip(names, contributions, strict=True):
        if "=" in name and value == 0:
            continue
        key = GROUPS.get(name, name)
        grouped[key] = grouped.get(key, 0.0) + float(value)
    return grouped


def explain(frame: pd.DataFrame, model: np.lib.npyio.NpzFile) -> pd.DataFrame:
    names, category_maps = model_components(model)
    x = design_matrix(frame, model["mean"], model["scale"], category_maps)
    weights = model["weights"]
    contributions = x * weights
    reconstructed = sigmoid(contributions.sum(axis=1) + float(model["bias"]))
    gap = np.abs(reconstructed - frame["review_score"].to_numpy(dtype="float64"))
    if np.max(gap) > 1e-5:
        raise ValueError(f"Explanations do not reconstruct saved scores; max difference {np.max(gap):.6g}")

    output = frame.copy()
    output["score_reconstruction_gap"] = gap
    for slot in (1, 2, 3):
        output[f"model_reason_{slot}"] = ""
        output[f"reason_{slot}_effect"] = 0.0
    reasons = []
    effects = []
    for (_, row), vector in zip(frame.iterrows(), contributions, strict=True):
        groups = grouped_contributions(names, vector)
        positive = sorted(((name, value) for name, value in groups.items() if value > 0),
                          key=lambda item: item[1], reverse=True)[:3]
        reasons.append([factor_text(name, row) for name, _ in positive] + [""] * (3 - len(positive)))
        effects.append([value for _, value in positive] + [0.0] * (3 - len(positive)))
    for slot in (1, 2, 3):
        output[f"model_reason_{slot}"] = [items[slot - 1] for items in reasons]
        output[f"reason_{slot}_effect"] = [items[slot - 1] for items in effects]

    average = output["prior_average_amount"].to_numpy(dtype="float64")
    amount = output["amount_paid"].to_numpy(dtype="float64")
    ratio = np.divide(amount, average, out=np.full(len(output), np.nan), where=average > 0)
    output["amount_to_earlier_average"] = ratio
    output["amount_spike_rule"] = (output["prior_transaction_count"] >= 5) & (ratio >= 10)
    output["rule_reason"] = np.where(output["amount_spike_rule"],
                                      "Amount at least 10x earlier average after 5+ earlier payments", "")
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("data/processed/dashboard_cases_raw.csv"))
    parser.add_argument("--model", type=Path, default=Path("models/numpy_logistic_v1.npz"))
    parser.add_argument("--output", type=Path, default=Path("data/processed/dashboard_cases.csv"))
    args = parser.parse_args()
    with np.load(args.model, allow_pickle=False) as model:
        frame = pd.read_csv(args.input, dtype={"from_bank": str, "from_account": str,
                                               "to_bank": str, "to_account": str})
        if frame.empty:
            raise ValueError("The dashboard export has no transactions")
        explained = explain(frame, model)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    explained.to_csv(args.output, index=False)
    print(f"Wrote {len(explained):,} explained cases to {args.output}")
    print(f"Maximum model score reconstruction gap: {explained.score_reconstruction_gap.max():.9f}")


if __name__ == "__main__":
    main()
