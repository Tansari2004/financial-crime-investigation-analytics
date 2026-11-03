# Full-source precision audit · November 3, 2026

The full **5,078,345-row** source was re-read, its decimals validated, point-in-time features rebuilt, and both full-precision and rounded-control models retrained with identical settings. No new hyperparameters or test split were selected. This is a retrospective audit, not a fresh final evaluation.

- [Current full-precision metrics](metrics.json)
- [Matched rounded-control metrics](rounded_control_metrics.json)
- [Model versus amount/history and frequency rules](rule_comparison.json)
- [Rounded-control rule diagnostics](rounded_rule_comparison.json)
- [Precision impact and ranking overlap](precision_comparison.json)
- [Independent full-precision check](independent_verification.json)
- [Independent rounded-control check](rounded_independent_verification.json)
- [Source precision](source_precision.json) and [same-source currency audit](rounded_source_precision.json)
- [Runtime/settings and artifact hashes](run_manifest.json)
- [Full-precision model](model.npz) and [rounded-control model](rounded_control_model.npz)

**Main findings:** full precision retrieves 267/1,000 positive labels, versus 34 for the amount-relative-to-prior-average rule and 1 for prior frequency. The matched rounded control retrieves 270; preserving decimals is a correctness fix, not a measured ranking improvement. The two top-1,000 queues share 991 transaction IDs.

**Read the date diagnostic before quoting the overall number.** Of the model's 267 retrieved positives, 217 come from September 11–18: only 1,108 rows, with 655 positive labels. On the two high-volume dates September 9–10 (862,792 rows, 956 positives), a separate capacity-matched diagnostic retrieves 76 positives versus 26 for the amount rule and 1 for frequency. This period diagnostic was added after inspecting volumes; it does not replace the original test or represent fresh validation. All 1,000 cases in the full-test queue are ACH, showing strong payment-format dependence.

Scikit-learn independently reproduces AP, ROC-AUC, confusion matrices and stable-ID capacity results for validation/test and all 31 test date/currency/format slices: **1,822 assertions per run, 3,644 total**. Reference and training library versions are recorded separately.

The bounded rebuild uses DuckDB rather than a full local PostgreSQL import to avoid the multi-GB database. Tests check both decimal modes against PostgreSQL on multi-day fixtures. Original source text is exactly representable in the chosen decimal type; only model features convert to double precision. The full PostgreSQL database was not rebuilt. Saved Power BI screenshots remain the original v1 experiment.

Original CSV/features/score exports are not redistributed. Obtain the separately licensed source, then run the [reproduction command](../../docs/financial_evaluation_upgrade.md). Hashes identify the exact local artifacts; fresh model regeneration can have small platform-dependent floating-point differences. Model NPZ files contain numerical parameters and categorical feature names, not transaction/account records.
