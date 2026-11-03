# Resume and interview wording after the precision audit

Suggested project bullets:

- Rebuilt point-in-time features from 5.08 million synthetic financial transactions, corrected decimal import and tied-score evaluation errors, and verified metrics against scikit-learn.
- Compared a class-weighted logistic model with amount/history and frequency rules at identical review capacities; exposed substantial time-prevalence shift and payment-format dependence.
- Built an earlier two-page Power BI review report with model-linked reasons; retain its v1 version label when showing screenshots.

If quoting a result, give its scope: the full synthetic test retrieves 267/1,000, but 217 positives come from a tiny high-prevalence late tail. A separate diagnostic of the two high-volume dates retrieves 76/1,000 versus 26 for the amount rule. This diagnostic was added after inspecting volume patterns and is not fresh validation.

Do not say that preserving precision improved detection: the matched rounded control retrieves 270, and 991 queue IDs are shared. The old 199/1,000 is historical v1, not the current matched control. The audit used a bounded-space DuckDB rebuild with PostgreSQL equivalence fixtures; it did not rebuild the full PostgreSQL database or refresh the saved Power BI report.

Do not claim prevented losses, production monitoring, calibrated crime probabilities, real-bank validation or investigator time saved. No new LinkedIn post or resume edit is implied by this wording guide.
