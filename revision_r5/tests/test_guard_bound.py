"""Numerical checks of the guard proposition's assumptions and tight cases."""
import math
import random


def test_accepted_forecasts_obey_completion_bound_over_adversarial_errors():
    rng = random.Random(83005)
    for _ in range(5000):
        eta = rng.uniform(0, .95)
        gamma = rng.uniform(.2, 2)
        reference_real = 10 ** rng.uniform(-3, 3)
        reference_error = rng.uniform(1 - eta, 1 + eta)
        selected_error = rng.uniform(1 - eta, 1 + eta)
        reference_prediction = reference_error * reference_real
        selected_prediction = gamma * reference_prediction * rng.random()
        selected_real = selected_prediction / selected_error
        assert selected_real / reference_real <= gamma * (1 + eta) / (1 - eta) + 1e-12


def test_upper_bound_is_attained_and_exact_prediction_is_special_case():
    for eta in (0, .01, .05, .3, .9):
        for gamma in (.8, 1, 1.05, 2):
            cr, hr = 1.0, 1 + eta
            hp = gamma * hr
            cp = hp / (1 - eta)
            assert math.isclose(hp, (1 - eta) * cp)
            assert math.isclose(hr, (1 + eta) * cr)
            assert math.isclose(cp / cr, gamma * (1 + eta) / (1 - eta))
            if eta == 0:
                assert cp / cr == gamma


def test_calibrated_threshold_exposes_loss_of_reference_witness():
    delta = .05
    threshold_eta = delta / (2 + delta)
    gamma_at_threshold = (1 + delta) * (1 - threshold_eta) / (1 + threshold_eta)
    assert math.isclose(gamma_at_threshold, 1)
    for eta in (.03, .1, .3):
        gamma = (1 + delta) * (1 - eta) / (1 + eta)
        assert gamma < 1
        assert math.isclose(gamma * (1 + eta) / (1 - eta), 1 + delta)
        reference_prediction = 100.0
        assert not reference_prediction <= gamma * reference_prediction


def test_same_forecast_cap_does_not_imply_same_realized_cap_under_error():
    eta, gamma = .05, 1.05
    reference_prediction = 1 + eta
    selected_prediction = gamma * reference_prediction
    reference_real = 1.0
    selected_real = selected_prediction / (1 - eta)
    assert selected_prediction <= gamma * reference_prediction
    assert selected_real > gamma * reference_real
