import numpy as np
import pytest

from rheo_superposition.losses import custom_composite_loss, custom_composite_point_loss


def test_loss_basic_properties():
    x = np.array([-2.0, -0.5, 0.0, 0.5, 2.0])
    y = custom_composite_point_loss(x, b=0.1, c=0.5)
    assert y[2] == pytest.approx(0.0)
    assert np.all(y >= 0)
    assert np.allclose(y, y[::-1])


def test_default_numeric_value():
    value = custom_composite_point_loss(np.array([0.5]), b=0.1, c=0.5)[0]
    expected = 0.1 * 0.5**4 / ((0.481 * 0.5) ** 2 + 0.5**3)
    expected += 0.5**2 / ((0.333 * 0.5) ** 2 + 0.5**2)
    assert value == pytest.approx(expected)


def test_b_scales_the_large_difference_term():
    x = np.array([100.0])
    low_b = custom_composite_point_loss(x, b=0.1, c=0.5)[0]
    high_b = custom_composite_point_loss(x, b=0.2, c=0.5)[0]

    assert high_b - low_b == pytest.approx(10.0, rel=1e-4)


def test_nonfinite_values_are_ignored():
    value = custom_composite_loss(np.array([0.0, np.nan, np.inf]), b=0.1, c=0.5)
    assert value == pytest.approx(0.0)


def test_invalid_parameters():
    with pytest.raises(ValueError):
        custom_composite_loss(np.array([1.0]), b=0.0, c=0.5)
    with pytest.raises(ValueError):
        custom_composite_loss(np.array([1.0]), b=0.1, c=0.0)
