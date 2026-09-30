WITH source_count AS (
    SELECT count(*) AS n FROM {{ source('core', 'fact_transaction') }}
), published_count AS (
    SELECT count(*) AS n FROM {{ source('analytics', 'fact_risk_signal') }}
)
SELECT source_count.n AS core_count, published_count.n AS risk_count
FROM source_count CROSS JOIN published_count
WHERE source_count.n <> published_count.n
