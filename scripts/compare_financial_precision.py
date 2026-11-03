"""Compare matched full-precision and rounded-control runs without retuning."""
import argparse
from collections import Counter
import json
from pathlib import Path

import numpy as np
import pandas as pd

from financial_crime.train_model import file_sha256


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--full', type=Path, required=True)
    parser.add_argument('--rounded', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    full_import = json.loads((args.full / 'precision_import.json').read_text())
    old_import = json.loads((args.rounded / 'precision_import.json').read_text())
    assert full_import['source_sha256'] == old_import['source_sha256']
    assert old_import['amount_mode'] == 'rounded_control_18_2'
    count = paid_changed = prior_changed = 0
    paid_max = prior_max = 0.0
    currencies = Counter()
    for a, b in zip(pd.read_csv(args.full / 'model_features.csv.gz', chunksize=200_000),
                    pd.read_csv(args.rounded / 'model_features.csv.gz', chunksize=200_000), strict=True):
        unchanged = [column for column in a if column not in ('amount_paid', 'prior_average_amount')]
        assert a[unchanged].equals(b[unchanged]), 'Non-amount feature/order/label changed'
        count += len(a)
        paid_delta = np.abs(a.amount_paid.to_numpy() - b.amount_paid.to_numpy())
        prior_delta = np.abs(a.prior_average_amount.to_numpy() - b.prior_average_amount.to_numpy())
        changed = paid_delta > 0
        paid_changed += int(changed.sum())
        prior_changed += int((prior_delta > 0).sum())
        paid_max = max(paid_max, float(paid_delta.max()))
        prior_max = max(prior_max, float(prior_delta.max()))
        currencies.update(a.loc[changed, 'payment_currency'])
    assert count == full_import['rows'] == old_import['rows']
    assert paid_changed == full_import['paid_rows_with_more_than_two_decimal_precision']
    fm = json.loads((args.full / 'metrics.json').read_text())
    rm = json.loads((args.rounded / 'metrics.json').read_text())
    assert fm['training_settings'] == rm['training_settings']
    assert fm['train'] == rm['train']
    for folder, meta in ((args.full, fm), (args.rounded, rm)):
        assert file_sha256(folder / 'model_features.csv.gz') == meta['features_sha256']
        assert file_sha256(folder / 'scores.csv.gz') == meta['scores_sha256']
    a = pd.read_csv(args.full / 'scores.csv.gz', float_precision='round_trip')
    b = pd.read_csv(args.rounded / 'scores.csv.gz', float_precision='round_trip')
    assert a.transaction_id.is_unique and b.transaction_id.is_unique
    assert a.transaction_id.equals(b.transaction_id) and a.data_split.equals(b.data_split)
    score_delta = np.abs(a.review_score.to_numpy() - b.review_score.to_numpy())
    test_a = a.loc[a.data_split.eq('test')].sort_values(['review_score', 'transaction_id'], ascending=[False, True])
    test_b = b.loc[b.data_split.eq('test')].sort_values(['review_score', 'transaction_id'], ascending=[False, True])
    overlap = []
    for k in (100, 500, 1000, 5000):
        common = len(set(test_a.transaction_id.head(k)) & set(test_b.transaction_id.head(k)))
        overlap.append({'k': k, 'same_transaction_ids': common, 'retained_fraction': common / k,
                        'jaccard': common / (2 * k - common)})
    report = {'status': 'completed', 'comparison': 'Same source/order/feature definitions/runtime/optimizer/settings; full decimals versus NUMERIC(18,2) import control',
              'source_sha256': full_import['source_sha256'], 'rows_compared': count,
              'non_amount_features_labels_and_order_identical': True,
              'training_settings': fm['training_settings'],
              'paid_amount_rows_changed': paid_changed, 'prior_average_rows_changed': prior_changed,
              'changed_paid_rows_by_currency': dict(currencies),
              'max_paid_amount_difference': paid_max, 'max_prior_average_difference': prior_max,
              'evaluation_score_rows': len(a), 'score_rows_changed_exactly': int((score_delta > 0).sum()),
              'max_absolute_score_change': float(score_delta.max()), 'mean_absolute_score_change': float(score_delta.mean()),
              'test_top_k_overlap': overlap,
              'full_precision_test': fm['test'], 'rounded_control_test': rm['test'],
              'full_precision_validation': fm['validation'], 'rounded_control_validation': rm['validation'],
              'historical_v1_note': 'The original published run is preserved separately; differences from it are not a controlled estimate of precision alone.',
              'artifact_sha256': {'full_features': fm['features_sha256'], 'rounded_features': rm['features_sha256'],
                                  'full_scores': fm['scores_sha256'], 'rounded_scores': rm['scores_sha256']}}
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'rows': count, 'paid_rows_changed': paid_changed, 'test_top_k_overlap': overlap}))


if __name__ == '__main__': main()
