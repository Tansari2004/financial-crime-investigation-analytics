# Interview and learning guide

## Thirty-second explanation

“I built a PostgreSQL investigation analytics project using about five million synthetic bank transactions. SQL summarizes who is moving money, how often, and how a payment compares with earlier account activity. I preserved currency and bank-account identity to avoid misleading comparisons. The completed version is SQL analytics; the next phase is to test whether a model can rank simulated-laundering cases near the top of a review queue.”

## Demonstrate it

1. Show the README and explain the investigation problem.
2. Open `sql/schema.sql`: explain sender/receiver fields and the generated ID.
3. Open `reports/sql_findings.txt`: show row count, label imbalance, and missingness checks.
4. Explain query 6: GROUP BY summarizes each sender bank-account pair; filtering to USD makes amounts comparable.
5. Explain query 8: CTEs create daily summaries; a window calculates earlier history; JOIN matches it to payments.
6. Explain that a large amount multiple is an indicator, not a validated prediction.

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

**What is the amount multiple?** Current USD payment divided by the same bank-account's average USD payment on strictly earlier days. At least ten prior payments are required and zero averages excluded. Missing history does not mean low risk.

**What are the limits?** Synthetic data, a short observation period, incomplete knowledge of context, possible false alerts, and no predictive model yet. Full-period aggregates are retrospective and cannot simply be reused as model features.

**How was it built?** With AI assistance. Practise running and modifying the SQL so you can explain the choices and accurately describe your own contribution.
