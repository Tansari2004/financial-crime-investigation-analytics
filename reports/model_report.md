# Financial-crime ranking: full-precision recomputation

**Current audit: November 3, 2026.** All 5,078,345 source rows were re-read, exact decimal source values validated and features rebuilt. A bounded-space DuckDB implementation of the point-in-time SQL was used; it is fixture-checked against PostgreSQL, not a complete new PostgreSQL database import. [Artifacts and verification](full_precision/README.md).

## Chronological evaluation

| Split | Dates | Rows | Positive labels |
| --- | --- | ---: | ---: |
| Train | Before September 8, 2022 | 3,731,672 | 3,027 |
| Validation | September 8, 2022 | 482,773 | 539 |
| Test | September 9–18, 2022 | 863,900 | 1,611 |

The model remains class-weighted NumPy logistic regression with three epochs and 200,000-row chunks. Rows are explicitly ordered by original transaction ID. Features use earlier calendar days only; targets and dates are unchanged. No tuning was performed on the observed holdout. Scores order review cases and are not calibrated crime probabilities.

## Current full-test results

Average precision is **0.1276433**, independently checked against scikit-learn's non-interpolated AP; ROC-AUC is **0.9634822**. The legacy `pr_auc` JSON key remains an AP alias, not trapezoidal PR area. Single-class subgroup ROC-AUC is null.

| Review capacity | Positive labels found | Precision | Recall |
| ---: | ---: | ---: | ---: |
| 100 | 37 | 37.0% | 2.30% |
| 500 | 147 | 29.4% | 9.12% |
| 1,000 | 267 | 26.7% | 16.57% |
| 5,000 | 667 | 13.34% | 41.40% |

The top-1,000 queue still includes 733 negatives and misses 1,344 positives. A 0.5 score cutoff produces 115,465 false positives, so it is not an established operating threshold.

## Same-capacity rule comparison

All methods use the same test rows and the same deterministic source-ID tie policy. The amount rule is the payment amount divided by the sender's earlier same-currency average; it is zero when no positive prior average exists. The frequency rule counts sender transactions on earlier days in the same currency. These are untuned comparisons, not an exhaustive baseline search.

| Reviewed | Model positives | Amount/history positives | Prior-frequency positives |
| ---: | ---: | ---: | ---: |
| 100 | 37 | 4 | 1 |
| 500 | 147 | 17 | 1 |
| 1,000 | 267 | 34 | 1 |
| 5,000 | 667 | 86 | 5 |

Average precision: model 0.1276433; amount/history 0.0037663; frequency 0.0012963. Raw amounts in different currencies are never compared as equivalent units. Source-ID tie breaking is reproducible but is an arbitrary choice when a rule has a tied boundary.

## What the aggregate result hides

The source's test distribution changes sharply:

| Diagnostic period | Rows | Positive labels | Positive rate | Model found / 1,000 | Amount rule | Frequency rule |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| September 9–10 | 862,792 | 956 | 0.1108% | 76 | 26 | 1 |
| September 11–18 | 1,108 | 655 | 59.12% | 655 | 564 | 564 |

**217 of the global queue's 267 positives come from the tiny late tail.** The high-volume-date diagnostic has model AP 0.0358749, versus 0.0026621 for amount/history. This diagnostic was added after observing the volume change; it is not a replacement holdout, tuning result or new prospective validation.

All 1,000 global shortlisted cases are **ACH**. The test has 1,489 positive ACH labels out of 1,611 positives across all formats. This strong payment-format association and the unusual late tail may reflect simulator construction. Date/currency/format metrics and counts are all published; small or single-class groups do not establish reliable subgroup performance.

## What preserving precision changed

145,670 paid amounts and 147,755 received amounts lose precision under the original two-decimal import, all in Bitcoin. The paired audit compares every source ID: non-amount features, labels and order are identical; 112,769 prior-average feature values change.

| Matched audit | Test AP | Found / 1,000 |
| --- | ---: | ---: |
| Full source precision | 0.1276433 | 267 |
| NUMERIC(18,2) import control | 0.1288358 | 270 |

The top-1,000 queues share 991 IDs. Preserving decimals does **not** improve ranking in this comparison; it restores correct input values. Both models use the same runtime, settings and source-ID ordering. The original v1 report's 199/1,000 is preserved in [legacy results](legacy/model_report.md), but its difference from this audit is not a controlled precision-only comparison.

## Verification and boundaries

Both runs pass independent scikit-learn AP/ROC/confusion and separate stable-ID ranking checks over validation/test plus 31 test slices: **3,644 assertions** in total. Two precision-mode PostgreSQL equivalence tests, exact-decimal COPY/history checks, tied-score regressions, compressed export checks and explanation formatting checks accompany the audit. The original saved Power BI report/screenshots have not been refreshed and retain v1 scores.

This is synthetic, retrospective, short-window evidence. There is no external validation, probability calibration, real investigator feedback, prevented-loss estimate or demonstrated production benefit. Preserve the original correction history and use a genuinely new representative test before choosing future improvements.
