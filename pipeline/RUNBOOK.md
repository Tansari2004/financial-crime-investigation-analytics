# Pipeline runbook

## Fresh local setup

Run `docker compose up -d --build`. PostgreSQL initializes five SQL files in
numeric order. Dagster opens at `http://localhost:3000` when its container is
ready; the daily schedule is defined but starts disabled so a clone does not
unexpectedly ingest a large local file. Enable it in Dagster after checking the
source directory and available disk space.

The v2 source contract preserves Bitcoin amounts to six decimal places. Start
with a fresh database for v2; replaying the initialization scripts on a v1
volume will not widen existing amount columns or reclassify rows skipped by the
file manifest. Do not remove a populated volume without preserving its data.

Place IBM `HI-Small_Trans.csv` under `data/raw/`. Use the small fixture first:

```sh
python -m pip install -e ".[dev,orchestration,dbt]"
python -m banking_pipeline.ingest tests/fixtures/clean_pipeline_Trans.csv
python -m banking_pipeline.promote --all
python -m banking_pipeline.analytics
```

For the full data, launch `banking_daily_pipeline` in Dagster or run the three
commands with the real file. A rerun of the same bytes skips the source file.
The source and correction directories are controlled by `BANKING_SOURCE_DIR`
and `BANKING_CORRECTION_DIR`. Compose mounts `data/raw/` and
`data/corrections/` read-only into Dagster. The default source pattern is
`*Trans.csv`; corrections are only loaded from the separate correction folder.
Before the multi-million-row file, check free space on the PostgreSQL volume:
raw JSON, typed staging, fact indexes, WAL, and temporary query files can take
substantially more space than the source CSV. This host did not have enough
free space for a responsible full-source run until space was freed. The
successful full run is recorded under `pipeline/evidence/full_run.json`.

## Full-source scale proof (on a machine with adequate storage)

Use a fresh PostgreSQL database and provision generous free space for the
database, WAL, indexes, and temporary query files (start with at least 20 GiB
free and monitor it; the exact requirement depends on PostgreSQL settings).
Keep the 454 MB IBM source file out of Git. The one-file loader is atomic, so
an interrupted or failed load can be retried without publishing partial rows.

```sh
python -m banking_pipeline.ingest data/raw/HI-Small_Trans.csv
python -m banking_pipeline.promote --all
python -m banking_pipeline.analytics
python scripts/verify_banking_full_run.py --min-source-rows 5000000 \
  --output pipeline/evidence/full_run.json
dbt test --project-dir pipeline/dbt --profiles-dir pipeline/dbt
```

Only commit `pipeline/evidence/full_run.json` after all checks pass and you
confirm that its counts describe this new pipeline, not the older investigation
database. The verifier checks manifest arithmetic, raw/staging/core/risk/mart
counts, file/currency reconciliation, no pending accepted rows, and a caught-up
publication marker. Retain the Dagster run ID, CI URL, and PostgreSQL version
alongside the evidence. The verifier does not itself prove downstream Power BI
refresh or real-world fraud-detection performance.

## Inspect a failure

Check the failed Dagster step and its log, then:

```sql
SELECT * FROM ops.file_manifest ORDER BY file_id DESC LIMIT 10;
SELECT * FROM ops.promotion_failure ORDER BY promotion_failure_id DESC LIMIT 10;
SELECT * FROM ops.analytics_failure ORDER BY analytics_failure_id DESC LIMIT 10;
SELECT * FROM analytics.v_pipeline_health;
SELECT * FROM analytics.file_row_reconciliation WHERE NOT is_balanced;
SELECT * FROM analytics.file_amount_reconciliation
WHERE raw_staging_delta <> 0 OR effective_core_delta <> 0;
```

For a data-quality failure, inspect the affected source file and
`quarantine.rejected_record` rows. The default policy allows at most 5% rejected
rows per affected file. A source exception requires a documented policy change
in `ops.quality_policy`; then rerun the job. No analytics publication occurs
until the gate passes.

For a transient connection or deadlock error, Dagster retries the step up to
three times. A schema, parsing, or quality failure is deterministic and fails
without retry. Ingestion manifests, promotion cursors, and publication markers
make reruns safe. A correction must identify the original `raw_record_id`.

## Backfill and recovery

Use `python -m banking_pipeline.promote --mode backfill --raw-after A
--raw-through B` for an exclusive/inclusive raw ID interval. A backfill never
moves the live cursor. Run `python -m banking_pipeline.analytics` afterward.
The publication function refreshes every affected day, including the old and
new dates of corrected transactions. It updates marts and the publication marker
in one transaction. If it fails, previous published tables remain visible.

The Dagster job does not call Power BI refresh. In Import mode, refresh the
semantic model after a new publication ID appears. That refresh is a downstream
operational step, not part of the database transaction.

## Independent checks

```sh
python -m pytest -q tests/test_banking_*.py
dbt test --project-dir pipeline/dbt --profiles-dir pipeline/dbt
```

The dbt suite assumes promotion and publication have finished. CI runs it
against a separate clean database so deliberately failed quality tests in
pytest cannot contaminate the dbt result.
