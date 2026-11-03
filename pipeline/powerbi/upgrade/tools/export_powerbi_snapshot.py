"""Export a complete, identifier-free Power BI snapshot in one read-only transaction.

The source database is untouched. Source account/bank identifiers are not exported.
The detail table is a balanced, explicitly bounded sample; all KPIs use full facts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


SQL = r"""
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout = '300s';
SET LOCAL TIME ZONE 'UTC';
WITH daily AS (
 SELECT event_date,payment_currency,payment_format,
   sum(transaction_count)::bigint AS transaction_count,
   sum(risk_alert_count)::bigint AS risk_alert_count,
   sum(labelled_laundering_count)::bigint AS labelled_laundering_count
 FROM analytics.v_daily_metrics GROUP BY event_date,payment_currency,payment_format
), flags AS (
 SELECT event_date, payment_currency, payment_format,
        count(*) FILTER (WHERE high_amount_for_currency_day) AS amount_hits,
        count(*) FILTER (WHERE high_hourly_velocity) AS velocity_hits,
        count(*) FILTER (WHERE repeated_counterparty) AS counterparty_hits
 FROM analytics.fact_risk_signal
 GROUP BY event_date, payment_currency, payment_format
), sample_rank AS (
 SELECT a.*, row_number() OVER (
   PARTITION BY event_date,payment_currency
   ORDER BY risk_score DESC,event_time,transaction_key) AS sample_rank
 FROM analytics.v_risk_alert a
), detail AS (
 SELECT a.* FROM sample_rank a WHERE sample_rank<=3
)
SELECT json_build_object(
 'publication', (SELECT row_to_json(p) FROM (
   SELECT last_publication_id AS publication_id,
          to_char(published_at,'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS published_at_utc
   FROM analytics.publication_state WHERE state_id=1) p),
 'daily_columns', ARRAY['Date','Currency','Payment format','Transactions',
   'Alerts','Synthetic labels','High amount hits','High velocity hits','Repeat counterparty hits'],
 'daily', (SELECT json_agg(json_build_array(d.event_date,d.payment_currency,
     d.payment_format,d.transaction_count,d.risk_alert_count,d.labelled_laundering_count,
     f.amount_hits,f.velocity_hits,f.counterparty_hits)
   ORDER BY d.event_date,d.payment_currency,d.payment_format)
   FROM daily d JOIN flags f USING(event_date,payment_currency,payment_format)),
 'file_columns', ARRAY['File key','Source rows','Accepted rows','Rejected rows',
    'Duplicate candidates','Raw rows','Staged rows','Published rows','Row balance OK'],
 'files', (SELECT json_agg(json_build_array(file_id,manifest_total,manifest_accepted,
   manifest_rejected,manifest_duplicate_candidates,raw_total,staged_count,core_count,
   is_balanced) ORDER BY file_id) FROM analytics.file_row_reconciliation),
 'reconciliation_columns', ARRAY['File key','Currency','Raw source total','Staged total',
   'Expected current total','Published total','Raw staging delta','Effective core delta',
   'Failure count','Status'],
 'reconciliation', (SELECT json_agg(json_build_array(file_id,payment_currency,
   raw_original_paid::text,staged_original_paid::text,expected_current_paid::text,
   core_paid::text,raw_staging_delta::text,effective_core_delta::text,
   CASE WHEN raw_staging_delta<>0 OR effective_core_delta<>0 THEN 1 ELSE 0 END,
   CASE WHEN raw_staging_delta<>0 OR effective_core_delta<>0 THEN 'CHECK' ELSE 'PASS' END)
   ORDER BY payment_currency,file_id) FROM analytics.file_amount_reconciliation),
 'detail_columns', ARRAY['Reference','Date','Event time (source)','Currency',
   'Payment format','Amount in currency','Rule score','Triggered rules'],
 'detail', (SELECT json_agg(json_build_array('TX-'||substr(md5(transaction_key::text),1,12),
   event_date,to_char(event_time,'YYYY-MM-DD HH24:MI:SS'),payment_currency,
   payment_format,amount_paid::text,risk_score,
   concat_ws('; ',CASE WHEN high_amount_for_currency_day THEN 'High amount' END,
     CASE WHEN high_hourly_velocity THEN 'High hourly velocity' END,
     CASE WHEN repeated_counterparty THEN 'Repeated counterparty' END))
   ORDER BY event_time,payment_currency,transaction_key) FROM detail),
 'controls', (SELECT json_build_object(
   'published_transactions',sum(transaction_count),'alerts',sum(risk_alert_count),
   'synthetic_labels',sum(labelled_laundering_count),'source_daily_rows',count(*),
   'date_count',count(DISTINCT event_date),'currencies',count(DISTINCT payment_currency),
   'formats',count(DISTINCT payment_format),'min_date',min(event_date),'max_date',max(event_date))
   FROM analytics.v_daily_metrics),
 'source', 'IBM AML HI-Small synthetic transactions; analytics publication',
 'sample_policy', 'Up to three alerts per event-date/currency, highest rule score first; not representative',
 'event_time_note', 'Source timestamps have no supplied timezone; only publication time is UTC'
);
ROLLBACK;
"""


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--host', default='127.0.0.1')
    p.add_argument('--port', default='5432')
    p.add_argument('--database', default='banking_pipeline_fullrun')
    p.add_argument('--psql', default='psql')
    p.add_argument('--output', type=Path, default=Path('pipeline/powerbi/upgrade/data/snapshot.json'))
    a = p.parse_args()
    result = subprocess.run([a.psql, '-X', '-w', '-q', '-A', '-t', '-h', a.host,
        '-p', a.port, '-d', a.database, '-v', 'ON_ERROR_STOP=1'],
        input=SQL, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr)
    doc = json.loads(result.stdout)
    assert doc['publication']['publication_id'] is not None, 'No published snapshot'
    daily = doc['daily']
    doc['controls']['exported_daily_rows'] = len(daily)
    assert len({tuple(r[:3]) for r in daily}) == len(daily), 'Duplicate daily grain'
    assert sum(r[3] for r in daily) == doc['controls']['published_transactions']
    assert sum(r[4] for r in daily) == doc['controls']['alerts']
    assert sum(r[5] for r in daily) == doc['controls']['synthetic_labels']
    assert sum(r[2] for r in doc['files']) == doc['controls']['published_transactions']
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(doc,separators=(',',':'))+'\n')
    print(json.dumps({'output':str(a.output),'sha256':hashlib.sha256(a.output.read_bytes()).hexdigest(),
        'controls':doc['controls'],'detail_sample_rows':len(doc['detail'])}))


if __name__ == '__main__':
    main()
