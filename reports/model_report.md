# Logistic baseline results

Model: `numpy_logistic_v1`, a class-weighted logistic regression trained in chunks with NumPy.

## Chronological split

| Split | Dates | Rows | Positive labels | Prevalence |
|---|---|---:|---:|---:|
| Train | Before September 8, 2022 | 3,731,672 | 3,027 | 0.0811% |
| Validation | September 8, 2022 | 482,773 | 539 | 0.1116% |
| Test | September 9 onward | 863,900 | 1,611 | 0.1865% |

Later dates have a higher positive-label rate. This distribution shift is part of the synthetic dataset and limits how broadly test performance can be interpreted.

## Test metrics

| Metric | Result |
|---|---:|
| PR-AUC / average precision | 0.1016 |
| ROC-AUC | 0.9330 |
| Precision at score 0.5 | 0.0126 |
| Recall at score 0.5 | 0.9174 |

The 0.5 cutoff creates 116,179 false positives, so it is not a practical alert threshold. The ranking metrics below better reflect limited investigator capacity.

| Review capacity | Positive labels found | Precision@K | Recall@K |
|---:|---:|---:|---:|
| 100 | 35 | 35.0% | 2.17% |
| 500 | 103 | 20.6% | 6.39% |
| 1,000 | 199 | 19.9% | 12.35% |
| 5,000 | 592 | 11.84% | 36.75% |

At K=1,000, precision is about 107 times the 0.1865% test prevalence. This is enrichment within this synthetic time split, not real-world business impact.

## Interpretation

The largest positive model coefficients include ACH payment format, larger amounts, higher prior average amounts, and several currency indicators. Coefficients show associations after feature scaling; they do not prove causation or wrongdoing. The prominence of payment format and currency may reflect the simulator's construction.

`review_score` is useful for ordering cases. Class weighting changes calibration, so it must not be described as the probability of a crime. Labels were excluded from model inputs and used only for training targets and evaluation.

## Limitations

- Synthetic data and a short 18-day observation window.
- Strong time-based label shift, especially in the last dates.
- Historical features use earlier calendar days, not intraday history.
- No hyperparameter search, probability calibration, external validation, or real investigator feedback.
- No claim that a high score proves laundering.
