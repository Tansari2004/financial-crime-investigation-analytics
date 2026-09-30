"""Append explicit source corrections without changing immutable original rows."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path

from .contract import HEADERS, payload_for, validate_row
from .ingest import log, sha256_file

CORRECTION_HEADER = ("Target Raw Record ID",) + HEADERS


def parse_corrections(path: Path):
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        header_line = source.readline()
        if not header_line:
            raise ValueError("empty_correction_file")
        header = next(csv.reader([header_line], strict=True))
        if tuple(header) != CORRECTION_HEADER:
            raise ValueError("correction_header_mismatch")
        for row_number, raw_line in enumerate(source, start=2):
            try:
                values = next(csv.reader([raw_line], strict=True))
            except (csv.Error, StopIteration) as exc:
                raise ValueError(f"correction row {row_number}: malformed_csv") from exc
            if len(values) != len(CORRECTION_HEADER):
                raise ValueError(f"correction row {row_number}: wrong_column_count")
            try:
                target_id = int(values[0])
            except ValueError as exc:
                raise ValueError(f"correction row {row_number}: invalid_target_id") from exc
            if target_id <= 0:
                raise ValueError(f"correction row {row_number}: invalid_target_id")
            errors = validate_row(values[1:])
            if errors:
                raise ValueError(f"correction row {row_number}: {','.join(errors)}")
            payload = payload_for(values[1:])
            yield row_number, raw_line.rstrip("\r\n"), target_id, payload


def ingest_corrections(path: Path, dsn: str) -> dict:
    import psycopg

    path = path.resolve()
    if not path.is_file() or path.suffix.lower() != ".csv":
        raise ValueError(f"expected an existing correction CSV: {path}")
    file_hash = sha256_file(path)
    byte_size = path.stat().st_size
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("SELECT pg_advisory_lock(hashtext(%s))", (file_hash,))
        try:
            with conn.transaction():
                existing = conn.execute(
                    "SELECT correction_file_id, status FROM ops.correction_file_manifest "
                    "WHERE sha256=%s FOR UPDATE", (file_hash,),
                ).fetchone()
                if existing and existing[1] == "completed":
                    return {"status": "skipped", "correction_file_id": existing[0],
                            "sha256": file_hash}
                if existing:
                    file_id = existing[0]
                    conn.execute(
                        "UPDATE ops.correction_file_manifest SET status='started', "
                        "started_at=now(), error_message=NULL WHERE correction_file_id=%s",
                        (file_id,),
                    )
                else:
                    file_id = conn.execute(
                        "INSERT INTO ops.correction_file_manifest "
                        "(source_path, sha256, byte_size, status) "
                        "VALUES (%s, %s, %s, 'started') RETURNING correction_file_id",
                        (str(path), file_hash, byte_size),
                    ).fetchone()[0]
            try:
                with conn.transaction():
                    conn.execute(
                        "CREATE TEMP TABLE incoming_corrections "
                        "(source_row_number BIGINT, raw_text TEXT, target_raw_record_id BIGINT, "
                        "payload JSONB, record_hash CHAR(64)) ON COMMIT DROP"
                    )
                    row_count = 0
                    with conn.cursor() as cur:
                        with cur.copy(
                            "COPY incoming_corrections "
                            "(source_row_number, raw_text, target_raw_record_id, payload, record_hash) "
                            "FROM STDIN"
                        ) as copy:
                            for row_number, raw_text, target_id, payload in parse_corrections(path):
                                canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
                                record_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
                                copy.write_row((row_number, raw_text, target_id,
                                                json.dumps(payload), record_hash))
                                row_count += 1
                    if path.stat().st_size != byte_size or sha256_file(path) != file_hash:
                        raise RuntimeError("correction_file_changed_during_ingestion")
                    # Shared with base ingestion and promotion: commit-order cursor safety.
                    conn.execute("SELECT pg_advisory_xact_lock(7291942)")
                    invalid_target = conn.execute(
                        "SELECT i.target_raw_record_id FROM incoming_corrections i "
                        "LEFT JOIN raw.transaction_record r "
                        "ON r.raw_record_id=i.target_raw_record_id "
                        "WHERE r.raw_record_id IS NULL OR r.validation_status <> 'accepted' "
                        "LIMIT 1"
                    ).fetchone()
                    if invalid_target:
                        raise ValueError(f"correction_target_not_accepted: {invalid_target[0]}")
                    conn.execute(
                        "INSERT INTO raw.transaction_correction "
                        "(correction_file_id, source_row_number, target_raw_record_id, "
                        "payload, raw_text, record_hash) "
                        "SELECT %s, source_row_number, target_raw_record_id, "
                        "payload, raw_text, record_hash FROM incoming_corrections "
                        "ORDER BY source_row_number", (file_id,),
                    )
                    inserted = conn.execute(
                        "SELECT count(*) FROM raw.transaction_correction "
                        "WHERE correction_file_id=%s", (file_id,),
                    ).fetchone()[0]
                    if inserted != row_count:
                        raise RuntimeError("correction count does not match parsed count")
                    conn.execute(
                        "UPDATE ops.correction_file_manifest SET status='completed', "
                        "completed_at=now(), row_count=%s WHERE correction_file_id=%s",
                        (row_count, file_id),
                    )
                result = {"status": "completed", "correction_file_id": file_id,
                          "sha256": file_hash, "row_count": row_count}
                log.info("correction_file_completed", extra={"file_id": file_id,
                                                              "rows": row_count})
                return result
            except Exception as exc:
                with conn.transaction():
                    conn.execute(
                        "UPDATE ops.correction_file_manifest SET status='failed', "
                        "error_message=%s WHERE correction_file_id=%s",
                        (str(exc)[:2000], file_id),
                    )
                raise
        finally:
            conn.execute("SELECT pg_advisory_unlock(hashtext(%s))", (file_hash,))


def main() -> None:
    parser = argparse.ArgumentParser(description="Load explicit IBM AML corrections")
    parser.add_argument("path", type=Path)
    parser.add_argument("--dsn", default=os.environ.get(
        "BANKING_DATABASE_URL", "postgresql://banking:banking_local_only@localhost:5433/banking_pipeline"))
    args = parser.parse_args()
    print(json.dumps(ingest_corrections(args.path, args.dsn), sort_keys=True))


if __name__ == "__main__":
    main()
