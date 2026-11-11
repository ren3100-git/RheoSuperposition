from __future__ import annotations

import numpy as np


def custom_composite_point_loss(
    residuals: np.ndarray,
    b: float = 0.1,
    c: float = 0.5,
) -> np.ndarray:
    """Return pointwise custom loss values.

    rho(x) =
        b x^4 / ((0.481 c)^2 + |x|^3)
        + x^2 / ((0.333 c)^2 + x^2)
    """
    if not np.isfinite(b) or b <= 0:
        raise ValueError("Loss parameter b must be positive and finite.")
    if not np.isfinite(c) or c <= 0:
        raise ValueError("Loss parameter c must be positive and finite.")

    x = np.asarray(residuals, dtype=float)
    abs_x = np.abs(x)
    x2 = x**2
    large_difference_term = float(b) * x2**2 / ((0.481 * float(c)) ** 2 + abs_x**3)
    quadratic_term = x2 / ((0.333 * float(c)) ** 2 + x2)
    return large_difference_term + quadratic_term


def custom_composite_loss(
    residuals: np.ndarray,
    b: float = 0.1,
    c: float = 0.5,
) -> float:
    """Return the mean custom composite loss over finite residuals."""
    x = np.asarray(residuals, dtype=float)
    x = x[np.isfinite(x)]
    if x.size == 0:
        return np.inf
    return float(np.mean(custom_composite_point_loss(x, b=b, c=c)))
