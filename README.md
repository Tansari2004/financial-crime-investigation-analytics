# Banking Transaction Data Pipeline & Analytics Platform

A batch data-engineering portfolio project over IBM's synthetic AML transaction
data. The pipeline preserves raw source evidence, quarantines invalid and exact
duplicate-candidate rows, models transactions incrementally in PostgreSQL,
applies explicit correction events, and publishes reconciled analytics only
after quality gates pass. Python handles streaming file ingestion; PostgreSQL
does set-based transformations; Dagster schedules the workflow. A saved Power BI
report visualizes an exported snapshot of the published analytics.

```mermaid
flowchart LR
    CSV[IBM AML CSV] --> Loader[Python streaming ingestion]
    Loader --> Raw[raw + quarantine]
    Raw --> Staging[typed staging]
    Staging --> Core[core dimensions + transaction fact]
    Corrections[explicit corrections] --> Core
    Core --> Gates[reconciliation + quality gates]
    Gates --> Marts[published daily + risk marts]
    Marts --> BI[Power BI / local preview]
    Dagster[Dagster daily job] --> Loader
    Dagster --> Gates
```

Engineering evidence: SHA-256 file manifests and safe reruns; ingestion-ID
watermarks that retain late events; bounded promotion batches; immutable source
rows plus explicit correction history; transaction-scoped analytics publication;
currency-aware amount reconciliation; 11 Python tests and 24 dbt checks; and a
[reproducible 50,000-row benchmark](pipeline/BENCHMARK.md). The complete IBM
HI-Small file has now been run through this new pipeline: **5,078,345 source
rows**, **5,078,336 accepted and published**, **nine exact-payload duplicate
candidates**, and **zero invalid rejects**. The [full-run report](pipeline/evidence/full_run.json)
passed every count, currency-amount, and publication-boundary check; 24 dbt
checks passed against the published database. The local browser preview and the
saved Power BI report are separate artifacts.

### Banking pipeline Power BI report

