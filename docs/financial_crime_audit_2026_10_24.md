# Financial Crime Analytics audit — October 24, 2026

## Scope and separation

Reviewed the earlier SQL/NumPy modelling workflow at `6cc0ae6b9d8928b0f9d26bd349cf19f6fe12ec5f`, separately from the banking pipeline audit. This audit covers transaction features, chronological boundaries, numerical metrics, saved-model explanations, score loading, report export, documentation, and dedicated CI. It is not a production banking or fraud-detection validation.

The feature SQL correctly partitions history by sender bank, account and payment currency, and excludes the entire current day. Current-day/future records and synthetic labels are not historical model inputs. A live PostgreSQL test confirms that later transactions and another bank/currency do not affect the earlier-day average. Numeric preprocessing statistics are fitted from training dates only.

## Reproduced problems and fixes

1. **Average precision mishandled ties.** A constant-score classifier on a 50%-positive fixture reported 0.8333 for one row order rather than prevalence 0.5. The implementation now groups equal scores at shared thresholds. This is non-interpolated average precision, not trapezoidal PR area. A hand-calculated mixed-score fixture checks the recall-step weighting.
2. **Ranking ties disagreed with the SQL queue.** NumPy's reverse score sort had no transaction-ID tie policy, while the exported review queue uses ascending transaction ID at equal score. Evaluation now receives IDs and uses the same ordering. New metrics record `evaluation_version = grouped_tie_ap_id_ranking_v2` and the tie policy. When direct helper callers omit IDs, input position is the deterministic fallback; the trainer always supplies transaction IDs.
3. **Incomplete score imports could appear successful.** The previous SQL printed a row-count difference but exited successfully after committing an incomplete score table. Imports now run in one transaction, enforce a transaction foreign key, and raise errors for missing scores or split/date disagreement. Three database tests prove failed imports leave no partially loaded score table. Existing score tables remain protected by the existing create-table refusal.
4. **Invalid data could silently reach evaluation.** Missing timestamps were assigned to test; NaN scores were accepted by metrics and could bypass explanation reconstruction checks. Timestamp, required-feature, binary-label, finite-value and numeric-range validation now fail explicitly. Nonpositive epoch/chunk settings are rejected, and empty splits or a one-class training set stop before writing scores. A single-class held-out ROC AUC is reported as undefined (`null`), rather than a misleading numeric zero.
5. **The modelling workflow lacked dedicated tests/CI.** Added numerical, preprocessing and SQL tests plus a PostgreSQL-backed Actions workflow. This workflow does not depend on the separate banking test job.

## Verification

**19 tests passed locally with no skipped database cases**, using Python 3.12 and a dedicated loopback PostgreSQL 16.15 instance. The suite covers tied-score AP and ROC, deterministic ranking, missing/invalid inputs, chronological day boundaries, label exclusion, unknown categories, finite explanation reconstruction, score-import rollback, and earlier-day SQL history.

A fabricated **100-row** end-to-end case creates SQL features, trains a model in chunks, scores all records, imports scores, exports the later-period queue, and reconstructs explanations. It checks 60 training, 20 validation and 20 test records and training-only preprocessing statistics. This is a smoke test, not new performance evidence or a replacement for the original dataset.

CI repeats the suite on PostgreSQL 16. Inspect the checks attached to this audit pull request for the current hosted result. Integration tests require a disposable database/server role with `CREATEDB`, and remove only their per-case databases. Never set `FINANCIAL_CRIME_TEST_DATABASE_URL` to working data.

## Historical performance status

The saved `reports/model_metrics.json` remains unchanged. Its split counts, confusion matrices, and Precision@K/Recall@K arithmetic reconcile internally, but the original row-level scores, feature CSV and model artifact are not committed. The 5.08-million-row experiment was **not rerun**. Correct AP and tied top-K metrics cannot be recomputed from aggregate JSON alone, and their exact change is unknown.

Therefore the saved 0.1016 AP and 199/1,000 result are historical outputs of the original evaluator, not freshly verified outputs of this corrected evaluator. The model report and README say so. No replacement metric or effect size is invented. If old artifacts still exist, re-evaluate those exact scores first; otherwise rebuild and record a new run with its source checksum, code revision, parameters, dependency versions and row-level tie policy.

The original modelling schema retains its documented `NUMERIC(18,2)` storage, which can round Bitcoin source amounts. Correcting precision requires reimporting the original source and regenerating features/scores. That is not silently migrated here, and prior metrics must not be relabelled as precision-corrected. It is separate from the newer banking pipeline's six-decimal storage.

## Remaining limitations

- Synthetic data, 18-day observation period and changing label prevalence.
- No new simple-heuristic comparison, external data, investigator study or calibrated crime probabilities.
- No proof of prevented losses, reduced investigation time, or live monitoring.
- Public screenshots document a static Power BI report; editable report source and live refresh are not established by these tests.
- Model tuning, chunk size and source ordering can affect training; the audit's synthetic smoke test is not an exact full-data reproduction.

The corrected evaluation and import path are ready for review. A fresh full-data run remains necessary before presenting historical performance figures as outputs verified by this audit.
