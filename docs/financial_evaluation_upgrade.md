# Financial-crime metric and precision correction

## Implemented and verified

The custom non-interpolated average-precision calculation now groups identical scores at a threshold before adding recall increments. Tied-label order no longer changes AP. Exhaustive small tie cases and randomized rounded scores match [`sklearn.metrics.average_precision_score`](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.average_precision_score.html), including all-positive/all-negative cases. Capacity-limited rankings use stable source transaction order to resolve boundary ties. AP and precision@K are different quantities; K still selects exactly K rows.

The original modelling schema now uses unconstrained PostgreSQL `NUMERIC` for source amounts. A live COPY/feature test preserves 0.025852 and 0.00123456789, including the previous-day average. Widening an already loaded column cannot recover old rounded values: the rebuild starts from original source text in a fresh database and refuses to overwrite an existing modelling table or output directory.

The bounded-space alternative validates every source decimal before using `DECIMAL(38,12)`, and refuses values it cannot represent exactly. On the 180-row fabricated multi-day test, its features agree with the PostgreSQL SQL output within 1e-12. Both keep earlier-calendar-day history and convert to double only at the modelling-feature boundary. That is a fixture equivalence check, not proof of equivalence on all inputs or a complete full PostgreSQL import.

Nine regression tests pass. A separate 180-row fabricated smoke run completed PostgreSQL import, feature export, training, hash-matched scores, rule comparisons and date/currency/format diagnostics. Those fixture scores are not portfolio performance results.

## Full-dataset status: pending

The original 5,078,345-row source hash was observed as `b19d39f515523373f991b689c07e11e7b0b95c17a2c27a87d91584ae16c5b040`. The full precision-corrected rebuild/retraining did not finish: the machine has less than 0.5 GB free disk and the source is in cloud-managed storage. No new full-dataset metric, ranking improvement or amount-precision effect is claimed. The original rounded v1 results are preserved in [legacy artifacts](../reports/legacy/); the published report and Power BI screenshots still depict that experiment. Correct code alone does not establish whether its published AP or top-K findings change.

## Rebuild when storage is available

Install Python 3.11+, PostgreSQL 16 and the optional evaluation dependencies:

```bash
python -m pip install -e '.[dev,evaluation]'
createdb financial_precision_v2
python scripts/rebuild_financial_precision.py --source data/raw/HI-Small_Trans.csv --database-url postgresql:///financial_precision_v2 --output data/processed/full_precision_v2
python -m financial_crime.train_model --features data/processed/full_precision_v2/model_features.csv --scores data/processed/full_precision_v2/scores.csv --model data/processed/full_precision_v2/model.npz --metrics data/processed/full_precision_v2/metrics.json
python scripts/compare_financial_rules.py --features data/processed/full_precision_v2/model_features.csv --scores data/processed/full_precision_v2/scores.csv --precision-evidence data/processed/full_precision_v2/precision_import.json --model-metrics data/processed/full_precision_v2/metrics.json --output data/processed/full_precision_v2/comparison.json
```

Allow several GB for the database, indexes, exports and temporary work. This intentionally creates a new experiment rather than silently rewriting an old database.

For a smaller-disk alternative, `scripts/rebuild_financial_bounded.py --source ... --output ...` writes compressed features using DuckDB with a 1.25 GB memory and 200 MB temporary-file limit. It still needs the complete locally readable source and room for compressed features/scores. It is not evidence of a full PostgreSQL import. Use its `.csv.gz` output in the same training/comparison commands and `.csv.gz` for scores. The script records the engine, exact-source capacity validation, source hash and feature hash.

Feature, score and metric SHA-256 checks prevent comparing old scores with newly imported features. Keep the same source order, training dates, chunk size, optimizer and epochs when auditing precision impact. Compare old and new AP, all capacity counts, score differences and top-K ID overlap; attribute any tie-boundary changes separately from precision changes before replacing published results.

## Capacity comparison and slices

The comparison evaluates the model and two untuned earlier-history rules at K=100, 500, 1,000 and 5,000 on identical rows: amount divided by the account's earlier same-currency average; and earlier-days transaction frequency within currency. The amount ratio is zero when there is no positive prior average. It is not an exchange-rate conversion. No raw dollar/Bitcoin magnitudes are ranked against each other.

Rows are ordered by source transaction ID before ties are broken, never by outcome labels. Rule ties at the capacity boundary can affect found counts and must be acknowledged. The same precision/recall/AP computation applies to every method. Date, currency and payment-format diagnostics retain counts/prevalence and per-method capacity results; a group with few positives is not reliable evidence of subgroup performance. Different group prevalence, simulator construction and the short 18-day window limit interpretation. These are retrospective diagnostics, not a new untouched final test or a demonstrated real-bank benefit.

## Reviewer walkthrough

1. Open a ranked case and inspect its original timestamp, payment format, amount and currency. A high score determines review order, not guilt.
2. Read the feature-contribution terms alongside earlier-day activity. An amount ratio compares the sender with its own earlier same-currency average. Missing prior history differs from a genuine zero average.
3. Check the original transaction and related context. Currency/payment-format patterns may reflect the simulator rather than useful real-world evidence. Contribution signs explain this linear score, not causes or proof.
4. Record a human decision, evidence and uncertainty. Do not automatically block an account or classify wrongdoing from this score. Synthetic truth labels are used for offline evaluation, not available as live review evidence.
5. Report the queue's false positives and missed positives at the chosen capacity. Until the full rerun completes, the saved queue and its 199/1,000 count remain historical v1 evidence.
