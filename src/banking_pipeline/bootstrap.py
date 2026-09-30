"""Apply the repository's idempotent PostgreSQL DDL in order."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from .promote import DEFAULT_DSN

SQL_DIR = Path(__file__).resolve().parents[2] / "pipeline" / "sql"


def bootstrap(dsn: str) -> list[str]:
    import psycopg

    files = sorted(SQL_DIR.glob("[0-9][0-9][0-9]_*.sql"))
    if not files:
        raise FileNotFoundError(f"no migrations found in {SQL_DIR}")
    with psycopg.connect(dsn, autocommit=True) as conn:
        for path in files:
            conn.execute(path.read_text(encoding="utf-8"))
    return [path.name for path in files]


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply banking pipeline SQL")
    parser.add_argument("--dsn", default=os.environ.get("BANKING_DATABASE_URL", DEFAULT_DSN))
    args = parser.parse_args()
    for name in bootstrap(args.dsn):
        print(name)


if __name__ == "__main__":
    main()
