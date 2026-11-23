import math

import numpy as np

from revision_r1.analyze import View, counts


def case(seed, mix, value, node=4):
    return {'root_seed': seed, 'mix': mix, 'nodes': node, 'ccr': .5, 'failure_fraction': .6, 'x': value}


def test_equal_mix_weighting_and_root_resampling():
    data = [case(s, 'A', 1) for s in (0, 1)] + [case(s, 'B', 9, n) for s in (0, 1) for n in (4, 8)]
    result = View(data).effect(lambda c: c['x'])
    assert result['point'] == 5
    assert result['ci95'] == [5, 5]
    assert np.all(counts(2).sum(axis=1) == 2)


def test_missing_group_never_becomes_zero():
    data = [case(s, m, None if m == 'B' else 2) for s in (0, 1) for m in ('A', 'B')]
    result = View(data).effect(lambda c: c['x'])
    assert result['point'] is None and result['ci95'] is None
    assert result['defined_bootstrap_draws'] == 0


def test_ragged_grid_preserves_original_root_population():
    data = [case(0, 'A', 4), case(1, 'A', 8), case(0, 'B', 10)]
    result = View(data, roots=(0, 1)).effect(lambda c: c['x'])
    assert result['point'] == 8
    assert result['undefined_pairs'] == 1
    assert result['ci95'] is None  # Some samples draw only root 1; B is then undefined.


def test_relative_cdi_is_ratio_of_means_including_zero_cases():
    data = [case(0, 'A', 0), case(1, 'A', 2)]
    result = View(data).ratio(lambda c: c['x'], lambda c: 2 * c['x'])
    assert result['point'] == -.5
    assert result['ci95'] is None  # All-zero resamples remain undefined, never silently dropped.


def test_nonzero_ratio_is_paired_by_the_same_root_draw():
    data = [case(0, 'A', 2), case(1, 'A', 4)]
    result = View(data).ratio(lambda c: 1.5 * c['x'], lambda c: c['x'])
    assert math.isclose(result['point'], .5)
    assert np.allclose(result['ci95'], [.5, .5])
