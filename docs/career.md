# Resume and LinkedIn — SQL + ML version

## Resume

**Financial Crime Investigation & Transaction Risk System | PostgreSQL, SQL, Python, NumPy, Power BI | Personal Project**

- Built a PostgreSQL and Python pipeline that ingested and scored 5.08 million synthetic financial transactions using point-in-time behavioral features and a class-weighted logistic regression baseline.
- Used chronological train/validation/test splits to reduce future leakage and evaluated severe class imbalance with PR-AUC, ROC-AUC, and investigator-capacity ranking metrics.
- Surfaced 199 of 1,611 positive labels in the top 1,000 later-period cases (19.9% precision, 12.35% recall), approximately 107× the test-period base rate.
- Generated model-linked reason fields for the top 10,000 later-period cases and built a two-page Power BI report with a ranked review queue and currency-count chart.
- Pinned the currency chart to a Power BI dashboard in My workspace.
- Built a local interactive investigation dashboard with case filters, category and daily charts, and per-transaction explanations.

## LinkedIn project description

Built a PostgreSQL and Python investigation-prioritization pipeline across 5,078,345 synthetic IBM AML transactions. The project creates point-in-time SQL features, trains a class-weighted logistic regression on earlier dates, and assigns a review score to every transaction.

Because only 0.1019% of all transactions carry a positive synthetic label, I evaluated the model with PR-AUC and review-capacity metrics rather than accuracy alone. On the later test period, the top 1,000 ranked transactions contained 199 known positive labels (19.9% precision and 12.35% recall). I generated model-derived reasons for the top 10,000 later-period cases, a local interactive investigation dashboard, and a two-page Power BI report. A currency-count chart from the report is pinned to a Power BI dashboard in My workspace. Isolation Forest and validated exposure-aware priority rules remain planned work.

## Before posting

Link to the [GitHub repository](https://github.com/Tansari2004/financial-crime-investigation-analytics), which includes screenshots of the Power BI report and dashboard. The verified dashboard contains the currency chart; the ranked case table is verified in the report, not yet as a tile on the same dashboard. Do not claim Isolation Forest, real-world detection performance, prevented losses, or business impact. Describe `review_score` as a ranking score rather than a crime probability. A private Power BI workspace URL should not be presented as a public demo link.
