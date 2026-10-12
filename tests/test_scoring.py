import pytest

from kairos.scoring import clv, outcome_from_goals, rps


def test_rps_perfect_and_worst():
    assert rps([1, 0, 0], 0) == 0
    assert rps([0, 0, 1], 0) == 1


def test_rps_uniform_draw():
    assert rps([1 / 3, 1 / 3, 1 / 3], 1) == pytest.approx(1 / 9, abs=1e-6)


def test_clv():
    assert clv(2.27, 2.05) == pytest.approx(0.1073, abs=1e-4)
    assert clv(3.20, 3.45) < 0


def test_outcome_from_goals():
    assert outcome_from_goals(2, 1) == 0
    assert outcome_from_goals(1, 1) == 1
    assert outcome_from_goals(0, 3) == 2
