-- Load one score per transaction after running train_model.py.
CREATE TABLE model_scores (
    transaction_id BIGINT PRIMARY KEY,
    review_score DOUBLE PRECISION NOT NULL CHECK (review_score BETWEEN 0 AND 1),
    data_split TEXT NOT NULL CHECK (data_split IN ('train', 'validation', 'test')),
    model_version TEXT NOT NULL
);

\copy model_scores(transaction_id, review_score, data_split, model_version) FROM 'data/processed/model_scores.csv' WITH (FORMAT csv, HEADER true)

CREATE INDEX model_scores_rank_idx ON model_scores (review_score DESC);
ANALYZE model_scores;

-- Fast post-load integrity check: both values must be zero.
SELECT
    (SELECT COUNT(*) FROM transactions) - (SELECT COUNT(*) FROM model_scores) AS row_count_difference,
    COUNT(*) FILTER (WHERE t.transaction_id IS NULL) AS unmatched_scores
FROM model_scores s
LEFT JOIN transactions t USING (transaction_id);
