"""Disk-saving exports must retain exactly the same evaluation predictions."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pandas as pd
from pandas.testing import assert_frame_equal


def test_evaluation_only_export_and_rule_comparison(tmp_path):
    root = Path(__file__).resolve().parents[1]
    # Three time partitions, both labels, prior history and categorical inputs.
    frame = pd.DataFrame([
        {"transaction_id": i + 1, "transaction_time": day,
         "amount_paid": 1 + i / 100, "payment_currency": "Bitcoin",
         "receiving_currency": "Bitcoin", "payment_format": "Wire",
         "same_bank": 0, "self_transfer": 0, "transaction_hour": i % 24,
         "transaction_weekday": 1 + i % 7, "prior_transaction_count": i,
         "prior_average_amount": 1 if i else 0, "has_prior_history": int(i > 0),
         "is_laundering": i % 2}
        for i, day in enumerate(["2022-09-01"] * 10 + ["2022-09-08"] * 10 + ["2022-09-09"] * 10)
    ])
    features = tmp_path / "features.csv.gz"
    frame.to_csv(features, index=False)
    for name in ("all", "evaluation"):
        command = [sys.executable, "-m", "financial_crime.train_model", "--features", str(features),
                   "--scores", str(tmp_path / f"{name}.csv.gz"), "--model", str(tmp_path / f"{name}.npz"),
                   "--metrics", str(tmp_path / f"{name}.json")]
        if name == "evaluation":
            command.append("--evaluation-scores-only")
        subprocess.run(command, cwd=root, check=True, capture_output=True)
    full = pd.read_csv(tmp_path / "all.csv.gz")
    selected = pd.read_csv(tmp_path / "evaluation.csv.gz")
    assert len(full) == 30 and len(selected) == 20
    assert_frame_equal(full.loc[full.data_split.ne("train")].reset_index(drop=True), selected)
    a = json.loads((tmp_path / "all.json").read_text())
    b = json.loads((tmp_path / "evaluation.json").read_text())
    assert a["test"] == b["test"] and a["validation"] == b["validation"]
    evidence = tmp_path / "precision.json"
    evidence.write_text(json.dumps({"features_sha256": a["features_sha256"], "fixture": True}))
    subprocess.run([sys.executable, str(root / "scripts/compare_financial_rules.py"),
                    "--features", str(features), "--scores", str(tmp_path / "evaluation.csv.gz"),
                    "--model-metrics", str(tmp_path / "evaluation.json"),
                    "--precision-evidence", str(evidence), "--output", str(tmp_path / "comparison.json")],
                   cwd=root, check=True, capture_output=True)
    comparison = json.loads((tmp_path / "comparison.json").read_text())
    assert comparison["splits"]["test"]["logistic"] == b["test"]
    subprocess.run([sys.executable, str(root / "scripts/verify_financial_results.py"),
                    "--features", str(features), "--scores", str(tmp_path / "evaluation.csv.gz"),
                    "--metrics", str(tmp_path / "evaluation.json"),
                    "--comparison", str(tmp_path / "comparison.json"),
                    "--output", str(tmp_path / "verification.json")], cwd=root, check=True, capture_output=True)
    verification = json.loads((tmp_path / "verification.json").read_text())
    assert verification["status"] == "passed"
    assert verification["total_feature_rows"] == 30
