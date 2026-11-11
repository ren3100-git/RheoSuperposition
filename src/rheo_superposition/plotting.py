from __future__ import annotations

import numpy as np

from .readers import temp_sort_value


def get_temperature_colors(data: dict[str, dict]) -> dict[str, tuple[float, float, float]]:
    """
    Assign temperature-dependent colors.

    Low temperature  : blue  = (0, 0, 255)
    Middle temperature: green = (0, 170, 0)
    High temperature : red   = (255, 0, 0)
    """
    temps = sorted(data.keys(), key=temp_sort_value)
    values = np.array([temp_sort_value(T) for T in temps], dtype=float)

    blue = np.array([0, 0, 255], dtype=float) / 255.0
    green = np.array([0, 170, 0], dtype=float) / 255.0
    red = np.array([255, 0, 0], dtype=float) / 255.0

    if len(temps) == 1:
        return {T: tuple(green) for T in temps}
    if not np.all(np.isfinite(values)):
        values = np.arange(len(temps), dtype=float)

    vmin = np.min(values)
    vmax = np.max(values)

    if vmax == vmin:
        return {T: tuple(green) for T in temps}

    colors = {}

    for T, v in zip(temps, values):
        p = (v - vmin) / (vmax - vmin)

        if p <= 0.5:
            q = p / 0.5
            color = blue * (1.0 - q) + green * q
        else:
            q = (p - 0.5) / 0.5
            color = green * (1.0 - q) + red * q

        colors[T] = tuple(color)

    return colors


def set_equal_log_decade_aspect(ax) -> None:
    """Make one logarithmic decade occupy the same physical length on x and y."""
    x_min, x_max = ax.get_xlim()
    y_min, y_max = ax.get_ylim()

    values = np.asarray([x_min, x_max, y_min, y_max], dtype=float)
    if not np.all(np.isfinite(values)) or np.any(values <= 0):
        return
    if x_min >= x_max or y_min >= y_max:
        return

    x_decades = float(np.log10(x_max) - np.log10(x_min))
    y_decades = float(np.log10(y_max) - np.log10(y_min))
    if x_decades <= 0 or y_decades <= 0:
        return

    # H / W = y decades / x decades gives identical physical length per decade.
    ax.set_box_aspect(y_decades / x_decades)


def balance_preview_axes(gp_ax, tan_ax) -> None:
    """Align widths while preserving equal log-decade lengths and all data."""
    x_min = min(gp_ax.get_xlim()[0], tan_ax.get_xlim()[0])
    x_max = max(gp_ax.get_xlim()[1], tan_ax.get_xlim()[1])
    x_decades = np.log10(x_max) - np.log10(x_min)
    y_logs = [np.log10(ax.get_ylim()) for ax in (gp_ax, tan_ax)]
    # Expand only the display limits; never crop data to achieve the layout.
    gp_aspect = max(0.5, np.diff(y_logs[0])[0] / x_decades,
                    np.diff(y_logs[1])[0] / x_decades / 0.6)
    for ax, limits, aspect in zip((gp_ax, tan_ax), y_logs, (gp_aspect, gp_aspect * 0.6)):
        center = np.mean(limits)
        half_span = x_decades * aspect / 2
        ax.set_xlim(x_min, x_max)
        ax.set_ylim(10 ** (center - half_span), 10 ** (center + half_span))
        set_equal_log_decade_aspect(ax)
    grid = gp_ax.get_subplotspec().get_gridspec()
    if grid is tan_ax.get_subplotspec().get_gridspec() and grid.get_geometry() == (2, 1):
        grid.set_height_ratios((5, 3))
    gp_ax.set_title("Storage / loss modulus", loc="left", fontsize=11)
    tan_ax.set_title("Loss tangent", loc="left", fontsize=11)
    gp_ax.set_xlabel("")
    gp_ax.tick_params(axis="x", labelbottom=False)