The four-page [Banking Transaction Pipeline Analytics report](https://app.powerbi.com/groups/0a05dc72-9fe5-4d16-9ad8-96d9a86f8c09/reports/11bcb2bd-eee1-4e92-8d16-6321df6267e6) is saved in a private Power BI workspace. Its pages cover daily transaction activity, pipeline health, currency reconciliation, and rule-based risk-alert counts. The images below provide reviewable evidence without workspace access:

[![Daily transaction activity in the saved Power BI report](pipeline/screenshots/transaction-activity.png)](pipeline/screenshots/transaction-activity.png)

[Pipeline health](pipeline/screenshots/pipeline-health.png) · [Currency reconciliation](pipeline/screenshots/reconciliation.png) · [Risk monitoring](pipeline/screenshots/risk-monitoring.png)

The report uses a **static Excel import** exported from the verified PostgreSQL publication. It is not connected live to PostgreSQL or set up for automatic refresh, and this repository does not contain a `.pbix` or `.pbip` source file. The [report notes](pipeline/powerbi/README.md) document the pages and these limitations.

Start with the [pipeline guide](pipeline/README.md), [architecture decisions](pipeline/ARCHITECTURE.md),
[operations runbook](pipeline/RUNBOOK.md), and [Power BI report notes](pipeline/powerbi/README.md).
For a fresh local database and Dagster UI, run `docker compose up -d --build`;
then use the fixture and commands in the pipeline guide. The
[GitHub Actions run](https://github.com/Tansari2004/financial-crime-investigation-analytics/actions/runs/36775208579)
passed PostgreSQL, Dagster, dbt, and Docker Compose smoke tests. Docker is not
installed on this laptop, so the container check was performed in CI.

| Location | What a reviewer can inspect |
| --- | --- |
| [`src/banking_pipeline/`](src/banking_pipeline/) | Streaming loaders, correction handling, promotion, publication, Dagster assets |
| [`pipeline/sql/`](pipeline/sql/) | Raw/staging/core/analytics schemas and transactional SQL functions |
| [`pipeline/dbt/`](pipeline/dbt/) | Independent published-state quality tests |
| [`tests/`](tests/) | Unit and live-PostgreSQL failure/replay tests |
| [`pipeline/dashboard/`](pipeline/dashboard/) | Local published-data preview (not Power BI) |
| [`.github/workflows/banking-pipeline.yml`](.github/workflows/banking-pipeline.yml) | Python, dbt, and Docker Compose CI jobs |

## Earlier investigation and modeling workflow

PostgreSQL and machine-learning investigation pipeline across **5,078,345 synthetic transactions**. The database contains **5,177 simulated-laundering labels (0.1019%)** over September 1–18, 2022. Every transaction receives a model review score for case ranking. A separate export adds model-derived reasons to the top 10,000 later-period test cases.

The business question is: which transaction patterns merit closer investigation? Eight reproducible analyses cover size, label balance, data quality, currency-specific amounts, payment methods, outgoing account volume, hourly activity, and payments relative to strictly earlier account history.

The chronological logistic baseline was trained on dates before September 8 and tested on September 9 onward. In the later test period, its top 1,000 transactions contained **199 of 1,611** positive labels: **19.9% Precision@1,000**, **12.35% Recall@1,000**, and **0.1016 PR-AUC**. Test prevalence was 0.1865%, giving about 107× enrichment at K=1,000 within this synthetic test period.

### Power BI report and dashboard

The **Financial Crime Review Queue** report was built in Power BI from the top **10,000 ranked later-period test transactions**. Its first page is a case table with review rank, model score, transaction ID and time, model-derived reason, amount and currency, and sender/receiver bank and account IDs. The second page counts those cases by payment currency. A **Financial Crime Investigation Dashboard** was also created in My workspace; the verified dashboard tile shows the currency chart. The table is verified in the report, but has not been verified as a tile on that same dashboard.

![Power BI dashboard showing case counts by payment currency](docs/images/power-bi-dashboard.png)

[View the ranked review-queue report screenshot](docs/images/power-bi-review-queue.png) · [Power BI build details](docs/power_bi_build.md)

The screenshots document the result without requiring access to the private Power BI workspace. The report visualizes a **ranked sample**, not all 5.08 million rows. Its review scores are prioritization scores, not calibrated probabilities or proof of financial crime.

See the [model report](reports/model_report.md), [raw model metrics](reports/model_metrics.json), [findings](docs/findings.md), [resume and LinkedIn text](docs/career.md), and [interview guide](docs/interview.md).

```mermaid
flowchart LR
    A[IBM synthetic CSV] --> B[PostgreSQL transactions]
    B --> C[Point-in-time SQL features]
    C --> D[Chronological logistic model]
    D --> E[Review score for every transaction]
    E --> F[Ranked investigation queue]
```

### Reproduce the SQL version

Requirements: PostgreSQL 16 and the source `HI-Small_Trans.csv` in `data/raw/`. Run from the repository root with PostgreSQL's `createdb` and `psql` commands on your `PATH`. The dataset is not included; see [Obtain the data](#2-obtain-the-data) below.

For a NEW database only:

```sh
createdb financial_crime
psql -X -v ON_ERROR_STOP=1 -d financial_crime -f sql/schema.sql
psql -X -v ON_ERROR_STOP=1 -d financial_crime -f sql/load.sql
```

Skip database creation and loading if you have already imported the data. The loader refuses to import into a populated table to prevent duplicate ingestion.

Generate the report:

```sh
psql -X -v ON_ERROR_STOP=1 -d financial_crime -f sql/investigation.sql -o reports/sql_findings.txt
```

Build features, train, score every transaction, and load the scores:

```sh
psql -X -v ON_ERROR_STOP=1 -d financial_crime -f sql/model_features.sql
psql -X -v ON_ERROR_STOP=1 -d financial_crime -c "\copy model_features TO 'data/processed/model_features.csv' WITH (FORMAT csv, HEADER true)"
python src/financial_crime/train_model.py
psql -X -v ON_ERROR_STOP=1 -d financial_crime -f sql/model_scores.sql
```

The model processes the CSV in chunks. Model artifacts and large generated files stay local and are excluded from Git.

Generate explained cases for a Power BI report:

```sh
psql -X -v ON_ERROR_STOP=1 -d financial_crime -f sql/dashboard_export.sql
PYTHONPATH=src python -m financial_crime.explain_cases
```

This produces `data/processed/dashboard_cases.csv`. The explanation code checks that its feature contributions reconstruct the saved model score. See the [Power BI build guide](docs/power_bi_build.md) for the verified report and dashboard status, layout, and field types.

Run the interactive browser dashboard locally:

```sh
python3 scripts/build_dashboard_data.py
python3 -m http.server 8765 --bind 127.0.0.1
```

Then open `http://127.0.0.1:8765/dashboard/`. The dashboard has rank, date, currency, format, account/ID search, and amount-spike filters; daily shortlist and category charts; a paged case queue; and per-case model reasons. Its data comes from the top 10,000 **test-period** cases. It is a local browser dashboard, not a Power BI report. The 10,000-case sample and model dependencies are important limitations: in the current export, 9,998 cases have ACH format.

### Design choices and limitations

- Account identity uses both bank and account code. Codes are text to preserve leading zeros.
- Amounts are grouped by currency. Transaction volume is not verified loss or unique financial exposure.
- Timestamps have no supplied timezone. Do not assume UTC.
- The current table stores amounts to two decimal places; further currency-specific precision validation is needed before broader use.
- The historical amount comparison uses only earlier calendar days and requires ten prior payments. This is an exploratory history rule, not a validated alert threshold. Accounts without sufficient history are omitted.
- Full-period totals and hourly counts describe the observed data. Rebuild them as of scoring time before using them in a model.
- Labels are the training target and evaluation answer key; they are never model inputs.
- `review_score` orders cases but is not a calibrated probability of crime. Class weighting intentionally changes calibration.
- Predicting 0 everywhere would achieve about 99.8981% accuracy and find no positive cases, so evaluation uses PR-AUC and top-K metrics.
- Later test dates have a higher positive rate than training dates. Results measure this synthetic time split and do not establish real-world performance.

### Next milestones

Add the ranked case table to the verified Power BI dashboard, add report slicers and further summary visuals, validate any exposure-aware priority rule, and extend explanations beyond the exported top 10,000 test cases. Isolation Forest has not been implemented.

## Optional Python data profiling

The Python profiler below is an early exploration helper. The SQL report linked above is the authoritative V1 output. The three-row test fixture is fabricated test data and is not used for project metrics.

### 1. Create a Python environment

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

### 2. Obtain the data

The official [IBM AML-Data repository](https://github.com/IBM/AML-Data) points to an improved Kaggle distribution and the original IBM Box distribution. The transaction data is synthetic CSV data with a laundering tag; the data itself uses the CDLA-Sharing-1.0 licence, so read that licence before use.

Recommended: download a **small, documented Kaggle variant first** from [IBM Transactions for Anti Money Laundering (AML)](https://www.kaggle.com/datasets/ealtman2019/ibm-transactions-for-anti-money-laundering-aml). Place the selected transaction CSV under `data/raw/`. Do not commit it.

If you use the Kaggle CLI after installing and authenticating it, first inspect the dataset files:

```bash
python -m pip install kaggle
# Create a Kaggle API token at https://www.kaggle.com/settings/account,
# then place the downloaded kaggle.json in ~/.kaggle/kaggle.json and run:
chmod 600 ~/.kaggle/kaggle.json
kaggle datasets list -s "IBM Transactions for Anti Money Laundering"
kaggle datasets files ealtman2019/ibm-transactions-for-anti-money-laundering-aml
kaggle datasets download ealtman2019/ibm-transactions-for-anti-money-laundering-aml --path data/raw --unzip
find data/raw -type f
```

Alternatively, use the source links in the official repository and save the downloaded CSV in `data/raw/`.

### 3. Profile the real schema

Run this command with the actual file name shown by `find`:

```bash
python scripts/profile_dataset.py data/raw/YOUR_TRANSACTION_FILE.csv
```

For a very large CSV, get a quick first profile without loading the whole file:

```bash
python scripts/profile_dataset.py data/raw/YOUR_TRANSACTION_FILE.csv --sample-rows 500000
```

The factual report is written to `reports/dataset_profile.md`. It includes row count (or sampled row count), field names, inferred pandas types, missingness, cardinality, label distribution when detected, and amount statistics when detected.

## Source-to-table mapping

The two source columns named `Account` map to `from_account` and `to_account`. All eleven source columns are loaded in CSV order; PostgreSQL adds a generated `transaction_id`. The schema is saved in `sql/schema.sql`. The ID is a local identifier, not supplied by IBM. Nullable columns are checked by the quality query rather than assumed complete.

## Responsible-use note

The IBM data is synthetic and labels are not real-world evidence. Any later model will prioritize review work, may produce false positives and false negatives, can drift, and requires human oversight.
