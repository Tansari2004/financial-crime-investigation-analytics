import itertools
import warnings

import numpy as np
import pytest
from sklearn.metrics import average_precision_score

from financial_crime.train_model import average_precision, ranking_at_k


def test_tied_score_permutations_match_reference():
    for labels in itertools.product((0, 1), repeat=4):
        for scores in ([.5] * 4, [.2, .5, .5, .8], [.1, .2, .3, .4]):
            y, s = np.array(labels), np.array(scores)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                expected = average_precision_score(y, s)
            assert average_precision(y, s) == pytest.approx(expected)
            for order in ([3, 2, 1, 0], [1, 0, 3, 2]):
                assert average_precision(y[order], s[order]) == pytest.approx(expected)


def test_random_rounded_scores_match_reference():
    rng = np.random.default_rng(42)
    for _ in range(20):
        y = rng.integers(0, 2, 200)
        s = np.round(rng.random(200), 1)
        assert average_precision(y, s) == pytest.approx(average_precision_score(y, s))


@pytest.mark.parametrize("labels,scores", [([], []), ([0, 2], [.1, .2]), ([1], [np.nan]), ([0], [.1, .2])])
def test_invalid_metric_input_fails(labels, scores):
    with pytest.raises(ValueError):
        average_precision(np.array(labels), np.array(scores))


def test_capacity_ties_use_stable_source_order():
    assert ranking_at_k(np.array([1, 0, 0]), np.array([.5, .5, .5]), 1)["positives_found"] == 1
