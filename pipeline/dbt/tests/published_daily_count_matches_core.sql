WITH source_count AS (
    SELECT count(*) AS n FROM {{ source('core', 'fact_transaction') }}
), published_count AS (
    SELECT COALESCE(sum(transaction_count), 0) AS n
    FROM {{ source('analytics', 'fact_daily_transaction') }}
)
SELECT source_count.n AS core_count, published_count.n AS daily_count
FROM source_count CROSS JOIN published_count
WHERE source_count.n <> published_count.n
