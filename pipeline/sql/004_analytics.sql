CREATE SCHEMA IF NOT EXISTS analytics;

CREATE TABLE IF NOT EXISTS analytics.fact_risk_signal (
    transaction_key BIGINT PRIMARY KEY REFERENCES core.fact_transaction(transaction_key),
    source_raw_record_id BIGINT NOT NULL,
    event_time TIMESTAMP NOT NULL,
    event_date DATE NOT NULL,
    from_bank_code TEXT NOT NULL,
    from_account_code TEXT NOT NULL,
    to_bank_code TEXT NOT NULL,
    to_account_code TEXT NOT NULL,
    amount_paid NUMERIC(20,2) NOT NULL,
    payment_currency TEXT NOT NULL,
    payment_format TEXT NOT NULL,
    high_amount_for_currency_day BOOLEAN NOT NULL,
    high_hourly_velocity BOOLEAN NOT NULL,
    repeated_counterparty BOOLEAN NOT NULL,
    risk_score SMALLINT NOT NULL CHECK (risk_score BETWEEN 0 AND 5),
    is_laundering BOOLEAN NOT NULL,
    current_correction_id BIGINT,
    refreshed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS analytics_risk_date_score_idx
    ON analytics.fact_risk_signal(event_date, risk_score DESC);

CREATE TABLE IF NOT EXISTS analytics.fact_daily_transaction (
    event_date DATE NOT NULL,
    from_bank_key BIGINT NOT NULL REFERENCES core.dim_bank(bank_key),
    payment_currency TEXT NOT NULL,
    payment_format TEXT NOT NULL,
    transaction_count BIGINT NOT NULL CHECK (transaction_count >= 0),
    paid_amount NUMERIC(38,2) NOT NULL,
    labelled_laundering_count BIGINT NOT NULL,
    risk_alert_count BIGINT NOT NULL,
    refreshed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (event_date, from_bank_key, payment_currency, payment_format)
);
CREATE INDEX IF NOT EXISTS analytics_daily_currency_date_idx
    ON analytics.fact_daily_transaction(payment_currency, event_date);

CREATE TABLE IF NOT EXISTS analytics.file_row_reconciliation (
    file_id BIGINT PRIMARY KEY REFERENCES ops.file_manifest(file_id),
    manifest_total BIGINT NOT NULL,
    manifest_accepted BIGINT NOT NULL,
    manifest_rejected BIGINT NOT NULL,
    manifest_duplicate_candidates BIGINT NOT NULL,
    raw_total BIGINT NOT NULL,
    raw_accepted BIGINT NOT NULL,
    raw_rejected BIGINT NOT NULL,
    raw_duplicate_candidates BIGINT NOT NULL,
    staged_count BIGINT NOT NULL,
    core_count BIGINT NOT NULL,
    is_balanced BOOLEAN NOT NULL,
    checked_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS analytics.file_amount_reconciliation (
    file_id BIGINT NOT NULL REFERENCES ops.file_manifest(file_id),
    payment_currency TEXT NOT NULL,
    raw_original_paid NUMERIC(38,2) NOT NULL,
    staged_original_paid NUMERIC(38,2) NOT NULL,
    expected_current_paid NUMERIC(38,2) NOT NULL,
    core_paid NUMERIC(38,2) NOT NULL,
    raw_staging_delta NUMERIC(38,2) NOT NULL,
    effective_core_delta NUMERIC(38,2) NOT NULL,
    checked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (file_id, payment_currency)
);

CREATE TABLE IF NOT EXISTS analytics.publication_state (
    state_id SMALLINT PRIMARY KEY DEFAULT 1 CHECK (state_id = 1),
    last_promotion_run_id BIGINT NOT NULL DEFAULT 0,
    last_file_id BIGINT NOT NULL DEFAULT 0,
    last_publication_id BIGINT,
    published_at TIMESTAMPTZ
);
INSERT INTO analytics.publication_state (state_id) VALUES (1)
ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS analytics.publication_run (
    publication_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    through_promotion_run_id BIGINT NOT NULL,
    through_file_id BIGINT NOT NULL,
    affected_days BIGINT NOT NULL,
    affected_files BIGINT NOT NULL,
    refreshed_risk_rows BIGINT NOT NULL,
    refreshed_daily_rows BIGINT NOT NULL,
    status TEXT NOT NULL CHECK (status = 'published'),
    published_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ops.analytics_failure (
    analytics_failure_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    error_message TEXT NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ops.quality_policy (
    policy_name TEXT PRIMARY KEY,
    max_rejected_fraction NUMERIC(5,4) NOT NULL
        CHECK (max_rejected_fraction BETWEEN 0 AND 1)
);
INSERT INTO ops.quality_policy (policy_name, max_rejected_fraction)
VALUES ('transaction_files', 0.05) ON CONFLICT DO NOTHING;

CREATE OR REPLACE VIEW analytics.v_daily_metrics AS
SELECT d.event_date, b.bank_code AS from_bank_code,
       d.payment_currency, d.payment_format, d.transaction_count,
       d.paid_amount, d.labelled_laundering_count, d.risk_alert_count,
       d.refreshed_at
FROM analytics.fact_daily_transaction d
JOIN core.dim_bank b ON b.bank_key = d.from_bank_key;

CREATE OR REPLACE VIEW analytics.v_risk_alert AS
SELECT s.transaction_key, s.source_raw_record_id, s.event_time,
       s.event_date, s.from_bank_code, s.from_account_code,
       s.to_bank_code, s.to_account_code,
       s.amount_paid, s.payment_currency, s.payment_format,
       s.high_amount_for_currency_day, s.high_hourly_velocity,
       s.repeated_counterparty, s.risk_score, s.is_laundering,
       s.current_correction_id
FROM analytics.fact_risk_signal s
WHERE s.risk_score >= 2;

CREATE OR REPLACE VIEW analytics.v_risk_evaluation AS
SELECT event_date, payment_currency,
       count(*) AS transaction_count,
       count(*) FILTER (WHERE is_laundering) AS synthetic_label_count,
       count(*) FILTER (WHERE risk_score >= 2) AS alert_count,
       count(*) FILTER (WHERE risk_score >= 2 AND is_laundering) AS labelled_alert_count,
       count(*) FILTER (WHERE risk_score >= 2 AND NOT is_laundering) AS unlabelled_alert_count,
       count(*) FILTER (WHERE risk_score < 2 AND is_laundering) AS missed_label_count
FROM analytics.fact_risk_signal
GROUP BY event_date, payment_currency;

CREATE OR REPLACE VIEW analytics.v_pipeline_health AS
SELECT p.published_at, p.last_publication_id,
       p.last_promotion_run_id, s.last_raw_record_id,
       s.last_correction_id, s.max_event_time,
       (SELECT count(*) FROM analytics.file_row_reconciliation
        WHERE NOT is_balanced) AS imbalanced_files,
       (SELECT count(*) FROM ops.file_manifest
        WHERE status = 'failed') AS failed_files,
       (SELECT max(occurred_at) FROM ops.analytics_failure) AS last_analytics_failure
FROM analytics.publication_state p
CROSS JOIN ops.pipeline_state s
WHERE p.state_id = 1 AND s.pipeline_name = 'transaction_promotion';
