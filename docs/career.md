# Resume and LinkedIn — SQL + ML version

## Resume

**Financial Crime Investigation & Transaction Risk System | PostgreSQL, SQL, Python, NumPy | Personal Project**

- Built a PostgreSQL and Python pipeline that ingested and scored 5.08 million synthetic financial transactions using point-in-time behavioral features and a class-weighted logistic regression baseline.
- Used chronological train/validation/test splits to reduce future leakage and evaluated severe class imbalance with PR-AUC, ROC-AUC, and investigator-capacity ranking metrics.
- Surfaced 199 of 1,611 positive labels in the top 1,000 later-period cases (19.9% precision, 12.35% recall), approximately 107× the test-period base rate.

## LinkedIn project description

Built a PostgreSQL and Python investigation-prioritization pipeline across 5,078,345 synthetic IBM AML transactions. The project creates point-in-time SQL features, trains a class-weighted logistic regression on earlier dates, and assigns a review score to every transaction.

Because only 0.1019% of all transactions carry a positive synthetic label, I evaluated the model with PR-AUC and review-capacity metrics rather than accuracy alone. On the later test period, the top 1,000 ranked transactions contained 199 known positive labels (19.9% precision and 12.35% recall). Planned extensions include per-case explanations, exposure-aware priority rules, and a Power BI dashboard.

## Before posting

Link to the [GitHub repository](https://github.com/Tansari2004/financial-crime-investigation-analytics). Do not claim Power BI, real-world detection performance, prevented losses, or business impact as completed achievements. Describe `review_score` as a ranking score rather than a crime probability.
