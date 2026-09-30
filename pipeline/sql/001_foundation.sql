CREATE SCHEMA IF NOT EXISTS ops;
CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS quarantine;

CREATE TABLE IF NOT EXISTS ops.file_manifest (
    file_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_name TEXT NOT NULL,
    source_path TEXT NOT NULL,
    sha256 CHAR(64) NOT NULL UNIQUE,
    byte_size BIGINT NOT NULL CHECK (byte_size >= 0),
    schema_version TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('started', 'completed', 'failed')),
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    total_rows BIGINT NOT NULL DEFAULT 0,
    accepted_rows BIGINT NOT NULL DEFAULT 0,
    rejected_rows BIGINT NOT NULL DEFAULT 0,
    duplicate_candidates BIGINT NOT NULL DEFAULT 0,
    error_message TEXT,
    CHECK (total_rows = accepted_rows + rejected_rows + duplicate_candidates)
);

CREATE TABLE IF NOT EXISTS raw.transaction_record (
    raw_record_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    file_id BIGINT NOT NULL REFERENCES ops.file_manifest(file_id),
    source_row_number BIGINT NOT NULL,
    payload JSONB NOT NULL,
    raw_text TEXT NOT NULL,
    record_hash CHAR(64) NOT NULL,
    validation_status TEXT NOT NULL CHECK (validation_status IN ('accepted', 'rejected', 'duplicate_candidate')),
    reason_codes TEXT[] NOT NULL DEFAULT '{}',
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (file_id, source_row_number)
);

CREATE INDEX IF NOT EXISTS raw_transaction_record_hash_idx
    ON raw.transaction_record(record_hash) WHERE validation_status = 'accepted';
CREATE INDEX IF NOT EXISTS raw_transaction_file_status_idx
    ON raw.transaction_record(file_id, validation_status);

CREATE TABLE IF NOT EXISTS quarantine.rejected_record (
    rejection_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    raw_record_id BIGINT NOT NULL UNIQUE REFERENCES raw.transaction_record(raw_record_id),
    file_id BIGINT NOT NULL REFERENCES ops.file_manifest(file_id),
    source_row_number BIGINT NOT NULL,
    reason_codes TEXT[] NOT NULL,
    raw_text TEXT NOT NULL,
    quarantined_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
