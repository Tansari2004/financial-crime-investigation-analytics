"""Promote accepted raw events into typed staging and canonical core tables."""

from __future__ import annotations

import argparse
import json
import os


DEFAULT_DSN = "postgresql://banking:banking_local_only@localhost:5433/banking_pipeline"


def promote(
    dsn: str,
    *,
    mode: str = "incremental",
    raw_after: int | None = None,
    raw_through: int | None = None,
    correction_after: int | None = None,
    correction_through: int | None = None,
    raw_limit: int = 100000,
    correction_limit: int = 10000,
) -> dict:
    import psycopg

    with psycopg.connect(dsn, autocommit=True) as conn:
        try:
            return conn.execute(
                "SELECT core.promote_transactions(%s, %s, %s, %s, %s, %s, %s)",
                (mode, raw_after, raw_through, correction_after, correction_through,
                 raw_limit, correction_limit),
            ).fetchone()[0]
        except Exception as exc:
            try:
                conn.execute(
                    "INSERT INTO ops.promotion_failure "
                    "(requested_mode, requested_raw_after, requested_raw_through, "
                    "requested_correction_after, requested_correction_through, error_message) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    (mode, raw_after, raw_through, correction_after,
                     correction_through, str(exc)[:2000]),
                )
            except Exception:
                # Keep the original failure if the database is unavailable.
                pass
            raise


def main() -> None:
    parser = argparse.ArgumentParser(description="Promote IBM AML raw transactions")
    parser.add_argument("--dsn", default=os.environ.get("BANKING_DATABASE_URL", DEFAULT_DSN))
    parser.add_argument("--mode", choices=("incremental", "backfill"), default="incremental")
    parser.add_argument("--raw-after", type=int)
    parser.add_argument("--raw-through", type=int)
    parser.add_argument("--correction-after", type=int)
    parser.add_argument("--correction-through", type=int)
    parser.add_argument("--raw-limit", type=int, default=100000)
    parser.add_argument("--correction-limit", type=int, default=10000)
    parser.add_argument("--all", action="store_true", help="run incremental batches until caught up")
    args = parser.parse_args()
    if args.all and args.mode != "incremental":
        parser.error("--all applies only to incremental mode")
    if args.mode == "backfill" and not (args.raw_through is not None or
                                         args.correction_through is not None):
        parser.error("backfill requires --raw-through or --correction-through")
    while True:
        result = promote(
            args.dsn, mode=args.mode, raw_after=args.raw_after,
            raw_through=args.raw_through, correction_after=args.correction_after,
            correction_through=args.correction_through, raw_limit=args.raw_limit,
            correction_limit=args.correction_limit,
        )
        print(json.dumps(result, sort_keys=True))
        if not args.all or result["status"] == "skipped":
            break


if __name__ == "__main__":
    main()
