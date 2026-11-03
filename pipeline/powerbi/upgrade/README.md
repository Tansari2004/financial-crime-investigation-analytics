# Banking Analytics: editable Power BI upgrade

**Status: source prepared and offline-verified; native Power BI runtime check and workspace publication pending.**

Inspected again November 3, 2026: 335 offline checks pass, all ten M queries
parse with Microsoft's parser 4.0.1 on Node 22, and Microsoft's PBIR validator
0.5.0 reports zero errors/warnings. The [connection audit](verification/source_audit.json)
records the embedded data sources and the original report's export blocker.
This published source preview was prepared locally; it is not a `.pbix` export
of the saved workspace report.

This is an editable Power BI project, not a screenshot, browser imitation, or
claim that the existing workspace report has been replaced. Its data is a
complete aggregate of the verified PostgreSQL publication. No database login,
account identifiers or original bank identifiers are embedded.

## Open the project

1. Extract the complete folder. Keep the `.Report` and `.SemanticModel` folders
   beside `Banking_Analytics.pbip`.
2. In a recent **Power BI Desktop for Windows**, enable Power BI project/PBIP
   support if requested, then open `Banking_Analytics.pbip`.
3. Refresh the model. All ten queries load included compressed snapshot data;
   the initial refresh needs no PostgreSQL connection or local source path.
4. Perform the native checks below before replacing the existing report or
   claiming that its interactions have been verified.

Power BI Desktop does not run natively on macOS. Workspace editing/publication
requires access to the Power BI service or a Windows Desktop environment.

## Report design

Three visible pages and one hidden drillthrough page are authored in PBIR:

- **Transaction overview:** date/currency/format filters, exact transaction and
  alert counts, alert rate, daily volumes, format mix and a dataset-specific note.
- **Data quality and reconciliation:** source/accepted/duplicate/status callouts,
  exact per-currency source, staging, expected-current and published values.
- **Alert workload:** absolute counts alongside rates, overlapping rule signals,
  and a route to supporting sampled records.
- **Alert sample details:** currency drillthrough retaining additional filter
  context, separate population/sample counts, rule reasons and a Back action.

The report has 38 native visual definitions. Its white/blue theme uses readable
titles and avoids splitting simple validation information across sparse pages.
File-level quality totals intentionally do not respond to event-date or payment-
format filters. Monetary values are never totalled across currencies.

## Data and model

Source: IBM AML HI-Small synthetic transactions, published in the local
`banking_pipeline_fullrun` database, publication 1. Publication time is
**2026-10-01 03:33:14 UTC**. Event timestamps have no supplied timezone.

| Control | Value |
| --- | ---: |
| Source records | 5,078,345 |
| Accepted/published transactions | 5,078,336 |
| Rule-based alerts | 766,725 |
| Duplicate candidates excluded | 9 |
| Invalid rejects | 0 |
| Event dates | 18 |
| Currencies / payment formats | 15 / 7 |
| Full source daily aggregate rows | 217,161 |
| Exported date/currency/format aggregate rows | 862 |
| Bounded alert-detail sample | 455 |

The 862 reporting rows aggregate **all** 217,161 source daily rows across banks.
There is no daily row limit. Counts, labels and rule totals reconcile to the
complete publication; the model does not pretend that a small sample contains
five million row-level transactions.

`FactDaily` has date/currency/payment-format grain. `DimDate`, `DimCurrency` and
`DimFormat` filter both the full fact and the bounded `AlertSample`. `DimFile`
filters the two file-quality facts. `DimRule` is intentionally disconnected and
selects a context-aware rule-count measure. Nine single-direction relationships
avoid fact-to-fact joins.

The 23 measures include safe division, preceding-day comparisons, selected-
format shares, rule selection and a quality status that reports missing data.
Reconciliation failure counts are computed before aggregation, preventing
opposing discrepancies from cancelling. Currency amounts stay as exact decimal
text from PostgreSQL so six-decimal values are not silently rounded to Power
BI's four-decimal fixed currency type.

`Measures.dax` and `PowerQuery.m` are the actual definitions used by this model,
rather than future examples. Power Query selects known columns and enforces
dates, integers, booleans and text explicitly.

## Findings verified in the source database

