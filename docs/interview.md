# Interview and learning guide

## Thirty-second explanation

“I built a PostgreSQL and Python investigation-ranking pipeline using about five million synthetic bank transactions. SQL creates behavioral features using only information available before each scoring date. A class-weighted logistic regression ranks every transaction for human review. On a later test period, 199 of 1,611 positive labels appeared in the top 1,000 cases, giving 19.9% precision and 12.35% recall at that review capacity.”

## Demonstrate it

1. Show the README and explain the investigation problem.
2. Open `sql/schema.sql`: explain sender/receiver fields and the generated ID.
3. Open `reports/sql_findings.txt`: show row count, label imbalance, and missingness checks.
4. Explain query 6: GROUP BY summarizes each sender bank-account pair; filtering to USD makes amounts comparable.
5. Show `sql/model_features.sql`: earlier-day windows keep future activity out of historical features.
6. Show `reports/model_report.md`: explain PR-AUC and why top-K metrics match limited investigator capacity.
7. Explain that class weighting makes `review_score` useful for ordering, but not a calibrated crime probability.

## Vocabulary

- SELECT chooses what to show.
- WHERE keeps rows meeting a condition.
- GROUP BY collects payments by account or category.
- COUNT, SUM, AVG count payments, add amounts, and calculate an average.
- JOIN matches related rows.
- WITH names an intermediate query (a CTE).
- A window function calculates over related rows while keeping each current row.

## Key questions

**Why not filter to label 1?** That uses the synthetic answer key. A future model must score unseen rows without that label as input.

**Why separate currencies?** Ten dollars and ten euros have different units. No exchange rates are assumed.

**What is the amount multiple?** Current payment divided by the same bank-account and currency's average on strictly earlier days. Missing history is represented explicitly; it does not mean low risk.

**Why split by time?** Random splitting can let similar future behavior influence training. Earlier dates train the model and later dates test subsequently observed transactions.

**Why not accuracy?** Predicting 0 for every row would be about 99.9% accurate and useless. PR-AUC and Precision@K/Recall@K measure positive-case ranking.

**What are the limits?** Synthetic data, a short observation period, a changing positive-label rate over time, incomplete context, many false alerts at a 0.5 cutoff, and no calibrated probability or real investigator validation.

**How was it built?** With AI assistance. Practise running and modifying the SQL so you can explain the choices and accurately describe your own contribution.
