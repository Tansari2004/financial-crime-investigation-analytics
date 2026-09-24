-- Read-only descriptive investigation. Run with psql -X -v ON_ERROR_STOP=1.
\pset pager off
\echo '1. Dataset size and observation period'
SELECT COUNT(*) AS transactions, MIN(transaction_time) AS first_seen,
       MAX(transaction_time) AS last_seen FROM transactions;

\echo '2. Synthetic labels: these are answers for evaluation, not model predictions'
SELECT is_laundering, COUNT(*) AS transactions,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 4) AS percentage
FROM transactions GROUP BY is_laundering ORDER BY is_laundering;

\echo '3. Missingness and invalid values'
SELECT COUNT(*) FILTER (WHERE transaction_time IS NULL) AS missing_time,
       COUNT(*) FILTER (WHERE NULLIF(BTRIM(from_bank),'') IS NULL OR NULLIF(BTRIM(from_account),'') IS NULL) AS missing_sender,
       COUNT(*) FILTER (WHERE NULLIF(BTRIM(to_bank),'') IS NULL OR NULLIF(BTRIM(to_account),'') IS NULL) AS missing_receiver,
       COUNT(*) FILTER (WHERE amount_paid IS NULL) AS missing_paid,
       COUNT(*) FILTER (WHERE amount_received IS NULL) AS missing_received,
       COUNT(*) FILTER (WHERE NULLIF(BTRIM(payment_currency),'') IS NULL) AS missing_paid_currency,
       COUNT(*) FILTER (WHERE NULLIF(BTRIM(receiving_currency),'') IS NULL) AS missing_received_currency,
       COUNT(*) FILTER (WHERE NULLIF(BTRIM(payment_format),'') IS NULL) AS missing_format,
       COUNT(*) FILTER (WHERE is_laundering IS NULL OR is_laundering NOT IN (0,1)) AS invalid_label,
       COUNT(*) FILTER (WHERE amount_paid < 0 OR amount_received < 0) AS negative_amounts
FROM transactions;

\echo '4. Payment totals by currency (never add different currencies together)'
SELECT payment_currency, COUNT(*) AS transactions,
       MIN(amount_paid) AS minimum_paid, ROUND(AVG(amount_paid),2) AS average_paid,
       MAX(amount_paid) AS maximum_paid, SUM(amount_paid) AS total_paid
FROM transactions GROUP BY payment_currency ORDER BY transactions DESC;

\echo '5. Payment methods and retrospective label frequency'
SELECT payment_format, COUNT(*) AS transactions,
       COUNT(*) FILTER (WHERE is_laundering=1) AS labelled_laundering,
       ROUND(100.0 * COUNT(*) FILTER (WHERE is_laundering=1) / COUNT(*),4) AS labelled_pct
FROM transactions GROUP BY payment_format ORDER BY transactions DESC;

\echo '6. Highest outgoing USD volume: descriptive, NOT a risk ranking'
SELECT from_bank, from_account, COUNT(*) AS payments,
       COUNT(DISTINCT (to_bank,to_account)) AS distinct_counterparties,
       SUM(amount_paid) AS total_usd_paid, ROUND(AVG(amount_paid),2) AS average_usd_paid
FROM transactions WHERE payment_currency='US Dollar'
GROUP BY from_bank, from_account ORDER BY total_usd_paid DESC, from_bank, from_account LIMIT 10;

\echo '7. Busiest sender hours: review indicator, not proof of laundering'
SELECT from_bank, from_account, DATE_TRUNC('hour',transaction_time) AS activity_hour,
       COUNT(*) AS payments
FROM transactions GROUP BY from_bank, from_account, DATE_TRUNC('hour',transaction_time)
ORDER BY payments DESC, from_bank, from_account, activity_hour LIMIT 10;

\echo '8. USD payments relative to strictly earlier sender-day history'
-- Daily aggregation bounds the work. Exclude the current day to prevent future leakage.
-- Same bank+account+currency. This excludes intraday earlier transactions deliberately.
WITH daily AS (
 SELECT from_bank, from_account, transaction_time::date AS activity_day,
        COUNT(*) AS n, SUM(amount_paid) AS total
 FROM transactions WHERE payment_currency='US Dollar'
 GROUP BY from_bank, from_account, transaction_time::date
), history AS (
 SELECT *, SUM(total) OVER prior / NULLIF(SUM(n) OVER prior,0) AS prior_day_average,
           SUM(n) OVER prior AS prior_payments
 FROM daily WINDOW prior AS (
 PARTITION BY from_bank,from_account ORDER BY activity_day
 ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING)
)
SELECT t.transaction_id, t.from_bank, t.from_account, t.transaction_time,
       t.amount_paid, ROUND(h.prior_day_average,2) AS prior_usd_average,
       ROUND(t.amount_paid / h.prior_day_average,2) AS amount_multiple,
       h.prior_payments
FROM transactions t JOIN history h
 ON t.from_bank=h.from_bank AND t.from_account=h.from_account
 AND t.transaction_time::date=h.activity_day
WHERE t.payment_currency='US Dollar' AND h.prior_payments >= 10 AND h.prior_day_average > 0
ORDER BY amount_multiple DESC, t.transaction_id LIMIT 10;
