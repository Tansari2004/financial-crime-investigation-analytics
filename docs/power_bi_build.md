# Power BI investigation dashboard

## Current status

The project generates `data/processed/dashboard_cases.csv`, a 10,000-row, 3.6 MB export of the highest-ranked **later-period test transactions**. Each row has the existing model review score, up to three model factors that increased it, and a separate transparent amount-spike rule. The file is local and excluded from Git because it contains generated transaction records.

On September 29, 2026, the CSV was imported into Power BI's **Financial Crime Risk Data** semantic model in My workspace. The saved **Financial Crime Review Queue** report was visually verified with:

- A ranked transaction table (Page 1): `review_rank`, `review_score`, `transaction_id`, `transaction_time`, `model_reason_1`, `amount_paid`, `payment_currency`, and sender/receiver bank and account IDs. The table was sorted with rank 1 first, and leading zeros in bank IDs were preserved.
- **Currency Mix — Top 10k Cases** (Page 2): a bar chart with `payment_currency` on the Y-axis and **Count of `transaction_id`** on the X-axis. This counts exported cases, not total financial exposure.

A **Financial Crime Investigation Dashboard** was created and visually verified with the currency chart tile. The ranked table has **not** yet been verified as a tile on that same dashboard. Two dashboards with the same name appeared in My workspace; do not assume they are identical. See the [dashboard screenshot](images/power-bi-dashboard.png) and [report-table screenshot](images/power-bi-review-queue.png). The Power BI workspace is private; these screenshots are the public evidence in this repository. No public report link or `.pbix` file is provided.

## Generate the report data

From the repository root, after creating `model_features` and `model_scores`:

```sh
psql -X -v ON_ERROR_STOP=1 -d financial_crime -f sql/dashboard_export.sql
PYTHONPATH=src python -m financial_crime.explain_cases
```

The second command refuses to export explanations unless their reconstructed scores match the saved model scores within `0.00001`. On the existing data, the maximum difference was below `0.000000001`.

## Rebuild or extend the Power BI report

The steps below describe the intended fuller report design. Slicers, cards, additional reason columns, and an evaluation page have **not** been verified as completed in the Power BI report.

1. Open Power BI Desktop or a Power BI workspace that allows report creation. Import `data/processed/dashboard_cases.csv` as a text/CSV source and name the table `Cases`.
2. In Power Query, set `from_bank`, `from_account`, `to_bank`, and `to_account` to **Text** so leading zeros survive. Set `transaction_time` to Date/Time, `review_rank` and `transaction_id` to Whole Number, `review_score` and `reason_1_effect` through `reason_3_effect` to Decimal Number, and `amount_paid` to Decimal Number. Set `amount_spike_rule` to True/False.
3. Add slicers for date, payment currency, payment format, and amount-spike rule.
4. Add a transaction table sorted by `review_rank` ascending. Show date/time, sender and receiver bank/account, amount **with its currency**, review score, `model_reason_1` to `model_reason_3`, and `rule_reason`.
5. Add cards for displayed case count and displayed amount-spike count. Add a bar chart of displayed case count by payment format and another by payment currency. These counts respond to the slicers.
6. Add a second page named **Model evaluation** if you want to use `is_laundering`. Keep that answer-key column off the investigator page. The first 1,000 exported test rows contain 199 positive synthetic labels.
7. Title the report **Synthetic transaction review queue** and add a note: “Scores rank review priority; they are not calibrated crime probabilities. Model factors describe this model's math, not proof of wrongdoing.”

Do not sum amounts across different currencies into one total. A Saudi Riyal value and a US Dollar value need conversion before comparison or addition.

## What the explanation means

For each transaction, the logistic model calculates a raw score by adding a bias and weighted feature values. The export groups related time and day values, then lists up to three positive contributions to that raw score. A positive contribution raises the model's score relative to its mathematical zero-coded reference. It does **not** mean the feature caused laundering or that removing it would produce a trustworthy counterfactual.

The amount-spike rule is separate: it triggers only when the sender has at least five earlier payments in the same payment currency and the current amount is at least ten times the earlier average. This is an illustrative review flag, not a validated fraud threshold.
