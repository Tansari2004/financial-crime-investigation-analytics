# Full-source evidence

`full_run.json` is the independently generated report for the new banking
pipeline's complete IBM HI-Small transaction file. It was produced from a
fresh PostgreSQL 16 database after raw ingestion, 51 bounded promotion batches,
and atomic analytics publication on September 30, 2026. All 24 dbt checks also
passed against this full published database, as did the 11-test Python suite
against a separate fresh test database.

The 5,078,345 source rows resolve to 5,078,336 accepted transactions and nine
exact-payload duplicate candidates, with zero invalid rejects. Raw, staging,
core, risk, and the daily mart reconcile at their documented grains. The JSON
records the source SHA-256 and schema version. This is evidence for this new
pipeline, not a copied count from the older investigation database.

The source CSV and database remain local and are not committed. Reproduce the
run using `pipeline/RUNBOOK.md` and compare the source checksum and checks.
