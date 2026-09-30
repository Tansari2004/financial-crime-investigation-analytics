WITH daily AS (
    SELECT event_date, payment_currency,
           sum(transaction_count) AS transaction_count,
           sum(labelled_laundering_count) AS synthetic_label_count,
           sum(risk_alert_count) AS alert_count
    FROM {{ source('analytics', 'fact_daily_transaction') }}
    GROUP BY event_date, payment_currency
), evaluation AS (
    SELECT event_date, payment_currency, transaction_count,
           synthetic_label_count, alert_count,
           labelled_alert_count, unlabelled_alert_count, missed_label_count
    FROM analytics.v_risk_evaluation
)
SELECT COALESCE(d.event_date, e.event_date) AS event_date,
       COALESCE(d.payment_currency, e.payment_currency) AS payment_currency
FROM daily d
FULL JOIN evaluation e
  ON e.event_date = d.event_date AND e.payment_currency = d.payment_currency
WHERE COALESCE(d.transaction_count, -1) <> COALESCE(e.transaction_count, -1)
   OR COALESCE(d.synthetic_label_count, -1) <> COALESCE(e.synthetic_label_count, -1)
   OR COALESCE(d.alert_count, -1) <> COALESCE(e.alert_count, -1)
   OR e.alert_count <> e.labelled_alert_count + e.unlabelled_alert_count
   OR e.synthetic_label_count <> e.labelled_alert_count + e.missed_label_count
