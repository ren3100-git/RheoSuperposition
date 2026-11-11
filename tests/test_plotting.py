from __future__ import annotations

import numpy as np
from matplotlib.figure import Figure

from rheo_superposition.plotting import draw_unshifted_preview


def _decade_ratio(ax) -> float:
    x_min, x_max = ax.get_xlim()
    y_min, y_max = ax.get_ylim()
    return np.log10(y_max / y_min) / np.log10(x_max / x_min)


def test_input_preview_uses_equal_physical_length_per_decade() -> None:
    omega = np.logspace(-2, 2, 9)
    gp = 100.0 * omega ** 0.5
    gpp = 20.0 * omega ** 0.25
    data = {
        "25": {
            "omega": omega,
            "Gp": gp,
            "Gpp": gpp,
            "tan_delta": gpp / gp,
        }
    }

    figure = Figure(figsize=(8, 8))
    gp_ax = figure.add_subplot(2, 1, 1)
    tan_ax = figure.add_subplot(2, 1, 2)
    draw_unshifted_preview(gp_ax, tan_ax, data)

    assert np.isclose(gp_ax.get_box_aspect(), _decade_ratio(gp_ax))
    assert np.isclose(tan_ax.get_box_aspect(), _decade_ratio(tan_ax))


def test_preview_axes_have_aligned_widths_and_balanced_heights():
    from matplotlib.backends.backend_agg import FigureCanvasAgg

    omega = np.logspace(-2, 2, 9)
    gp = 100 * omega ** 0.5
    gpp = 20 * omega ** 0.25
    figure = Figure(figsize=(10, 8))
    grid = figure.add_gridspec(2, 1, height_ratios=(5, 3))
    gp_ax, tan_ax = [figure.add_subplot(grid[i, 0]) for i in range(2)]
    draw_unshifted_preview(gp_ax, tan_ax, {
        "25": {"omega": omega, "Gp": gp, "Gpp": gpp, "tan_delta": gpp / gp},
    })
    FigureCanvasAgg(figure).draw()
    upper, lower = gp_ax.get_position(), tan_ax.get_position()
    assert np.isclose(upper.width, lower.width)
    assert np.isclose(upper.x0, lower.x0)
    assert np.isclose(upper.height / lower.height, 5 / 3)
    assert gp_ax.get_xlim() == tan_ax.get_xlim()
    assert gp_ax.get_ylim()[0] <= min(gp.min(), gpp.min())
    assert gp_ax.get_ylim()[1] >= max(gp.max(), gpp.max())
