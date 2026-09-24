-- Run from the repository root. Loading twice is refused.
BEGIN;
LOCK TABLE transactions IN EXCLUSIVE MODE;
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM transactions) THEN
        RAISE EXCEPTION 'transactions already contains data; import refused';
    END IF;
END $$;
\copy transactions(transaction_time, from_bank, from_account, to_bank, to_account, amount_received, receiving_currency, amount_paid, payment_currency, payment_format, is_laundering) FROM 'data/raw/HI-Small_Trans.csv' WITH (FORMAT csv, HEADER true)
COMMIT;
ANALYZE transactions;
