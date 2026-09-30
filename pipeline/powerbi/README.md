# Power BI report build kit

Status: the SQL reporting layer and local preview are implemented. A `.pbix` or
`.pbip` file has not been created or verified in Power BI Desktop. This host is
macOS, and the available Power BI web account has not opened an editable
workspace. The steps below are the exact handoff for an environment with report
authoring access. Do not present the local HTML preview as a Power BI report.

## Connection

1. Start PostgreSQL and publish analytics using the main pipeline runbook.
2. In Power BI Desktop, choose **Get data → PostgreSQL database**. Server:
   `localhost:5433`; database: `banking_pipeline`; mode: **Import**.
3. In Navigator, load these views/tables from the `analytics` schema:
   `v_daily_metrics`, `v_risk_alert`, `file_row_reconciliation`,
   `file_amount_reconciliation`, `v_pipeline_health`, `v_risk_evaluation`,
   and `publication_state`.
4. Keep bank and account identifiers as Text, dates as Date, event time as
   Date/Time, and amounts as Fixed decimal number. Use the saved `M_queries.pq`
   as the exact source query reference if Navigator does not display schemas.
5. Refresh only after `analytics.publication_state.published_at` changes.

The SQL views are already reporting shaped. No relationship is needed between
the daily aggregate and transaction-level alert sample. Cross-filter each page
within its own grain. Do not join on bank code alone and duplicate amounts.

## Pages

**Transaction overview.** Cards for transaction count, labelled synthetic
laundering count, alert count, and latest publication time. Line chart of count
by event date. Stacked column chart of count by payment format. Matrix of
`paid_amount` by date and payment currency. Bank filter and currency filter.
Keep currency visible on every amount visual; there is no conversion table.

**Risk monitoring.** Table from `v_risk_alert` sorted by descending risk score,
then event time. Show sender and receiver bank/account, amount and currency,
score, and three separate rule flags. The `is_laundering` synthetic label is
available only on a separate evaluation page, never as an input to the score.
Signals are exploratory and do not establish criminal activity.

**Pipeline health.** Cards for source, accepted, rejected, and duplicate
candidate counts. Table of `file_row_reconciliation` with `is_balanced` and
all component counts. Table of `file_amount_reconciliation` showing original
versus current amount totals by file and currency. Red conditional formatting
for nonzero deltas. Show publication ID and time from `v_pipeline_health`.

**Synthetic label evaluation.** Use `v_risk_evaluation`, grouped by date and
currency, for labelled alerts, unlabelled alerts, and missed labels. It covers
all published scored transactions, including non-alerts; `v_risk_alert` alone
cannot calculate recall. The supplied DAX measures calculate alert precision
and label recall against this synthetic answer key. Explain that rule-based
signals have not been calibrated or validated for real-world banking use.

Use `Measures.dax` for the basic counts. Save the finished report as PBIP/PBIR
if possible so its source can be reviewed in Git. [Microsoft's Power BI project
format documentation](https://learn.microsoft.com/en-us/power-bi/developer/projects/projects-overview)
describes that format. The PostgreSQL connector supports Import and DirectQuery;
Import is appropriate for these curated marts. [Microsoft connector
documentation](https://learn.microsoft.com/en-us/power-query/connectors/postgresql)
documents connection settings.

After authoring, capture screenshots of the four pages and place them in
`pipeline/screenshots/`. The repository intentionally contains no unverified
Power BI screenshots.
