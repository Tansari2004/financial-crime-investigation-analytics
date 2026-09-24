-- Run in a NEW database. Fails if the table exists, protecting existing work.
CREATE TABLE transactions (
    transaction_id BIGSERIAL PRIMARY KEY,
    transaction_time TIMESTAMP,
    from_bank TEXT,
    from_account TEXT,
    to_bank TEXT,
    to_account TEXT,
    amount_received NUMERIC(18, 2),
    receiving_currency TEXT,
    amount_paid NUMERIC(18, 2),
    payment_currency TEXT,
    payment_format TEXT,
    is_laundering SMALLINT
);
