WITH expected AS (
    SELECT file_id, payload->>'payment_currency' AS payment_currency
    FROM raw.transaction_record WHERE validation_status = 'accepted'
    UNION
    SELECT source_file_id, payment_currency FROM staging.transaction_typed
    UNION
    SELECT s.source_file_id, c.payment_currency
    FROM staging.transaction_correction_typed c
    JOIN staging.transaction_typed s ON s.raw_record_id = c.target_raw_record_id
    UNION
    SELECT source_file_id, payment_currency FROM {{ source('core', 'fact_transaction') }}
), reconciled AS (
    SELECT * FROM {{ source('analytics', 'file_amount_reconciliation') }}
)
SELECT COALESCE(e.file_id, r.file_id) AS file_id,
       COALESCE(e.payment_currency, r.payment_currency) AS payment_currency
FROM expected e FULL JOIN reconciled r
  ON r.file_id = e.file_id AND r.payment_currency = e.payment_currency
WHERE e.file_id IS NULL OR r.file_id IS NULL
   OR r.raw_staging_delta <> 0 OR r.effective_core_delta <> 0
