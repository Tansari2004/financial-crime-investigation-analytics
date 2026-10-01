CREATE SCHEMA IF NOT EXISTS staging;
CREATE SCHEMA IF NOT EXISTS core;

CREATE TABLE IF NOT EXISTS ops.correction_file_manifest (
    correction_file_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_path TEXT NOT NULL,
    sha256 CHAR(64) NOT NULL UNIQUE,
    byte_size BIGINT NOT NULL CHECK (byte_size >= 0),
    status TEXT NOT NULL CHECK (status IN ('started', 'completed', 'failed')),
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    row_count BIGINT NOT NULL DEFAULT 0,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS raw.transaction_correction (
    correction_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    correction_file_id BIGINT NOT NULL REFERENCES ops.correction_file_manifest(correction_file_id),
    source_row_number BIGINT NOT NULL,
    target_raw_record_id BIGINT NOT NULL REFERENCES raw.transaction_record(raw_record_id),
    payload JSONB NOT NULL,
    raw_text TEXT NOT NULL,
    record_hash CHAR(64) NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (correction_file_id, source_row_number)
);
CREATE INDEX IF NOT EXISTS raw_transaction_correction_target_idx
    ON raw.transaction_correction(target_raw_record_id, correction_id DESC);

CREATE TABLE IF NOT EXISTS staging.transaction_typed (
    raw_record_id BIGINT PRIMARY KEY REFERENCES raw.transaction_record(raw_record_id),
    source_file_id BIGINT NOT NULL REFERENCES ops.file_manifest(file_id),
    event_time TIMESTAMP NOT NULL,
    from_bank_code TEXT NOT NULL,
    from_account_code TEXT NOT NULL,
    to_bank_code TEXT NOT NULL,
    to_account_code TEXT NOT NULL,
    amount_received NUMERIC(24,6) NOT NULL CHECK (amount_received >= 0),
    receiving_currency TEXT NOT NULL,
    amount_paid NUMERIC(24,6) NOT NULL CHECK (amount_paid >= 0),
    payment_currency TEXT NOT NULL,
    payment_format TEXT NOT NULL,
    is_laundering BOOLEAN NOT NULL,
    record_hash CHAR(64) NOT NULL,
    staged_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS staging_transaction_event_time_idx
    ON staging.transaction_typed(event_time);
CREATE INDEX IF NOT EXISTS staging_transaction_source_file_currency_idx
    ON staging.transaction_typed(source_file_id, payment_currency);

CREATE TABLE IF NOT EXISTS staging.transaction_correction_typed (
    correction_id BIGINT PRIMARY KEY REFERENCES raw.transaction_correction(correction_id),
    target_raw_record_id BIGINT NOT NULL REFERENCES raw.transaction_record(raw_record_id),
    event_time TIMESTAMP NOT NULL,
    from_bank_code TEXT NOT NULL,
    from_account_code TEXT NOT NULL,
    to_bank_code TEXT NOT NULL,
    to_account_code TEXT NOT NULL,
    amount_received NUMERIC(24,6) NOT NULL CHECK (amount_received >= 0),
    receiving_currency TEXT NOT NULL,
    amount_paid NUMERIC(24,6) NOT NULL CHECK (amount_paid >= 0),
    payment_currency TEXT NOT NULL,
    payment_format TEXT NOT NULL,
    is_laundering BOOLEAN NOT NULL,
    record_hash CHAR(64) NOT NULL,
    staged_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS staging_correction_target_idx
    ON staging.transaction_correction_typed(target_raw_record_id, correction_id DESC);

CREATE TABLE IF NOT EXISTS core.dim_bank (
    bank_key BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    bank_code TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS core.dim_account (
    account_key BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    bank_key BIGINT NOT NULL REFERENCES core.dim_bank(bank_key),
    account_code TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (bank_key, account_code)
);
CREATE INDEX IF NOT EXISTS core_dim_account_code_idx
    ON core.dim_account(account_code);

CREATE TABLE IF NOT EXISTS core.fact_transaction (
    transaction_key BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_raw_record_id BIGINT NOT NULL UNIQUE REFERENCES raw.transaction_record(raw_record_id),
    source_file_id BIGINT NOT NULL REFERENCES ops.file_manifest(file_id),
    current_correction_id BIGINT REFERENCES raw.transaction_correction(correction_id),
    event_time TIMESTAMP NOT NULL,
    from_account_key BIGINT NOT NULL REFERENCES core.dim_account(account_key),
    to_account_key BIGINT NOT NULL REFERENCES core.dim_account(account_key),
    amount_received NUMERIC(24,6) NOT NULL CHECK (amount_received >= 0),
    receiving_currency TEXT NOT NULL,
    amount_paid NUMERIC(24,6) NOT NULL CHECK (amount_paid >= 0),
    payment_currency TEXT NOT NULL,
    payment_format TEXT NOT NULL,
    is_laundering BOOLEAN NOT NULL,
    first_loaded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS core_fact_transaction_event_time_idx
    ON core.fact_transaction(event_time);
CREATE INDEX IF NOT EXISTS core_fact_transaction_event_date_idx
    ON core.fact_transaction ((event_time::date));
CREATE INDEX IF NOT EXISTS core_fact_transaction_source_file_currency_idx
    ON core.fact_transaction(source_file_id, payment_currency)
    INCLUDE (amount_paid);
CREATE INDEX IF NOT EXISTS core_fact_transaction_from_account_time_idx
    ON core.fact_transaction(from_account_key, event_time);
CREATE INDEX IF NOT EXISTS core_fact_transaction_to_account_time_idx
    ON core.fact_transaction(to_account_key, event_time);

CREATE TABLE IF NOT EXISTS ops.pipeline_state (
    pipeline_name TEXT PRIMARY KEY,
    last_raw_record_id BIGINT NOT NULL DEFAULT 0 CHECK (last_raw_record_id >= 0),
    last_correction_id BIGINT NOT NULL DEFAULT 0 CHECK (last_correction_id >= 0),
    max_event_time TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO ops.pipeline_state (pipeline_name)
VALUES ('transaction_promotion') ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS ops.promotion_run (
    promotion_run_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    mode TEXT NOT NULL CHECK (mode IN ('incremental', 'backfill')),
    raw_from_exclusive BIGINT NOT NULL,
    raw_to_inclusive BIGINT NOT NULL,
    correction_from_exclusive BIGINT NOT NULL,
    correction_to_inclusive BIGINT NOT NULL,
    staged_rows BIGINT NOT NULL,
    fact_inserted_rows BIGINT NOT NULL,
    correction_events BIGINT NOT NULL,
    corrected_transactions BIGINT NOT NULL,
    late_arriving_rows BIGINT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('completed', 'failed')),
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS ops.promotion_failure (
    promotion_failure_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    requested_mode TEXT NOT NULL,
    requested_raw_after BIGINT,
    requested_raw_through BIGINT,
    requested_correction_after BIGINT,
    requested_correction_through BIGINT,
    error_message TEXT NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
