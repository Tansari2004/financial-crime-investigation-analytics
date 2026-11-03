# Financial-crime precision and metric audit · completed

The storage blocker was resolved with a bounded-space rebuild. **All 5,078,345 source rows were re-read, decimals validated, features rebuilt, and full-precision and matched rounded-control models retrained.** Results and independent checks are published in [the audit artifacts](../reports/full_precision/README.md) and [current model report](../reports/model_report.md).

## Verified results

- Full-precision model: average precision **0.1276433**; **267 positives in 1,000 reviews**, 26.7% precision and 16.57% recall.
- Same-capacity amount/history rule: **34** positives; earlier-day frequency rule: **1**.
- Matched two-decimal control: **270**, not 267. Preserving amounts is a correctness fix, **not a demonstrated ranking improvement**.
- **991/1,000** queue IDs are shared between the matched precision runs.
- **145,670 paid** and **147,755 received** values lose precision at two decimals, all in Bitcoin; **112,769** prior-average feature values change.
- Scikit-learn independently reproduces AP, ROC-AUC, confusion matrices and capacity metrics across both runs: **3,644 assertions**, including validation/test and 31 date/currency/payment-format slices per run.

The original 199/1,000 v1 result is [archived](../reports/legacy/model_report.md). It is not the matched rounded control: differences from that older run cannot be attributed to precision alone. The new paired runs hold source-ID order, feature definitions, runtime, epochs and chunk size fixed. No model tuning was performed.

## Important interpretation

**217 of the 267 retrieved positives come from a tiny late tail.** September 11–18 contains just 1,108 rows but 655 positive labels. September 9–10 contains 862,792 rows and 956 positives. In a separate high-volume-date diagnostic, the model finds **76/1,000**, versus **26** for amount/history and **1** for frequency. That diagnostic was added after examining volumes; it is not a new untouched holdout or a replacement for the original test.

All global top-1,000 cases are ACH. The model may exploit simulator-specific date and payment-format patterns. These results establish neither real-bank performance nor money saved. The old Power BI screenshots still show v1 and have not been relabeled as the new audit.

## Correctness changes

The custom AP function now groups tied scores at distinct thresholds. Label order within a tie cannot change AP. Small exhaustive tie cases and randomized rounded scores are checked against [`sklearn.metrics.average_precision_score`](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.average_precision_score.html). Capacity ranking uses source-ID order to resolve ties; AP and selecting exactly K cases are different calculations.

The PostgreSQL modelling schema now uses unconstrained `NUMERIC`. Fresh COPY and history tests preserve amounts beyond cents, including 0.025852 and 0.00123456789. Simply widening an old column cannot recover rounded values.

The full audit used **DuckDB DECIMAL(38,12)** from original source text to fit local storage. Every input amount is validated as exactly representable before the engine can round it. The rounded control deliberately casts through DECIMAL(18,2), then uses the same accumulator type as the full run. Both modes are checked against the PostgreSQL feature SQL on multi-day fixtures with Bitcoin and ordinary currency values. Non-amount features, labels and row order match across all 5.08M paired rows.

This completes the feature/model audit; **it is not a full rebuild of the local PostgreSQL database**. Existing banking pipeline tables/publications were not changed. Source values retain decimal precision; model features intentionally convert to double. Reviewer explanation text no longer hides small amounts by formatting everything to two decimal places.

## Reproduce with bounded disk use

Use Python 3.12, the separately licensed original `HI-Small_Trans.csv`, and a fresh output directory. Keep room for the locally readable source, roughly 165 MB of compressed exports and up to 200 MB temporary work; allow extra space for the Python environment and system overhead. The published run reused an installed runtime rather than installing another large environment.

```bash
python -m venv .venv-audit
.venv-audit/bin/python -m pip install -r requirements-financial-audit.txt
.venv-audit/bin/python scripts/recompute_financial.py --source data/raw/HI-Small_Trans.csv --output data/processed/new_precision_audit
```

On Windows use `.venv-audit\Scripts\python.exe`. The runner sets a single BLAS thread and original transaction-ID order, creates new full/control directories, trains with unchanged settings, evaluates identical review capacities, runs trusted reference verification, and compares features, scores and queue IDs. It never overwrites a previous experiment. Only validation/test scores are exported; every original row is still read and its features rebuilt, with all training rows used in fitting.

The training runtime was NumPy 2.3.5, pandas 2.2.3 and DuckDB 1.4.1. Independent verification ran separately with scikit-learn 1.6.1, NumPy 2.0.2 and pandas 2.3.3. [Artifact hashes/settings](../reports/full_precision/run_manifest.json) identify exact published evidence. Small floating-point differences are possible across platforms; matched precision experiments must share their runtime and order.

For a full new PostgreSQL database instead, retain the original fresh-import workflow:

```bash
python -m pip install -e '.[dev,evaluation]'
createdb financial_precision_v2
python scripts/rebuild_financial_precision.py --source data/raw/HI-Small_Trans.csv --database-url postgresql:///financial_precision_v2 --output data/processed/full_postgres_v2
```

That path requires several GB for the database, indexes and exports. It refuses existing modelling tables and output files. Do not silently alter a populated rounded database and call its original values restored.

## Reviewer walkthrough

1. Inspect a ranked case's original timestamp, amount, currency and payment format. A high score determines review order, not guilt.
2. Read model contribution terms and earlier-day account context. The amount ratio compares the sender to its own earlier same-currency average; missing history differs from a true zero average.
3. Check source evidence and related activity. All top-1,000 cases being ACH and the unusually positive late tail are warnings about simulator dependence, not proof the score transfers to a real bank.
4. Record a human decision, supporting evidence and uncertainty. Contributions explain this linear score, not causes or wrongdoing. Do not automatically block accounts from this prototype.
5. Report false positives, missed positives, review capacity and period coverage together. A score threshold of 0.5 is not an established operating policy. Keep the current model audit separate from the older saved Power BI report.
