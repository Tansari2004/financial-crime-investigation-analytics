-- Point-in-time transaction features for the logistic-regression baseline.
-- Run once after loading transactions. It intentionally refuses to overwrite
-- an existing feature table.
CREATE TABLE model_features AS
WITH daily AS (
    SELECT
        from_bank,
        from_account,
        payment_currency,
        transaction_time::date AS activity_day,
        COUNT(*) AS daily_transactions,
        SUM(amount_paid) AS daily_amount
    FROM transactions
    GROUP BY from_bank, from_account, payment_currency, transaction_time::date
),
history AS (
    SELECT
        from_bank,
        from_account,
        payment_currency,
        activity_day,
        SUM(daily_transactions) OVER prior_days AS prior_transaction_count,
        SUM(daily_amount) OVER prior_days AS prior_amount_total
    FROM daily
    WINDOW prior_days AS (
        PARTITION BY from_bank, from_account, payment_currency
        ORDER BY activity_day
        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
    )
)
SELECT
    t.transaction_id,
    t.transaction_time,
    t.amount_paid::double precision AS amount_paid,
    t.payment_currency,
    t.receiving_currency,
    t.payment_format,
    (t.from_bank = t.to_bank)::integer AS same_bank,
    (t.from_bank = t.to_bank AND t.from_account = t.to_account)::integer AS self_transfer,
    EXTRACT(HOUR FROM t.transaction_time)::integer AS transaction_hour,
    EXTRACT(ISODOW FROM t.transaction_time)::integer AS transaction_weekday,
    COALESCE(h.prior_transaction_count, 0)::double precision AS prior_transaction_count,
    CASE
        WHEN h.prior_transaction_count > 0
        THEN (h.prior_amount_total / h.prior_transaction_count)::double precision
        ELSE 0
    END AS prior_average_amount,
    CASE WHEN h.prior_transaction_count > 0 THEN 1 ELSE 0 END AS has_prior_history,
    t.is_laundering
FROM transactions t
LEFT JOIN history h
  ON t.from_bank = h.from_bank
 AND t.from_account = h.from_account
 AND t.payment_currency = h.payment_currency
 AND t.transaction_time::date = h.activity_day;

ALTER TABLE model_features ADD PRIMARY KEY (transaction_id);
CREATE INDEX model_features_time_idx ON model_features (transaction_time);
ANALYZE model_features;

-- Export from psql after creation:
-- \copy model_features TO 'data/processed/model_features.csv' WITH (FORMAT csv, HEADER true)
