"""Refresh curated analytics and publish only after database quality gates pass."""

from __future__ import annotations

import argparse
import json
import os

from .promote import DEFAULT_DSN


def publish(dsn: str) -> dict:
    import psycopg

    with psycopg.connect(dsn, autocommit=True) as conn:
        try:
            return conn.execute("SELECT analytics.refresh_and_publish()").fetchone()[0]
        except Exception as exc:
            try:
                conn.execute(
                    "INSERT INTO ops.analytics_failure (error_message) VALUES (%s)",
                    (str(exc)[:2000],),
                )
            except Exception:
                pass
            raise


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh and quality-gate analytics")
    parser.add_argument("--dsn", default=os.environ.get("BANKING_DATABASE_URL", DEFAULT_DSN))
    args = parser.parse_args()
    print(json.dumps(publish(args.dsn), sort_keys=True))


if __name__ == "__main__":
    main()