def draw_unshifted_preview(gp_ax, tan_ax, data: dict[str, dict] | None, colors=None) -> None:
    """Draw cleaned, unshifted data actually used by the analysis."""
    gp_ax.clear()
    tan_ax.clear()
    tan_ax.set_visible(True)
    gp_ax.set_subplotspec(gp_ax.get_subplotspec().get_gridspec()[0, 0])
    if data and "response" in next(iter(data.values())):
        tan_ax.set_visible(False)
        gp_ax.set_subplotspec(gp_ax.get_subplotspec().get_gridspec()[:, 0])
        colors = colors or get_temperature_colors(data)
        for label, d in data.items():
            gp_ax.plot(d["time"], d["response"], color=colors[label], label=label,
                       marker="o", markersize=2, linewidth=0.9)
        gp_ax.set_xscale("log")
        gp_ax.set_yscale("log")
        gp_ax.set_xlabel("t")
        gp_ax.set_ylabel(d["response_name"] + "(t)")
        gp_ax.set_title("Unshifted " + d["measurement"] + " data")
        gp_ax.legend(fontsize=8)
        set_equal_log_decade_aspect(gp_ax)
        return

    for ax in (gp_ax, tan_ax):
        ax.grid(False, which="both")

    if not data:
        gp_ax.set_xscale("log")
        gp_ax.set_yscale("log")
        gp_ax.set_xlabel(r"$\omega$")
        gp_ax.set_ylabel(r"$G', G''$")
        tan_ax.set_xscale("log")
        tan_ax.set_yscale("log")
        tan_ax.set_xlabel(r"$\omega$")
        tan_ax.set_ylabel(r"$\tan\delta$")
        balance_preview_axes(gp_ax, tan_ax)
        return

    colors = colors or get_temperature_colors(data)
    for temperature in sorted(data, key=temp_sort_value):
        d = data[temperature]
        color = colors.get(temperature, (0.5, 0.5, 0.5))
        omega = np.asarray(d["omega"], dtype=float)
        gp = np.asarray(d["Gp"], dtype=float)
        gpp = np.asarray(d["Gpp"], dtype=float)
        tan_delta = np.asarray(d["tan_delta"], dtype=float)

        gp_ax.plot(
            omega, gp, linestyle="-", linewidth=0.9, marker="o", markersize=3.0,
            markerfacecolor="none", markeredgecolor=color, color=color,
        )
        gp_ax.plot(
            omega, gpp, linestyle="-", linewidth=0.9, marker="o", markersize=3.0,
            markerfacecolor=color, markeredgecolor=color, color=color,
        )
        tan_ax.plot(
            omega, tan_delta, linestyle="-", linewidth=0.9, marker="^", markersize=3.0,
            markerfacecolor=color, markeredgecolor=color, color=color,
        )

    gp_ax.set_xscale("log")
    gp_ax.set_yscale("log")
    gp_ax.set_xlabel(r"$\omega$")
    gp_ax.set_ylabel(r"$G', G''$")

    tan_ax.set_xscale("log")
    tan_ax.set_yscale("log")
    tan_ax.set_xlabel(r"$\omega$")
    tan_ax.set_ylabel(r"$\tan\delta$")

    for ax in (gp_ax, tan_ax):
        ax.relim()
        ax.autoscale_view()
    balance_preview_axes(gp_ax, tan_ax)


def condition_positions(labels, scale="linear"):
    """Return numerical conditions, or categorical positions on a linear axis."""
    if scale not in {"linear", "log"}:
        raise ValueError("Condition axis scale must be linear or log.")
    values = np.asarray([temp_sort_value(label) for label in labels], dtype=float)
    numeric = bool(np.all(np.isfinite(values)))
    if scale == "log" and (not numeric or np.any(values <= 0)):
        raise ValueError("A logarithmic Condition axis requires positive numeric conditions. Select linear for zero, negative values or text labels.")
    return (values if numeric else np.arange(len(values), dtype=float)), numeric


def configure_condition_axis(ax, labels, scale="linear", axis_label="Condition"):
    """Configure scale, ticks and padded limits without changing the data."""
    positions, numeric = condition_positions(labels, scale)
    # Reset locators too, allowing categorical/linear/log axes to be switched.
    ax.set_xscale(scale)
    ax.set_xlabel(axis_label)
    if len(positions):
        if scale == "log":
            limits = np.log10([np.min(positions), np.max(positions)])
            padding = max(float(np.diff(limits)[0]) * .08, .1)
            ax.set_xlim(10. ** (limits[0] - padding), 10. ** (limits[1] + padding))
        else:
            lower, upper = float(np.min(positions)), float(np.max(positions))
            padding = (upper - lower) * .08 if upper > lower else max(abs(lower)*.08, .5)
            ax.set_xlim(lower - padding, upper + padding)
        if not numeric:
            ax.set_xticks(positions, list(labels))
    return positions
