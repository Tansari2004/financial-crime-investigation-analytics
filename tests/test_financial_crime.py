"""Numerical and explanation regressions for the investigation model."""
import numpy as np
import pandas as pd
import pytest

from financial_crime.train_model import average_precision, evaluate, ranking_at_k, split_names


def test_average_precision_groups_tied_scores():
    # A constant model has AP equal to prevalence, independent of input order.
    scores = np.array([.5, .5, .5, .5])
    for labels in [np.array([0, 1, 0, 1]), np.array([1, 1, 0, 0])]:
        assert average_precision(labels, scores) == pytest.approx(.5)


def test_missing_timestamp_is_not_silently_assigned_to_test():
    with pytest.raises(ValueError, match='timestamp'):
        split_names(pd.Series([pd.Timestamp('2022-09-01'), pd.NaT]))


def test_evaluation_rejects_invalid_scores():
    with pytest.raises(ValueError, match='finite'):
        evaluate(np.array([0, 1]), np.array([.4, np.nan]))


def test_score_ties_use_transaction_id_like_the_sql_queue():
    labels = np.array([1, 0, 0])
    scores = np.array([.8, .8, .2])
    assert ranking_at_k(labels, scores, 1, np.array([20, 10, 30]))['positives_found'] == 0
    assert ranking_at_k(labels[::-1], scores[::-1], 1, np.array([30, 10, 20]))['positives_found'] == 0


def test_average_precision_matches_hand_calculated_threshold_steps():
    # At .9, precision=1 and recall=1/2; at .5, precision=2/3 and recall=1.
    assert average_precision(np.array([1,0,1]), np.array([.9,.5,.5])) == pytest.approx(5/6)


def test_chronological_boundary_days():
    times = pd.Series(pd.to_datetime(['2022-09-07 23:59','2022-09-08 00:00','2022-09-09 00:00']))
    assert split_names(times).tolist() == ['train','validation','test']


@pytest.mark.parametrize('labels,scores', [([], []), ([0,2],[.1,.9]), ([0,1],[.1,1.1])])
def test_evaluation_fails_instead_of_emitting_invalid_metrics(labels,scores):
    with pytest.raises(ValueError):
        evaluate(np.array(labels),np.array(scores))


def test_unknown_category_stays_separate_and_labels_are_not_features():
    from financial_crime.train_model import CATEGORICAL_FEATURES, NUMERIC_FEATURES, design_matrix
    frame = example_features()
    maps = {c: {'known':0} for c in CATEGORICAL_FEATURES}
    x = design_matrix(frame, np.zeros(len(NUMERIC_FEATURES)), np.ones(len(NUMERIC_FEATURES)), maps)
    frame['is_laundering'] = 1-frame.is_laundering
    assert np.array_equal(x,design_matrix(frame,np.zeros(len(NUMERIC_FEATURES)),np.ones(len(NUMERIC_FEATURES)),maps))
    assert x[0,len(NUMERIC_FEATURES)+1] == 1


def example_features():
    return pd.DataFrame({
        'transaction_id':[1,2], 'transaction_time':pd.to_datetime(['2022-09-01','2022-09-09']),
        'is_laundering':[0,1], 'amount_paid':[100.,200.], 'prior_transaction_count':[2.,4.],
        'prior_average_amount':[50.,75.], 'same_bank':[0,1], 'self_transfer':[0,0],
        'has_prior_history':[1,1], 'transaction_hour':[9,10], 'transaction_weekday':[4,5],
        'payment_currency':['USD','USD'],'receiving_currency':['USD','USD'],'payment_format':['Wire','Wire']})


def test_explanations_reconstruct_and_reject_nonfinite_saved_scores():
    from financial_crime.explain_cases import explain
    from financial_crime.train_model import CATEGORICAL_FEATURES,NUMERIC_FEATURES,design_matrix,sigmoid
    frame=example_features();maps={c:{'USD' if c!='payment_format' else 'Wire':0} for c in CATEGORICAL_FEATURES}
    names=list(NUMERIC_FEATURES)
    for c in CATEGORICAL_FEATURES:names += [f'{c}={value}' for value in maps[c]]+[f'{c}=UNKNOWN']
    model={'mean':np.zeros(len(NUMERIC_FEATURES)),'scale':np.ones(len(NUMERIC_FEATURES)),
           'weights':np.linspace(-.1,.1,len(names)),'bias':np.array(.1),'feature_names':np.array(names)}
    frame['review_score']=sigmoid(design_matrix(frame,model['mean'],model['scale'],maps) @ model['weights']+.1)
    result=explain(frame,model)
    assert result.score_reconstruction_gap.max()<1e-12
    frame.loc[0,'review_score']=np.nan
    with pytest.raises(ValueError,match='reconstruct'):explain(frame,model)


def test_invalid_features_are_rejected_before_scoring():
    from financial_crime.train_model import validate_features
    frame=example_features();frame.loc[0,'amount_paid']=-1
    with pytest.raises(ValueError,match='nonnegative'):validate_features(frame)


def test_auc_reports_undefined_for_single_class_and_handles_ties():
    from financial_crime.train_model import roc_auc
    assert roc_auc(np.array([0,0]),np.array([.2,.4])) is None
    assert roc_auc(np.array([0,1]),np.array([.5,.5])) == pytest.approx(.5)


def test_cli_rejects_zero_epochs_before_writing_outputs(tmp_path):
    import subprocess,sys
    result=subprocess.run([sys.executable,'-m','financial_crime.train_model','--epochs','0'],cwd=tmp_path,text=True,capture_output=True)
    assert result.returncode!=0 and 'must be positive' in result.stderr
    assert not (tmp_path/'data/processed/model_scores.csv').exists()