- The September 10 to 11 decline is real in the supplied dataset: **208,325 to
  396** transactions. The final eight dates contain **1,108** transactions.
  This is not evidence of an actual banking outage or a proven import error.
- US dollars have the greatest alert count (**288,101**). Saudi riyals have a
  higher alert rate (**16.04%**) than US dollars (**15.20%**). Counts and rates
  answer different workload questions; neither establishes real fraud risk.
- All 15 exact currency reconciliations pass in this source publication.

Rule scores are the pipeline's heuristic scores, not the separate financial-
crime logistic-model scores. High amount and high hourly velocity each add two
points; repeated counterparty adds one. An alert requires at least two points.
Rule hit counts overlap and can include signals below that threshold.

The detail sample takes at most three highest-score alerts per date/currency.
It is deliberately nonrepresentative. All rates and population counts come from
the complete aggregate, never from the 455 sampled records. Some valid filter
selections can have alerts but no sampled detail rows.

## Verification completed

- Microsoft's `powerbi-report-authoring-cli` **0.5.0**: report schema, bindings,
  visual roles and formatting validation: **zero errors, zero warnings**.
- Microsoft's `powerquery-parser` **4.0.1**: all ten table queries parse.
- `verification/offline_checks.json`: count/grain controls, unique dimension
  keys, foreign keys, filter arithmetic, sample boundaries, exact decimal
  reconciliation, field bindings and non-overlapping page geometry.
- `verification/data_checks.json`: source controls and complete per-day counts.

These are offline/source checks. They do not establish that native DAX has run,
Power Query has refreshed in Desktop, or the report has rendered correctly.

## Still required in Power BI

1. Open and refresh all ten tables without model or query errors.
2. Check the unfiltered KPIs against the control table above.
3. Test date/currency/format selections. Confirm a zero-row selection does not
   fabricate a rate and sample counts never become the rate denominator.
4. Confirm source-file totals retain their declared full-file scope.
5. Drill through a currency with date/format filters, verify the context, then
   use Back. Check a selection with no sampled rows.
6. Inspect all three visible pages and the detail page at normal zoom; check
   table widths, cards, filter controls, notes and date sorting.
7. Publish the verified project to the intended workspace, export new report
   images/PDF and update the portfolio evidence. The existing saved four-page
   report and its public screenshots have **not** been overwritten.

Automatic database refresh, a gateway, role-based security and a cloud database
are not implemented or claimed. They are optional later work, not a prerequisite
for demonstrating this snapshot report.

## Rebuild from the source database

From the repository root:

```sh
python scripts/export_powerbi_snapshot.py --database banking_pipeline_fullrun
python scripts/build_powerbi_model.py
python scripts/build_powerbi_report.py
python scripts/verify_powerbi_upgrade.py
powerbi-report-author validate pipeline/powerbi/upgrade/Banking_Analytics.pbip
```

The export executes one repeatable-read, read-only transaction. It does not
alter the pipeline, publish a new database snapshot or change source records.
Use `--host`, `--port` and `--psql` for another installation. PostgreSQL settings
are not embedded credentials. The original database must be accessible; the
temporary verification copy used during development is not a deployed service.

In the standalone download, the same Python scripts are under `tools/`:

```sh
python tools/export_powerbi_snapshot.py --output data/snapshot.json
python tools/build_powerbi_model.py
python tools/build_powerbi_report.py
python tools/verify_powerbi_upgrade.py
```

The expected controls and written findings describe this fixed demo publication.
Review them before adopting a genuinely different source run. Refreshing the
embedded snapshot in Desktop reloads the packaged data; it does not query the
database automatically.

## Attribution and format references

- Data: [IBM AML-Data](https://github.com/IBM/AML-Data), synthetic HI-Small.
  Underlying data licence: CDLA-Sharing-1.0. Preserve the source attribution and
  applicable licence when redistributing data-derived extracts.
- [Power BI project format](https://learn.microsoft.com/en-us/power-bi/developer/projects/projects-overview)
- [Star-schema modelling guidance](https://learn.microsoft.com/en-us/power-bi/guidance/star-schema)
- [Microsoft Power Query parser](https://github.com/microsoft/powerquery-parser)
- [Original project evidence](https://github.com/Tansari2004/financial-crime-investigation-analytics/tree/main/pipeline/evidence)
