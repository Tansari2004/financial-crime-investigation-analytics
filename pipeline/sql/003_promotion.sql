CREATE OR REPLACE FUNCTION core.promote_transactions(
    p_mode TEXT DEFAULT 'incremental',
    p_raw_after BIGINT DEFAULT NULL,
    p_raw_through BIGINT DEFAULT NULL,
    p_correction_after BIGINT DEFAULT NULL,
    p_correction_through BIGINT DEFAULT NULL,
    p_raw_limit INTEGER DEFAULT 100000,
    p_correction_limit INTEGER DEFAULT 10000
) RETURNS JSONB
LANGUAGE plpgsql
AS $$
DECLARE
    v_state ops.pipeline_state%ROWTYPE;
    v_raw_after BIGINT;
    v_raw_through BIGINT;
    v_correction_after BIGINT;
    v_correction_through BIGINT;
    v_first_blocked_correction BIGINT;
    v_staged_rows BIGINT := 0;
    v_fact_inserted BIGINT := 0;
    v_correction_events BIGINT := 0;
    v_corrected_transactions BIGINT := 0;
    v_late_rows BIGINT := 0;
    v_expected BIGINT;
    v_actual BIGINT;
    v_max_new_event_time TIMESTAMP;
    v_run_id BIGINT;
BEGIN
    IF p_mode NOT IN ('incremental', 'backfill') THEN
        RAISE EXCEPTION 'mode must be incremental or backfill';
    END IF;
    IF p_raw_limit <= 0 OR p_correction_limit <= 0 THEN
        RAISE EXCEPTION 'batch limits must be positive';
    END IF;

    -- Ingestion uses this same lock before assigning raw IDs. No transaction
    -- with a lower uncommitted ID can appear after the cursor advances.
    PERFORM pg_advisory_xact_lock(7291942);
    SELECT * INTO STRICT v_state FROM ops.pipeline_state
    WHERE pipeline_name = 'transaction_promotion' FOR UPDATE;

    IF p_mode = 'incremental' THEN
        IF p_raw_after IS NOT NULL OR p_raw_through IS NOT NULL OR
           p_correction_after IS NOT NULL OR p_correction_through IS NOT NULL THEN
            RAISE EXCEPTION 'explicit ranges require backfill mode';
        END IF;
        v_raw_after := v_state.last_raw_record_id;
        SELECT COALESCE(max(raw_record_id), v_raw_after) INTO v_raw_through
        FROM (
            SELECT raw_record_id FROM raw.transaction_record
            WHERE validation_status = 'accepted' AND raw_record_id > v_raw_after
            ORDER BY raw_record_id LIMIT p_raw_limit
        ) bounded_raw;

        v_correction_after := v_state.last_correction_id;
        SELECT min(c.correction_id) INTO v_first_blocked_correction
        FROM raw.transaction_correction c
        WHERE c.correction_id > v_correction_after
          AND c.target_raw_record_id > v_raw_through
          AND NOT EXISTS (
              SELECT 1 FROM core.fact_transaction f
              WHERE f.source_raw_record_id = c.target_raw_record_id
          );
        SELECT COALESCE(max(correction_id), v_correction_after)
        INTO v_correction_through
        FROM (
            SELECT correction_id FROM raw.transaction_correction
            WHERE correction_id > v_correction_after
              AND correction_id < COALESCE(v_first_blocked_correction, 9223372036854775807)
            ORDER BY correction_id LIMIT p_correction_limit
        ) bounded_corrections;
    ELSE
        v_raw_after := COALESCE(p_raw_after, 0);
        v_raw_through := COALESCE(p_raw_through, v_raw_after);
        v_correction_after := COALESCE(p_correction_after, 0);
        v_correction_through := COALESCE(p_correction_through, v_correction_after);
        IF v_raw_after < 0 OR v_raw_through < v_raw_after OR
           v_correction_after < 0 OR v_correction_through < v_correction_after THEN
            RAISE EXCEPTION 'invalid backfill range';
        END IF;
        IF v_raw_through > COALESCE((SELECT max(raw_record_id) FROM raw.transaction_record), 0)
           OR v_correction_through > COALESCE((SELECT max(correction_id) FROM raw.transaction_correction), 0) THEN
            RAISE EXCEPTION 'backfill range exceeds available source IDs';
        END IF;
    END IF;

    IF v_raw_through = v_raw_after AND v_correction_through = v_correction_after THEN
        RETURN jsonb_build_object('status', 'skipped', 'mode', p_mode,
            'last_raw_record_id', v_state.last_raw_record_id,
            'last_correction_id', v_state.last_correction_id);
    END IF;

    INSERT INTO staging.transaction_typed (
        raw_record_id, source_file_id, event_time,
        from_bank_code, from_account_code, to_bank_code, to_account_code,
        amount_received, receiving_currency, amount_paid, payment_currency,
        payment_format, is_laundering, record_hash
    )
    SELECT r.raw_record_id, r.file_id, (r.payload->>'timestamp')::timestamp,
        r.payload->>'from_bank', r.payload->>'from_account',
        r.payload->>'to_bank', r.payload->>'to_account',
        (r.payload->>'amount_received')::numeric(24,6),
        r.payload->>'receiving_currency',
        (r.payload->>'amount_paid')::numeric(24,6),
        r.payload->>'payment_currency', r.payload->>'payment_format',
        (r.payload->>'is_laundering') = '1', r.record_hash
    FROM raw.transaction_record r
    WHERE r.validation_status = 'accepted'
      AND r.raw_record_id > v_raw_after AND r.raw_record_id <= v_raw_through
    ON CONFLICT (raw_record_id) DO NOTHING;
    GET DIAGNOSTICS v_staged_rows = ROW_COUNT;

    INSERT INTO staging.transaction_correction_typed (
        correction_id, target_raw_record_id, event_time,
        from_bank_code, from_account_code, to_bank_code, to_account_code,
        amount_received, receiving_currency, amount_paid, payment_currency,
        payment_format, is_laundering, record_hash
    )
    SELECT c.correction_id, c.target_raw_record_id,
        (c.payload->>'timestamp')::timestamp,
        c.payload->>'from_bank', c.payload->>'from_account',
        c.payload->>'to_bank', c.payload->>'to_account',
        (c.payload->>'amount_received')::numeric(24,6),
        c.payload->>'receiving_currency',
        (c.payload->>'amount_paid')::numeric(24,6),
        c.payload->>'payment_currency', c.payload->>'payment_format',
        (c.payload->>'is_laundering') = '1', c.record_hash
    FROM raw.transaction_correction c
    WHERE c.correction_id > v_correction_after
      AND c.correction_id <= v_correction_through
    ON CONFLICT (correction_id) DO NOTHING;

    SELECT count(*) INTO v_expected FROM raw.transaction_record
    WHERE validation_status = 'accepted'
      AND raw_record_id > v_raw_after AND raw_record_id <= v_raw_through;
    SELECT count(*) INTO v_actual FROM staging.transaction_typed
    WHERE raw_record_id > v_raw_after AND raw_record_id <= v_raw_through;
    IF v_expected <> v_actual THEN
        RAISE EXCEPTION 'raw-to-staging count mismatch: % versus %', v_expected, v_actual;
    END IF;
    SELECT count(*) INTO v_correction_events FROM staging.transaction_correction_typed
    WHERE correction_id > v_correction_after AND correction_id <= v_correction_through;
    SELECT count(*) INTO v_expected FROM raw.transaction_correction
    WHERE correction_id > v_correction_after AND correction_id <= v_correction_through;
    IF v_expected <> v_correction_events THEN
        RAISE EXCEPTION 'correction staging count mismatch';
    END IF;

    WITH incoming AS (
        SELECT from_bank_code, to_bank_code FROM staging.transaction_typed
        WHERE raw_record_id > v_raw_after AND raw_record_id <= v_raw_through
        UNION ALL
        SELECT from_bank_code, to_bank_code FROM staging.transaction_correction_typed
        WHERE correction_id > v_correction_after AND correction_id <= v_correction_through
    )
    INSERT INTO core.dim_bank (bank_code)
    SELECT DISTINCT bank_code FROM (
        SELECT from_bank_code AS bank_code FROM incoming
        UNION ALL SELECT to_bank_code FROM incoming
    ) codes ON CONFLICT (bank_code) DO NOTHING;

    WITH incoming AS (
        SELECT from_bank_code, from_account_code, to_bank_code, to_account_code
        FROM staging.transaction_typed
        WHERE raw_record_id > v_raw_after AND raw_record_id <= v_raw_through
        UNION ALL
        SELECT from_bank_code, from_account_code, to_bank_code, to_account_code
        FROM staging.transaction_correction_typed
        WHERE correction_id > v_correction_after AND correction_id <= v_correction_through
    )
    INSERT INTO core.dim_account (bank_key, account_code)
    SELECT DISTINCT b.bank_key, a.account_code
    FROM (
        SELECT from_bank_code AS bank_code, from_account_code AS account_code FROM incoming
        UNION ALL
        SELECT to_bank_code, to_account_code FROM incoming
    ) a
    JOIN core.dim_bank b ON b.bank_code = a.bank_code
    ON CONFLICT (bank_key, account_code) DO NOTHING;

    INSERT INTO core.fact_transaction (
        source_raw_record_id, source_file_id, event_time,
        from_account_key, to_account_key, amount_received, receiving_currency,
        amount_paid, payment_currency, payment_format, is_laundering
    )
    SELECT s.raw_record_id, s.source_file_id, s.event_time,
        fa.account_key, ta.account_key, s.amount_received, s.receiving_currency,
        s.amount_paid, s.payment_currency, s.payment_format, s.is_laundering
    FROM staging.transaction_typed s
    JOIN core.dim_bank fb ON fb.bank_code = s.from_bank_code
    JOIN core.dim_account fa ON fa.bank_key = fb.bank_key
                            AND fa.account_code = s.from_account_code
    JOIN core.dim_bank tb ON tb.bank_code = s.to_bank_code
    JOIN core.dim_account ta ON ta.bank_key = tb.bank_key
                            AND ta.account_code = s.to_account_code
    WHERE s.raw_record_id > v_raw_after AND s.raw_record_id <= v_raw_through
    ON CONFLICT (source_raw_record_id) DO NOTHING;
    GET DIAGNOSTICS v_fact_inserted = ROW_COUNT;

    SELECT count(*) INTO v_actual FROM core.fact_transaction
    WHERE source_raw_record_id > v_raw_after AND source_raw_record_id <= v_raw_through;
    SELECT count(*) INTO v_expected FROM staging.transaction_typed
    WHERE raw_record_id > v_raw_after AND raw_record_id <= v_raw_through;
    IF v_expected <> v_actual THEN
        RAISE EXCEPTION 'staging-to-fact count mismatch: % versus %', v_expected, v_actual;
    END IF;
    IF EXISTS (
        SELECT 1 FROM staging.transaction_correction_typed c
        LEFT JOIN core.fact_transaction f ON f.source_raw_record_id = c.target_raw_record_id
        WHERE c.correction_id > v_correction_after
          AND c.correction_id <= v_correction_through
          AND f.transaction_key IS NULL
    ) THEN
        RAISE EXCEPTION 'correction target has no fact transaction';
    END IF;

    WITH latest AS (
        SELECT DISTINCT ON (target_raw_record_id) *
        FROM staging.transaction_correction_typed
        WHERE correction_id > v_correction_after
          AND correction_id <= v_correction_through
        ORDER BY target_raw_record_id, correction_id DESC
    ), mapped AS (
        SELECT l.*, fa.account_key AS from_account_key,
            ta.account_key AS to_account_key
        FROM latest l
        JOIN core.dim_bank fb ON fb.bank_code = l.from_bank_code
        JOIN core.dim_account fa ON fa.bank_key = fb.bank_key
                                AND fa.account_code = l.from_account_code
        JOIN core.dim_bank tb ON tb.bank_code = l.to_bank_code
        JOIN core.dim_account ta ON ta.bank_key = tb.bank_key
                                AND ta.account_code = l.to_account_code
    )
    UPDATE core.fact_transaction f
    SET current_correction_id = m.correction_id,
        event_time = m.event_time,
        from_account_key = m.from_account_key,
        to_account_key = m.to_account_key,
        amount_received = m.amount_received,
        receiving_currency = m.receiving_currency,
        amount_paid = m.amount_paid,
        payment_currency = m.payment_currency,
        payment_format = m.payment_format,
        is_laundering = m.is_laundering,
        last_updated_at = now()
    FROM mapped m
    WHERE f.source_raw_record_id = m.target_raw_record_id
      AND (f.current_correction_id IS NULL OR f.current_correction_id < m.correction_id);
    GET DIAGNOSTICS v_corrected_transactions = ROW_COUNT;

    SELECT count(*) INTO v_late_rows FROM staging.transaction_typed
    WHERE raw_record_id > v_raw_after AND raw_record_id <= v_raw_through
      AND event_time < v_state.max_event_time;
    SELECT max(event_time) INTO v_max_new_event_time FROM (
        SELECT event_time FROM staging.transaction_typed
        WHERE raw_record_id > v_raw_after AND raw_record_id <= v_raw_through
        UNION ALL
        SELECT event_time FROM staging.transaction_correction_typed
        WHERE correction_id > v_correction_after AND correction_id <= v_correction_through
    ) events;

    IF p_mode = 'incremental' THEN
        UPDATE ops.pipeline_state
        SET last_raw_record_id = v_raw_through,
            last_correction_id = v_correction_through,
            max_event_time = greatest(max_event_time, v_max_new_event_time),
            updated_at = now()
        WHERE pipeline_name = 'transaction_promotion';
    END IF;

    INSERT INTO ops.promotion_run (
        mode, raw_from_exclusive, raw_to_inclusive,
        correction_from_exclusive, correction_to_inclusive,
        staged_rows, fact_inserted_rows, correction_events,
        corrected_transactions, late_arriving_rows, status
    ) VALUES (
        p_mode, v_raw_after, v_raw_through,
        v_correction_after, v_correction_through,
        v_staged_rows, v_fact_inserted, v_correction_events,
        v_corrected_transactions, v_late_rows, 'completed'
    ) RETURNING promotion_run_id INTO v_run_id;

    RETURN jsonb_build_object(
        'status', 'completed', 'mode', p_mode, 'promotion_run_id', v_run_id,
        'raw_from_exclusive', v_raw_after, 'raw_to_inclusive', v_raw_through,
        'correction_from_exclusive', v_correction_after,
        'correction_to_inclusive', v_correction_through,
        'staged_rows', v_staged_rows, 'fact_inserted_rows', v_fact_inserted,
        'correction_events', v_correction_events,
        'corrected_transactions', v_corrected_transactions,
        'late_arriving_rows', v_late_rows
    );
END;
$$;
