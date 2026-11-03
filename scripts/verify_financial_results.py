"""Independent recomputation with scikit-learn and explicit stable ID tie breaks."""
import argparse
import hashlib
import json
from pathlib import Path
import warnings

import numpy as np
import pandas as pd
import sklearn
from sklearn.metrics import average_precision_score, roc_auc_score, confusion_matrix


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def check_metrics(frame, values, published, assertions):
    y = frame.is_laundering.to_numpy(dtype=int)
    ids = frame.transaction_id.to_numpy(dtype=np.int64)
    assert published['rows'] == len(y)
    assert published['positives'] == int(y.sum())
    assertions[0] += 2
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        ap = float(average_precision_score(y, values))
    assert np.isclose(ap, published['average_precision'], rtol=0, atol=1e-12)
    assert published['pr_auc'] == published['average_precision']
    assertions[0] += 2
    if 0 < y.sum() < len(y):
        assert np.isclose(roc_auc_score(y, values), published['roc_auc'], rtol=0, atol=1e-12)
    else:
        assert published['roc_auc'] is None
    assertions[0] += 1
    assert confusion_matrix(y, values >= .5, labels=[0, 1]).tolist() == published['confusion_matrix_at_0_5']
    assertions[0] += 1
    ordered = np.lexsort((ids, -values))
    for row in published['ranking']:
        k = row['k']
        found = int(y[ordered[:k]].sum())
        assert found == row['positives_found']
        assert np.isclose(found / k, row['precision'], atol=1e-15)
        assert np.isclose(found / y.sum() if y.sum() else 0, row['recall'], atol=1e-15)
        assertions[0] += 3
    return ap


def scores(frame):
    ratio = np.zeros(len(frame))
    positive = frame.prior_average_amount.to_numpy() > 0
    ratio[positive] = frame.amount_paid.to_numpy()[positive] / frame.prior_average_amount.to_numpy()[positive]
    return {'logistic': frame.review_score.to_numpy(),
            'amount_vs_prior_same_currency_average': ratio,
            'prior_transaction_frequency': frame.prior_transaction_count.to_numpy()}


def main():
    parser = argparse.ArgumentParser()
    for name in ('features', 'scores', 'metrics', 'comparison', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    metrics = json.loads(args.metrics.read_text())
    comparison = json.loads(args.comparison.read_text())
    assert sha(args.features) == metrics['features_sha256']
    assert sha(args.scores) == metrics['scores_sha256']
    predictions = pd.read_csv(args.scores, float_precision='round_trip').set_index('transaction_id')
    assert not predictions.index.duplicated().any()
    parts = []
    total_rows = training_rows = training_positives = 0
    columns = ['transaction_id', 'transaction_time', 'is_laundering', 'amount_paid',
               'prior_average_amount', 'prior_transaction_count', 'payment_currency', 'payment_format']
    for chunk in pd.read_csv(args.features, usecols=columns, chunksize=200_000, parse_dates=['transaction_time']):
        total_rows += len(chunk)
        earlier = chunk.transaction_time < pd.Timestamp('2022-09-08')
        training_rows += int(earlier.sum())
        training_positives += int(chunk.loc[earlier, 'is_laundering'].sum())
        part = chunk.loc[~earlier].copy()
        part['review_score'] = predictions.loc[part.transaction_id, 'review_score'].to_numpy()
        parts.append(part)
    frame = pd.concat(parts, ignore_index=True)
    assert frame.transaction_id.is_unique
    assert training_rows == metrics['train']['rows'] and training_positives == metrics['train']['positives']
    assertions = [4]
    independently_verified = {}
    for name, mask in {'validation': frame.transaction_time < pd.Timestamp('2022-09-09'),
                       'test': frame.transaction_time >= pd.Timestamp('2022-09-09')}.items():
        part = frame.loc[mask]
        independently_verified[name] = {}
        for method, values in scores(part).items():
            independently_verified[name][method] = check_metrics(part, values, comparison['splits'][name][method], assertions)
            if method == 'logistic':
                check_metrics(part, values, metrics[name], assertions)
    test = frame.loc[frame.transaction_time >= pd.Timestamp('2022-09-09')].copy()
    test['date'] = test.transaction_time.dt.strftime('%Y-%m-%d')
    slices = 0
    for field in ('date', 'payment_currency', 'payment_format'):
        for value, part in test.groupby(field):
            slices += 1
            for method, values in scores(part).items():
                check_metrics(part, values, comparison['test_slices'][field][str(value)][method], assertions)
    ordered = test.sort_values(['review_score', 'transaction_id'], ascending=[False, True]).head(1000)
    shortlist = {'reviewed': len(ordered), 'positive_labels': int(ordered.is_laundering.sum()),
                 'by_date': ordered.groupby('date').agg(rows=('transaction_id','size'), positives=('is_laundering','sum')).to_dict('index'),
                 'by_payment_format': ordered.groupby('payment_format').agg(rows=('transaction_id','size'), positives=('is_laundering','sum')).to_dict('index'),
                 'by_payment_currency': ordered.groupby('payment_currency').agg(rows=('transaction_id','size'), positives=('is_laundering','sum')).to_dict('index')}
    time_diagnostics = {}
    for name, mask in {'September_9_10': test.date.le('2022-09-10'),
                       'September_11_18': test.date.ge('2022-09-11')}.items():
        part = test.loc[mask]
        if part.empty:
            time_diagnostics[name] = {'rows': 0, 'positives': 0, 'prevalence': None, 'methods': {}}
            continue
        truth = part.is_laundering.to_numpy(dtype=int)
        by_method = {}
        for method, values in scores(part).items():
            order = np.lexsort((part.transaction_id.to_numpy(), -values))
            by_method[method] = {'average_precision': float(average_precision_score(truth, values)),
                                 'reviewed': min(1000, len(part)),
                                 'positive_labels_found': int(truth[order[:1000]].sum())}
        time_diagnostics[name] = {'rows': len(part), 'positives': int(truth.sum()),
                                  'prevalence': float(truth.mean()), 'methods': by_method}
    result = {'status': 'passed', 'verification': 'Independent scikit-learn AP/ROC/confusion and NumPy lexsort capacity checks',
              'reference_versions': {'scikit_learn': sklearn.__version__, 'numpy': np.__version__, 'pandas': pd.__version__},
              'total_feature_rows': total_rows, 'evaluation_rows': len(frame), 'test_slices_verified': slices,
              'metric_assertions_passed': assertions[0], 'average_precision_reference': independently_verified,
              'global_test_top_1000': shortlist,
              'post_hoc_time_diagnostics': time_diagnostics,
              'time_diagnostic_note': 'Describes the observed sharp volume/prevalence change; not a replacement holdout or model-selection result',
              'artifact_sha256': {name: sha(getattr(args, name)) for name in ('features','scores','metrics','comparison')}}
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'status': 'passed', 'rows': total_rows, 'assertions': assertions[0], 'test_slices': slices}))


if __name__ == '__main__': main()
