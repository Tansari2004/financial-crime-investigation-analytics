-- Run in a NEW database. Fails if the table exists, protecting existing work.
CREATE TABLE transactions (
    transaction_id BIGSERIAL PRIMARY KEY,
    transaction_time TIMESTAMP,
    from_bank TEXT,
    from_account TEXT,
    to_bank TEXT,
    to_account TEXT,
    -- Preserve source decimals. Widening an already loaded table would NOT
    -- recover rounded amounts: rebuild from the original CSV in a new DB.
    amount_received NUMERIC,
    receiving_currency TEXT,
    amount_paid NUMERIC,
    payment_currency TEXT,
    payment_format TEXT,
    is_laundering SMALLINT
);
