"""Bounded-space decimal rebuild, matching the PostgreSQL feature SQL.

Use when the full PostgreSQL import would exceed local disk capacity. This is
not evidence of a full PostgreSQL rebuild. DuckDB reads original decimal text,
then exports the same modelling features; PostgreSQL remains the primary schema.
"""
import argparse
import csv
from decimal import Decimal
import json
from pathlib import Path

import duckdb

from financial_crime.train_model import file_sha256

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    features = args.output / "model_features.csv.gz"
    evidence = args.output / "precision_import.json"
    if features.exists() or evidence.exists():
        raise ValueError("Use a new output directory")
    count = changed_paid = changed_received = 0
    # Reject any input beyond the declared decimal capacity BEFORE the engine
    # can round it. Decimal is only used here to validate exact source precision.
    with args.source.open(newline="") as stream:
        rows = csv.reader(stream)
        next(rows)
        for row in rows:
            count += 1
            for index in (5, 7):
                amount = Decimal(row[index])
                if not amount.is_finite() or amount < 0 or amount.as_tuple().exponent < -12 or amount.adjusted() >= 26:
                    raise ValueError("Source amount exceeds exact DECIMAL(38,12) capacity")
            changed_received += Decimal(row[5]) != Decimal(row[5]).quantize(Decimal('.01'))
            changed_paid += Decimal(row[7]) != Decimal(row[7]).quantize(Decimal('.01'))
    columns = {'transaction_time': 'TIMESTAMP', 'from_bank': 'VARCHAR', 'from_account': 'VARCHAR',
               'to_bank': 'VARCHAR', 'to_account': 'VARCHAR', 'amount_received': 'DECIMAL(38,12)',
               'receiving_currency': 'VARCHAR', 'amount_paid': 'DECIMAL(38,12)', 'payment_currency': 'VARCHAR',
               'payment_format': 'VARCHAR', 'is_laundering': 'SMALLINT'}
    con = duckdb.connect()
    con.execute("SET memory_limit='1250MB'")
    con.execute("SET threads=1")
    con.execute("SET max_temp_directory_size='200MB'")
    con.execute("SET temp_directory=?", [str(args.output / 'temporary')])
    # Supplied names map the eleven source columns by position, as COPY does.
    source_literal = "'" + str(args.source.resolve()).replace("'", "''") + "'"
    con.execute(f"CREATE VIEW transactions AS SELECT row_number() OVER () AS transaction_id,* FROM read_csv({source_literal},header=true,columns={columns!r},timestampformat='%Y/%m/%d %H:%M')")
    query = (ROOT / "sql/model_features.sql").read_text()
    query = query[query.index("WITH daily AS"):query.index("ALTER TABLE")].strip().rstrip(';')
    # DuckDB decimal division returns double; carry the exact decimal sum to
    # the division, matching the final double feature within numerical tolerance.
    con.execute(f"COPY ({query} ORDER BY transaction_id) TO ? (FORMAT CSV, HEADER TRUE, COMPRESSION GZIP)", [str(features)])
    con.close()
    result = {"source_sha256": file_sha256(args.source), "source_bytes": args.source.stat().st_size,
              "rows": count, "paid_rows_with_more_than_two_decimal_precision": changed_paid,
              "received_rows_with_more_than_two_decimal_precision": changed_received,
              "import_amount_type": "DuckDB DECIMAL(38,12), all source values prevalidated as exactly representable",
              "features_amount_type": "double precision for modelling only",
              "engine": duckdb.__version__, "full_postgresql_rebuild": False,
              "features_sha256": file_sha256(features)}
    evidence.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__': main()
