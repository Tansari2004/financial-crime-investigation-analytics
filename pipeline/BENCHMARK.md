# Reproducible local benchmark

The benchmark script generates unique synthetic transactions in a temporary
CSV and requires an **empty, disposable** PostgreSQL database. It times schema
bootstrap, raw ingestion, bounded promotion, and analytics publication
separately. It refuses to run against a database already containing pipeline
schemas. It does not measure Docker startup, file download, or Power BI refresh.

```sh
createdb banking_benchmark
PYTHONPATH=src python scripts/benchmark_banking_pipeline.py \
  --dsn postgresql:///banking_benchmark --rows 50000 --raw-limit 10000
```

Observed on a local macOS host with PostgreSQL 16, Python 3.12, and local SSD
(2026-09-29):

| Stage | Seconds |
| --- | ---: |
| Schema bootstrap | 0.192 |
| Ingest 50,000 rows from a 4,189,438-byte CSV | 5.439 |
| Promote in five 10,000-row batches | 15.024 |
| Refresh, reconcile, quality-gate, and publish | 1.177 |

That run produced 50,000 raw rows, 50,000 core facts, and 50,000 transactions
accounted for in the daily mart, with zero rejected rows, zero duplicate
candidates, and zero file/currency amount mismatches. The stages total about
21.8 seconds, or roughly 2,300 end-to-end rows per second on this particular
host. After adding source-file and event-date indexes, a second 50,000-row run
on the same host took 4.920 seconds to bootstrap, 9.973 to ingest, 21.299 to
promote, and 5.296 to publish (41.488 seconds total). Both runs reconciled
exactly, and the current suite of 24 dbt checks also passes on a published
fixture. This is not an apples-to-apples
index speed comparison: local free space and I/O conditions changed
substantially. These numbers are illustrative, not a throughput guarantee;
storage, indexes, data distribution, and risk-window cardinality all matter.

The full 5,078,345-row IBM file has now completed the new pipeline and passed
the [full-run verifier](evidence/full_run.json) and 24 dbt checks. That report
establishes scale and reconciliation, not a controlled throughput benchmark;
the timings above remain the reproducible performance comparison. The complete
run used 51 promotion batches and refreshed 18 dates into 217,161 daily mart
groups. For performance work at this scale, record `EXPLAIN (ANALYZE, BUFFERS)`
for promotion and daily refresh on a host with ample space. Candidate
optimizations include partitioning raw/fact tables by ingest or event date and
tuning `work_mem` for risk-window queries. These are not prematurely
implemented in the current project.
