"""Atomic, replay-safe CSV ingestion into PostgreSQL raw and quarantine schemas."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import os
from pathlib import Path

from .contract import HEADERS, SCHEMA_VERSION, payload_for, validate_row

log = logging.getLogger("banking_pipeline")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_records(path: Path):
    """Yield physical line number, original CSV text, payload and validation errors.

    IBM's transaction export has one physical line per transaction. A broken CSV
    quote is a file-level failure; wrong-width records are quarantined.
    """
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        header_line = source.readline()
        if not header_line:
            raise ValueError("empty_file")
        header = next(csv.reader([header_line], strict=True))
        if tuple(header) != HEADERS:
            raise ValueError(f"header_mismatch: expected {HEADERS!r}; got {header!r}")
        for row_number, raw_line in enumerate(source, start=2):
            raw_text = raw_line.rstrip("\r\n")
            try:
                values = next(csv.reader([raw_line], strict=True))
            except (csv.Error, StopIteration):
                yield row_number, raw_text, {}, ["malformed_csv"]
                continue
            errors = validate_row(values)
            yield row_number, raw_text, payload_for(values), errors


def _copy_rows(cursor, file_id: int, path: Path, batch_size: int) -> int:
    count = 0
    with cursor.copy("COPY incoming (source_row_number, raw_text, payload, record_hash, reason_codes) FROM STDIN") as copy:
        for row_number, raw_text, payload, errors in parse_records(path):
            canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
            record_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            copy.write_row((row_number, raw_text, json.dumps(payload), record_hash, errors))
            count += 1
            if count % batch_size == 0:
                log.info("chunk_loaded", extra={"file_id": file_id, "rows": count})
    return count


def ingest_file(path: Path, dsn: str, batch_size: int = 10000) -> dict:
    import psycopg

    path = path.resolve()
    if not path.is_file() or path.suffix.lower() != ".csv":
        raise ValueError(f"expected an existing CSV file: {path}")
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    file_hash = sha256_file(path)
    byte_size = path.stat().st_size
    with psycopg.connect(dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_lock(hashtext(%s))", (file_hash,))
        try:
            with conn.transaction():
                row = conn.execute(
                    "SELECT file_id, status FROM ops.file_manifest WHERE sha256 = %s FOR UPDATE",
                    (file_hash,),
                ).fetchone()
                if row and row[1] == "completed":
                    log.info("file_skipped", extra={"file_id": row[0], "sha256": file_hash})
                    return {"status": "skipped", "file_id": row[0], "sha256": file_hash}
                if row:
                    file_id = row[0]
                    conn.execute(
                        "UPDATE ops.file_manifest SET status='started', started_at=now(), error_message=NULL "
                        "WHERE file_id=%s", (file_id,),
                    )
                else:
                    file_id = conn.execute(
                        "INSERT INTO ops.file_manifest "
                        "(source_name, source_path, sha256, byte_size, schema_version, status) "
                        "VALUES ('IBM AML HI-Small', %s, %s, %s, %s, 'started') RETURNING file_id",
                        (str(path), file_hash, byte_size, SCHEMA_VERSION),
                    ).fetchone()[0]
            try:
                with conn.transaction():
                    conn.execute(
                        "CREATE TEMP TABLE incoming (source_row_number BIGINT, raw_text TEXT, "
                        "payload JSONB, record_hash CHAR(64), reason_codes TEXT[]) ON COMMIT DROP"
                    )
                    with conn.cursor() as cur:
                        parsed_count = _copy_rows(cur, file_id, path, batch_size)
                    if path.stat().st_size != byte_size or sha256_file(path) != file_hash:
                        raise RuntimeError("source_file_changed_during_ingestion")
                    # Serialization by file hash prevents competing runs of the same file.
                    # A transaction lock also protects cross-file fingerprint decisions.
                    conn.execute("SELECT pg_advisory_xact_lock(7291942)")
                    conn.execute(
                        "WITH ranked AS ("
                        " SELECT i.*, count(*) FILTER (WHERE cardinality(reason_codes)=0)"
                        " OVER (PARTITION BY record_hash ORDER BY source_row_number) AS duplicate_rank"
                        " FROM incoming i), classified AS ("
                        " SELECT r.*, CASE WHEN cardinality(reason_codes) > 0 THEN 'rejected'"
                        " WHEN duplicate_rank > 1 OR EXISTS ("
                        " SELECT 1 FROM raw.transaction_record old"
                        " WHERE old.record_hash = r.record_hash AND old.validation_status = 'accepted'"
                        " ) THEN 'duplicate_candidate' ELSE 'accepted' END AS status FROM ranked r)"
                        " INSERT INTO raw.transaction_record"
                        " (file_id, source_row_number, raw_text, payload, record_hash, validation_status, reason_codes)"
                        " SELECT %s, source_row_number, raw_text, payload, record_hash, status,"
                        " CASE WHEN status='duplicate_candidate' THEN ARRAY['exact_payload_match']::text[]"
                        " ELSE reason_codes END FROM classified ORDER BY source_row_number",
                        (file_id,),
                    )
                    conn.execute(
                        "INSERT INTO quarantine.rejected_record"
                        " (raw_record_id, file_id, source_row_number, reason_codes, raw_text)"
                        " SELECT raw_record_id, file_id, source_row_number, reason_codes, raw_text"
                        " FROM raw.transaction_record WHERE file_id=%s"
                        " AND validation_status <> 'accepted'", (file_id,),
                    )
                    counts = conn.execute(
                        "SELECT count(*), count(*) FILTER (WHERE validation_status='accepted'),"
                        " count(*) FILTER (WHERE validation_status='rejected'),"
                        " count(*) FILTER (WHERE validation_status='duplicate_candidate')"
                        " FROM raw.transaction_record WHERE file_id=%s", (file_id,),
                    ).fetchone()
                    if counts[0] != parsed_count:
                        raise RuntimeError("raw count does not match parsed count")
                    conn.execute(
                        "UPDATE ops.file_manifest SET status='completed', completed_at=now(),"
                        " total_rows=%s, accepted_rows=%s, rejected_rows=%s, duplicate_candidates=%s"
                        " WHERE file_id=%s", (*counts, file_id),
                    )
                result = {"status": "completed", "file_id": file_id, "sha256": file_hash,
                          "total_rows": counts[0], "accepted_rows": counts[1],
                          "rejected_rows": counts[2], "duplicate_candidates": counts[3]}
                log.info("file_completed", extra=result)
                return result
            except Exception as exc:
                with conn.transaction():
                    conn.execute(
                        "UPDATE ops.file_manifest SET status='failed', error_message=%s WHERE file_id=%s",
                        (str(exc)[:2000], file_id),
                    )
                log.exception("file_failed", extra={"file_id": file_id, "sha256": file_hash})
                raise
        finally:
            conn.execute("SELECT pg_advisory_unlock(hashtext(%s))", (file_hash,))


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        fields = {"level": record.levelname, "event": record.getMessage(),
                  "logger": record.name}
        for name in ("file_id", "sha256", "rows", "total_rows", "accepted_rows",
                     "rejected_rows", "duplicate_candidates", "status"):
            if hasattr(record, name):
                fields[name] = getattr(record, name)
        if record.exc_info:
            fields["exception"] = self.formatException(record.exc_info)
        return json.dumps(fields)


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest IBM AML HI-Small CSV files")
    parser.add_argument("path", type=Path, help="CSV file or directory containing CSV files")
    parser.add_argument("--pattern", default="*Trans.csv",
                        help="glob for directory discovery (default: *Trans.csv)")
    parser.add_argument("--batch-size", type=int, default=10000)
    parser.add_argument("--dsn", default=os.environ.get(
        "BANKING_DATABASE_URL", "postgresql://banking:banking_local_only@localhost:5433/banking_pipeline"))
    args = parser.parse_args()
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    paths = sorted(args.path.glob(args.pattern)) if args.path.is_dir() else [args.path]
    if not paths:
        parser.error("no CSV files found")
    for path in paths:
        result = ingest_file(path, args.dsn, args.batch_size)
        print(json.dumps(result))


if __name__ == "__main__":
    main()
