"""Run a bounded, repeatable end-to-end benchmark in a disposable database."""

from __future__ import annotations

import argparse
import csv
import json
import os
import tempfile
from pathlib import Path
from time import perf_counter

import psycopg

from banking_pipeline.analytics import publish
from banking_pipeline.bootstrap import bootstrap
from banking_pipeline.contract import HEADERS
from banking_pipeline.ingest import ingest_file
from banking_pipeline.promote import promote


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn", default=os.environ.get("BANKING_BENCHMARK_DATABASE_URL"))
    parser.add_argument("--rows", type=int, default=50000)
    parser.add_argument("--raw-limit", type=int, default=10000)
    args = parser.parse_args()
    if not args.dsn:
        parser.error("set --dsn to a disposable, empty PostgreSQL database")
    if args.rows <= 0 or args.raw_limit <= 0:
        parser.error("--rows and --raw-limit must be positive")
    with psycopg.connect(args.dsn) as conn:
        schemas = conn.execute(
            "SELECT count(*) FROM information_schema.schemata "
            "WHERE schema_name IN ('raw','core','analytics')"
        ).fetchone()[0]
        if schemas:
            parser.error("benchmark database must be empty")

    with tempfile.TemporaryDirectory(prefix="banking_benchmark_") as directory:
        source = Path(directory) / "benchmark_Trans.csv"
        with source.open("w", newline="", encoding="utf-8") as output:
            writer = csv.writer(output)
            writer.writerow(HEADERS)
            for n in range(args.rows):
                day = 1 + n // 10000
                second_of_day = n % 10000
                hour, remainder = divmod(second_of_day, 3600)
                minute, second = divmod(remainder, 60)
                amount = f"{(n % 1000) + 1}.00"
                writer.writerow([
                    f"2022-09-{day:02d} {hour:02d}:{minute:02d}:{second:02d}",
                    "001", f"A{n % 1000:05d}", "002", f"B{n % 1000:05d}",
                    amount, "US Dollar", amount, "US Dollar", "Wire", "0",
                ])
        sizes = {"source_bytes": source.stat().st_size}
        timings = {}
        start = perf_counter()
        bootstrap(args.dsn)
        timings["bootstrap_seconds"] = round(perf_counter() - start, 3)
        start = perf_counter()
        ingest = ingest_file(source, args.dsn)
        timings["ingest_seconds"] = round(perf_counter() - start, 3)
        start = perf_counter()
        batches = 0
        while True:
            result = promote(args.dsn, raw_limit=args.raw_limit)
            if result["status"] == "skipped":
                break
            batches += 1
        timings["promotion_seconds"] = round(perf_counter() - start, 3)
        start = perf_counter()
        publication = publish(args.dsn)
        timings["publication_seconds"] = round(perf_counter() - start, 3)
        with psycopg.connect(args.dsn) as conn:
            counts = conn.execute(
                "SELECT (SELECT count(*) FROM raw.transaction_record), "
                "(SELECT count(*) FROM core.fact_transaction), "
                "(SELECT COALESCE(sum(transaction_count),0) "
                " FROM analytics.fact_daily_transaction), "
                "(SELECT count(*) FROM analytics.file_amount_reconciliation "
                " WHERE raw_staging_delta<>0 OR effective_core_delta<>0)"
            ).fetchone()
        print(json.dumps({
            "rows_requested": args.rows, "raw_limit": args.raw_limit,
            "promotion_batches": batches, "timings": timings,
            "source": sizes, "ingest": ingest, "publication": publication,
            "raw_rows": counts[0], "core_rows": counts[1],
            "daily_mart_transaction_count": int(counts[2]),
            "amount_mismatches": counts[3],
        }, indent=2))


if __name__ == "__main__":
    main()
