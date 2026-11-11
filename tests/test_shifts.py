import numpy as np

from rheo_superposition.models import TTSConfig
from rheo_superposition.shifts import estimate_horizontal_shift_factors, estimate_vertical_shift_factors


def _series(x, log_gp, log_gpp):
    gp = 10.0 ** log_gp
    gpp = 10.0 ** log_gpp
    return {
        "omega": 10.0 ** x,
        "Gp": gp,
        "Gpp": gpp,
        "x": x,
        "logGp": log_gp,
        "logGpp": log_gpp,
        "tan_delta": gpp / gp,
        "logTanDelta": log_gpp - log_gp,
    }


def test_reference_factors_are_one():
    x = np.linspace(-2, 2, 41)
    data = {"25": _series(x, 1.5 + 0.4*x, 1.1 + 0.7*x + 0.04*x**2)}
    config = TTSConfig(T_ref="25")
    h = estimate_horizontal_shift_factors(data, config)
    v = estimate_vertical_shift_factors(data, h, config)
    assert float(v.loc[0, "aT"]) == 1.0
    assert float(v.loc[0, "bT"]) == 1.0


def test_known_shift_is_recovered_approximately():
    x_ref = np.linspace(-2.5, 2.5, 81)
    gp_fun = lambda z: 1.4 + 0.32*z + 0.055*z**2
    gpp_fun = lambda z: 1.0 + 0.64*z + 0.035*z**2 + 0.015*z**3
    true_a = 0.55
    true_b = -0.35
    x_target = np.linspace(-2.0, 2.0, 65)
    data = {
        "25": _series(x_ref, gp_fun(x_ref), gpp_fun(x_ref)),
        "35": _series(
            x_target,
            gp_fun(x_target + true_a) - true_b,
            gpp_fun(x_target + true_a) - true_b,
        ),
    }
    config = TTSConfig(
        T_ref="25",
        log10_aT_bounds=(-1.5, 1.5),
        log10_bT_bounds=(-1.5, 1.5),
        min_overlap_points=10,
        loss_b=0.1,
        loss_c=0.5,
    )
    h = estimate_horizontal_shift_factors(data, config)
    v = estimate_vertical_shift_factors(data, h, config)
    row = v[v["T_label"] == "35"].iloc[0]
    assert abs(float(row["log10_aT"]) - true_a) < 0.08
    assert abs(float(row["log10_bT"]) - true_b) < 0.08
