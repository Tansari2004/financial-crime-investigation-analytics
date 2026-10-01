CREATE OR REPLACE FUNCTION analytics.refresh_and_publish()
RETURNS JSONB
LANGUAGE plpgsql
AS $$
DECLARE
    v_state analytics.publication_state%ROWTYPE;
    v_promotion_state ops.pipeline_state%ROWTYPE;
    v_through_run BIGINT;
    v_through_file BIGINT;
    v_days BIGINT;
    v_files BIGINT;
    v_risk_rows BIGINT := 0;
    v_daily_rows BIGINT := 0;
    v_expected BIGINT;
    v_actual BIGINT;
    v_publication_id BIGINT;
    v_rejection_limit NUMERIC;
BEGIN
    -- This lock is shared by ingestion and promotion. It provides one stable
    -- commit boundary for source, core, and the published reporting snapshot.
    PERFORM pg_advisory_xact_lock(7291942);
    SELECT * INTO STRICT v_state FROM analytics.publication_state
    WHERE state_id = 1 FOR UPDATE;
    SELECT * INTO STRICT v_promotion_state FROM ops.pipeline_state
    WHERE pipeline_name = 'transaction_promotion';
    SELECT COALESCE(max(promotion_run_id), 0) INTO v_through_run
    FROM ops.promotion_run WHERE status = 'completed';
    SELECT COALESCE(max(file_id), 0) INTO v_through_file
    FROM ops.file_manifest WHERE status = 'completed';
    SELECT max_rejected_fraction INTO STRICT v_rejection_limit
    FROM ops.quality_policy WHERE policy_name = 'transaction_files';

    IF EXISTS (
        SELECT 1 FROM raw.transaction_record
        WHERE validation_status = 'accepted'
          AND raw_record_id > v_promotion_state.last_raw_record_id
    ) OR EXISTS (
        SELECT 1 FROM raw.transaction_correction
        WHERE correction_id > v_promotion_state.last_correction_id
    ) THEN
        RAISE EXCEPTION 'unpromoted accepted source records';
    END IF;
    IF EXISTS (SELECT 1 FROM ops.file_manifest WHERE status = 'started') OR
       EXISTS (SELECT 1 FROM ops.correction_file_manifest WHERE status = 'started') THEN
        RAISE EXCEPTION 'a source file is still loading';
    END IF;

    IF v_through_run = v_state.last_promotion_run_id AND
       v_through_file = v_state.last_file_id THEN
        RETURN jsonb_build_object('status', 'skipped',
            'last_publication_id', v_state.last_publication_id);
    END IF;

    CREATE TEMP TABLE publish_days (event_date DATE PRIMARY KEY) ON COMMIT DROP;
    CREATE TEMP TABLE publish_files (file_id BIGINT PRIMARY KEY) ON COMMIT DROP;

    INSERT INTO publish_days (event_date)
    SELECT DISTINCT event_date FROM (
        SELECT s.event_time::date AS event_date
        FROM ops.promotion_run p
        JOIN staging.transaction_typed s
          ON s.raw_record_id > p.raw_from_exclusive
         AND s.raw_record_id <= p.raw_to_inclusive
        WHERE p.promotion_run_id > v_state.last_promotion_run_id
          AND p.promotion_run_id <= v_through_run
        UNION
        SELECT c.event_time::date
        FROM ops.promotion_run p
        JOIN staging.transaction_correction_typed c
          ON c.correction_id > p.correction_from_exclusive
         AND c.correction_id <= p.correction_to_inclusive
        WHERE p.promotion_run_id > v_state.last_promotion_run_id
          AND p.promotion_run_id <= v_through_run
        UNION
        SELECT original.event_time::date
        FROM ops.promotion_run p
        JOIN staging.transaction_correction_typed changed
          ON changed.correction_id > p.correction_from_exclusive
         AND changed.correction_id <= p.correction_to_inclusive
        JOIN staging.transaction_typed original
          ON original.raw_record_id = changed.target_raw_record_id
        WHERE p.promotion_run_id > v_state.last_promotion_run_id
          AND p.promotion_run_id <= v_through_run
        UNION
        SELECT history.event_time::date
        FROM ops.promotion_run p
        JOIN staging.transaction_correction_typed changed
          ON changed.correction_id > p.correction_from_exclusive
         AND changed.correction_id <= p.correction_to_inclusive
        JOIN staging.transaction_correction_typed history
          ON history.target_raw_record_id = changed.target_raw_record_id
        WHERE p.promotion_run_id > v_state.last_promotion_run_id
          AND p.promotion_run_id <= v_through_run
    ) affected;

    INSERT INTO publish_files (file_id)
    SELECT DISTINCT file_id FROM (
        SELECT m.file_id FROM ops.file_manifest m
        WHERE m.status = 'completed' AND m.file_id > v_state.last_file_id
          AND m.file_id <= v_through_file
        UNION
        SELECT s.source_file_id
        FROM ops.promotion_run p
        JOIN staging.transaction_typed s
          ON s.raw_record_id > p.raw_from_exclusive
         AND s.raw_record_id <= p.raw_to_inclusive
        WHERE p.promotion_run_id > v_state.last_promotion_run_id
          AND p.promotion_run_id <= v_through_run
        UNION
        SELECT r.file_id
        FROM ops.promotion_run p
        JOIN raw.transaction_correction c
          ON c.correction_id > p.correction_from_exclusive
         AND c.correction_id <= p.correction_to_inclusive
        JOIN raw.transaction_record r
          ON r.raw_record_id = c.target_raw_record_id
        WHERE p.promotion_run_id > v_state.last_promotion_run_id
          AND p.promotion_run_id <= v_through_run
    ) affected;

    SELECT count(*) INTO v_days FROM publish_days;
    SELECT count(*) INTO v_files FROM publish_files;

    DELETE FROM analytics.fact_risk_signal
    WHERE event_date IN (SELECT event_date FROM publish_days);

    WITH activity AS (
        SELECT f.transaction_key, f.source_raw_record_id, f.event_time,
            f.event_time::date AS event_date,
            fb.bank_code AS from_bank_code, fa.account_code AS from_account_code,
            tb.bank_code AS to_bank_code, ta.account_code AS to_account_code,
            f.payment_currency, f.payment_format, f.amount_paid,
            f.is_laundering, f.current_correction_id,
            count(*) OVER (
                PARTITION BY f.event_time::date, f.from_account_key,
                             date_trunc('hour', f.event_time), f.payment_currency
            ) AS hourly_outgoing_count,
            count(*) OVER (
                PARTITION BY f.event_time::date, f.from_account_key,
                             f.to_account_key, f.payment_currency
            ) AS daily_counterparty_count,
            count(*) OVER (
                PARTITION BY f.event_time::date, f.payment_currency
            ) AS currency_day_count,
            percent_rank() OVER (
                PARTITION BY f.event_time::date, f.payment_currency
                ORDER BY f.amount_paid
            ) AS amount_percent_rank
        FROM core.fact_transaction f
        JOIN publish_days d ON d.event_date = f.event_time::date
        JOIN core.dim_account fa ON fa.account_key = f.from_account_key
        JOIN core.dim_bank fb ON fb.bank_key = fa.bank_key
        JOIN core.dim_account ta ON ta.account_key = f.to_account_key
        JOIN core.dim_bank tb ON tb.bank_key = ta.bank_key
    ), flags AS (
        SELECT transaction_key, source_raw_record_id, event_time, event_date,
            from_bank_code, from_account_code, to_bank_code, to_account_code,
            amount_paid, payment_currency, payment_format,
            is_laundering, current_correction_id,
            (currency_day_count >= 100 AND amount_percent_rank >= 0.99)
                AS high_amount,
            (hourly_outgoing_count >= 5) AS high_velocity,
            (daily_counterparty_count >= 3) AS repeat_counterparty
        FROM activity
    )
    INSERT INTO analytics.fact_risk_signal (
        transaction_key, source_raw_record_id, event_time, event_date,
        from_bank_code, from_account_code, to_bank_code, to_account_code,
        amount_paid, payment_currency, payment_format,
        high_amount_for_currency_day, high_hourly_velocity,
        repeated_counterparty, risk_score, is_laundering, current_correction_id
    )
    SELECT transaction_key, source_raw_record_id, event_time, event_date,
        from_bank_code, from_account_code, to_bank_code, to_account_code,
        amount_paid, payment_currency, payment_format,
        high_amount, high_velocity, repeat_counterparty,
        (CASE WHEN high_amount THEN 2 ELSE 0 END +
         CASE WHEN high_velocity THEN 2 ELSE 0 END +
         CASE WHEN repeat_counterparty THEN 1 ELSE 0 END)::smallint,
        is_laundering, current_correction_id
    FROM flags;
    GET DIAGNOSTICS v_risk_rows = ROW_COUNT;

    DELETE FROM analytics.fact_daily_transaction
    WHERE event_date IN (SELECT event_date FROM publish_days);
    INSERT INTO analytics.fact_daily_transaction (
        event_date, from_bank_key, payment_currency, payment_format,
        transaction_count, paid_amount, labelled_laundering_count,
        risk_alert_count
    )
    SELECT f.event_time::date, a.bank_key, f.payment_currency, f.payment_format,
        count(*), sum(f.amount_paid),
        count(*) FILTER (WHERE f.is_laundering),
        count(*) FILTER (WHERE s.risk_score >= 2)
    FROM core.fact_transaction f
    JOIN publish_days d ON d.event_date = f.event_time::date
    JOIN core.dim_account a ON a.account_key = f.from_account_key
    JOIN analytics.fact_risk_signal s ON s.transaction_key = f.transaction_key
    GROUP BY f.event_time::date, a.bank_key, f.payment_currency, f.payment_format;
    GET DIAGNOSTICS v_daily_rows = ROW_COUNT;

    WITH counts AS (
        SELECT m.file_id, m.total_rows AS manifest_total,
            m.accepted_rows AS manifest_accepted,
            m.rejected_rows AS manifest_rejected,
            m.duplicate_candidates AS manifest_duplicate_candidates,
            count(r.raw_record_id) AS raw_total,
            count(*) FILTER (WHERE r.validation_status = 'accepted') AS raw_accepted,
            count(*) FILTER (WHERE r.validation_status = 'rejected') AS raw_rejected,
            count(*) FILTER (WHERE r.validation_status = 'duplicate_candidate')
                AS raw_duplicate_candidates,
            count(s.raw_record_id) AS staged_count,
            count(f.transaction_key) AS core_count
        FROM publish_files pf
        JOIN ops.file_manifest m ON m.file_id = pf.file_id
        LEFT JOIN raw.transaction_record r ON r.file_id = m.file_id
        LEFT JOIN staging.transaction_typed s ON s.raw_record_id = r.raw_record_id
        LEFT JOIN core.fact_transaction f ON f.source_raw_record_id = r.raw_record_id
        GROUP BY m.file_id
    ), balanced AS (
        SELECT *,
            manifest_total = raw_total AND manifest_accepted = raw_accepted
            AND manifest_rejected = raw_rejected
            AND manifest_duplicate_candidates = raw_duplicate_candidates
            AND raw_accepted = staged_count AND staged_count = core_count
            AS is_balanced
        FROM counts
    )
    INSERT INTO analytics.file_row_reconciliation (
        file_id, manifest_total, manifest_accepted, manifest_rejected,
        manifest_duplicate_candidates, raw_total, raw_accepted,
        raw_rejected, raw_duplicate_candidates, staged_count, core_count,
        is_balanced, checked_at
    )
    SELECT file_id, manifest_total, manifest_accepted, manifest_rejected,
        manifest_duplicate_candidates, raw_total, raw_accepted,
        raw_rejected, raw_duplicate_candidates, staged_count, core_count,
        is_balanced, now()
    FROM balanced
    ON CONFLICT (file_id) DO UPDATE SET
        manifest_total = EXCLUDED.manifest_total,
        manifest_accepted = EXCLUDED.manifest_accepted,
        manifest_rejected = EXCLUDED.manifest_rejected,
        manifest_duplicate_candidates = EXCLUDED.manifest_duplicate_candidates,
        raw_total = EXCLUDED.raw_total,
        raw_accepted = EXCLUDED.raw_accepted,
        raw_rejected = EXCLUDED.raw_rejected,
        raw_duplicate_candidates = EXCLUDED.raw_duplicate_candidates,
        staged_count = EXCLUDED.staged_count,
        core_count = EXCLUDED.core_count,
        is_balanced = EXCLUDED.is_balanced,
        checked_at = EXCLUDED.checked_at;

    DELETE FROM analytics.file_amount_reconciliation
    WHERE file_id IN (SELECT file_id FROM publish_files);
    WITH portions AS (
        SELECT r.file_id, r.payload->>'payment_currency' AS currency,
            sum((r.payload->>'amount_paid')::numeric(38,6)) AS raw_amount,
            0::numeric AS staged_amount, 0::numeric AS expected_amount,
            0::numeric AS core_amount
        FROM raw.transaction_record r
        JOIN publish_files pf ON pf.file_id = r.file_id
        WHERE r.validation_status = 'accepted'
        GROUP BY r.file_id, r.payload->>'payment_currency'
        UNION ALL
        SELECT s.source_file_id, s.payment_currency, 0, sum(s.amount_paid), 0, 0
        FROM staging.transaction_typed s
        JOIN publish_files pf ON pf.file_id = s.source_file_id
        GROUP BY s.source_file_id, s.payment_currency
        UNION ALL
        SELECT s.source_file_id,
            COALESCE(c.payment_currency, s.payment_currency),
            0, 0, sum(COALESCE(c.amount_paid, s.amount_paid)), 0
        FROM staging.transaction_typed s
        JOIN publish_files pf ON pf.file_id = s.source_file_id
        LEFT JOIN LATERAL (
            SELECT x.payment_currency, x.amount_paid
            FROM staging.transaction_correction_typed x
            WHERE x.target_raw_record_id = s.raw_record_id
            ORDER BY x.correction_id DESC LIMIT 1
        ) c ON true
        GROUP BY s.source_file_id, COALESCE(c.payment_currency, s.payment_currency)
        UNION ALL
        SELECT f.source_file_id, f.payment_currency, 0, 0, 0, sum(f.amount_paid)
        FROM core.fact_transaction f
        JOIN publish_files pf ON pf.file_id = f.source_file_id
        GROUP BY f.source_file_id, f.payment_currency
    ), totals AS (
        SELECT file_id, currency,
            sum(raw_amount) AS raw_original_paid,
            sum(staged_amount) AS staged_original_paid,
            sum(expected_amount) AS expected_current_paid,
            sum(core_amount) AS core_paid
        FROM portions GROUP BY file_id, currency
    )
    INSERT INTO analytics.file_amount_reconciliation (
        file_id, payment_currency, raw_original_paid, staged_original_paid,
        expected_current_paid, core_paid, raw_staging_delta,
        effective_core_delta
    )
    SELECT file_id, currency, raw_original_paid, staged_original_paid,
        expected_current_paid, core_paid,
        raw_original_paid - staged_original_paid,
        expected_current_paid - core_paid
    FROM totals;

    IF EXISTS (
        SELECT 1 FROM analytics.file_row_reconciliation r
        JOIN publish_files pf ON pf.file_id = r.file_id
        WHERE NOT r.is_balanced
    ) THEN
        RAISE EXCEPTION 'row reconciliation failed';
    END IF;
    IF EXISTS (
        SELECT 1 FROM analytics.file_amount_reconciliation a
        JOIN publish_files pf ON pf.file_id = a.file_id
        WHERE a.raw_staging_delta <> 0 OR a.effective_core_delta <> 0
    ) THEN
        RAISE EXCEPTION 'amount reconciliation failed';
    END IF;
    IF EXISTS (
        SELECT 1 FROM ops.file_manifest m
        JOIN publish_files pf ON pf.file_id = m.file_id
        WHERE m.total_rows > 0
          AND m.rejected_rows::numeric / m.total_rows > v_rejection_limit
    ) THEN
        RAISE EXCEPTION 'rejected-row fraction exceeds quality policy';
    END IF;

    SELECT count(*) INTO v_expected FROM core.fact_transaction f
    JOIN publish_days d ON d.event_date = f.event_time::date;
    SELECT count(*) INTO v_actual FROM analytics.fact_risk_signal s
    JOIN publish_days d ON d.event_date = s.event_date;
    IF v_expected <> v_actual THEN
        RAISE EXCEPTION 'risk signal coverage mismatch: % versus %', v_expected, v_actual;
    END IF;
    SELECT COALESCE(sum(d.transaction_count), 0) INTO v_actual
    FROM analytics.fact_daily_transaction d
    JOIN publish_days p ON p.event_date = d.event_date;
    IF v_expected <> v_actual THEN
        RAISE EXCEPTION 'daily mart count mismatch: % versus %', v_expected, v_actual;
    END IF;
    IF EXISTS (
        WITH core_totals AS (
            SELECT f.payment_currency, sum(f.amount_paid) AS amount
            FROM core.fact_transaction f
            JOIN publish_days d ON d.event_date = f.event_time::date
            GROUP BY f.payment_currency
        ), mart_totals AS (
            SELECT m.payment_currency, sum(m.paid_amount) AS amount
            FROM analytics.fact_daily_transaction m
            JOIN publish_days d ON d.event_date = m.event_date
            GROUP BY m.payment_currency
        )
        SELECT 1 FROM core_totals c FULL JOIN mart_totals m
            ON m.payment_currency = c.payment_currency
        WHERE COALESCE(c.amount, 0) <> COALESCE(m.amount, 0)
    ) THEN
        RAISE EXCEPTION 'daily mart amount mismatch';
    END IF;

    INSERT INTO analytics.publication_run (
        through_promotion_run_id, through_file_id,
        affected_days, affected_files, refreshed_risk_rows,
        refreshed_daily_rows, status
    ) VALUES (
        v_through_run, v_through_file, v_days, v_files,
        v_risk_rows, v_daily_rows, 'published'
    ) RETURNING publication_id INTO v_publication_id;
    UPDATE analytics.publication_state
    SET last_promotion_run_id = v_through_run,
        last_file_id = v_through_file,
        last_publication_id = v_publication_id,
        published_at = now()
    WHERE state_id = 1;

    RETURN jsonb_build_object(
        'status', 'published', 'publication_id', v_publication_id,
        'through_promotion_run_id', v_through_run,
        'through_file_id', v_through_file,
        'affected_days', v_days, 'affected_files', v_files,
        'refreshed_risk_rows', v_risk_rows,
        'refreshed_daily_rows', v_daily_rows
    );
END;
$$;
