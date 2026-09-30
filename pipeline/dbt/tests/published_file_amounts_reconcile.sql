SELECT file_id, payment_currency
FROM {{ source('analytics', 'file_amount_reconciliation') }}
WHERE raw_staging_delta <> 0 OR effective_core_delta <> 0
