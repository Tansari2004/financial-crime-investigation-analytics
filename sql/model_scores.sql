-- Load a complete score set atomically. Missing/orphaned/mis-split scores fail
-- with ON_ERROR_STOP, instead of merely printing a nonzero diagnostic.
BEGIN;
CREATE TABLE model_scores (
    transaction_id BIGINT PRIMARY KEY REFERENCES transactions(transaction_id),
    review_score DOUBLE PRECISION NOT NULL CHECK (review_score BETWEEN 0 AND 1),
    data_split TEXT NOT NULL CHECK (data_split IN ('train', 'validation', 'test')),
    model_version TEXT NOT NULL
);

\copy model_scores(transaction_id, review_score, data_split, model_version) FROM 'data/processed/model_scores.csv' WITH (FORMAT csv, HEADER true)

DO $$ BEGIN
    IF EXISTS (
        SELECT 1 FROM transactions t LEFT JOIN model_scores s USING (transaction_id)
        WHERE s.transaction_id IS NULL
    ) THEN
        RAISE EXCEPTION 'missing transaction scores; score import rolled back';
    END IF;
    IF EXISTS (
        SELECT 1 FROM model_scores s JOIN transactions t USING (transaction_id)
        WHERE t.transaction_time IS NULL OR s.data_split <> CASE
            WHEN t.transaction_time < TIMESTAMP '2022-09-08' THEN 'train'
            WHEN t.transaction_time < TIMESTAMP '2022-09-09' THEN 'validation'
            ELSE 'test' END
    ) THEN
        RAISE EXCEPTION 'score split disagrees with transaction time';
    END IF;
END $$;
CREATE INDEX model_scores_rank_idx ON model_scores (review_score DESC, transaction_id);
COMMIT;
ANALYZE model_scores;
