from __future__ import annotations

import numpy as np
import pandas as pd

from .losses import custom_composite_loss
from .models import TTSConfig
from .readers import normalize_condition_label, temp_sort_value


def prepare_xy(x, y) -> tuple[np.ndarray, np.ndarray]:
    df = pd.DataFrame({"x": x, "y": y})
    df = df.replace([np.inf, -np.inf], np.nan).dropna()
    df = df.sort_values("x")
    df = df.groupby("x", as_index=False)["y"].mean()
    return df["x"].to_numpy(), df["y"].to_numpy()

def make_cubic_spline(x, y):
    # SciPy is comparatively expensive to import. Defer it until the user
    # actually starts shift estimation so the application window appears sooner.
    from scipy.interpolate import CubicSpline

    x2, y2 = prepare_xy(x, y)
    if len(x2) < 4:
        raise ValueError("CubicSpline requires at least 4 valid unique x values.")
    return CubicSpline(x2, y2, extrapolate=False), (np.min(x2), np.max(x2)), x2, y2

def normalize_shift_mode(mode: str) -> str:
    """Normalize user-facing shift-mode aliases."""
    s = str(mode).strip().lower().replace("-", "_").replace(" ", "_")

    aliases = {
        "both": "both",
        "xy": "both",
        "x_y": "both",
        "estimate_both": "both",
        "horizontal_and_vertical": "both",

        "horizontal_only": "horizontal_only",
        "aT_only": "horizontal_only",
        "at_only": "horizontal_only",
        "x_only": "horizontal_only",
        "fix_bT": "horizontal_only",
        "fix_bt": "horizontal_only",

        "vertical_only": "vertical_only",
        "bT_only": "vertical_only",
        "bt_only": "vertical_only",
        "y_only": "vertical_only",
        "fix_aT": "vertical_only",
        "fix_at": "vertical_only",

        "none": "none",
        "fixed": "none",
        "no_shift": "none",
        "identity": "none",
    }

    if s not in aliases:
        raise ValueError(
            "shift_mode must be 'both', 'horizontal_only', 'vertical_only', or 'none'."
        )

    return aliases[s]

def make_reference_in_master_frame(d: dict, log10_aT: float, log10_bT: float) -> dict:
    return {
        "omega": 10.0 ** (d["x"] + log10_aT),
        "Gp": 10.0 ** (d["logGp"] + log10_bT),
        "Gpp": 10.0 ** (d["logGpp"] + log10_bT),
        "x": d["x"] + log10_aT,
        "logGp": d["logGp"] + log10_bT,
        "logGpp": d["logGpp"] + log10_bT,
        "tan_delta": d["tan_delta"],
        "logTanDelta": d["logTanDelta"],
    }

def choose_nearest_fitted_temperature(
    T: str,
    fitted_Ts: list[str],
    row_map: dict,
    T_ref: str,
    required_success: tuple[str, ...] = ("success_aT", "success_bT"),
) -> str:
    """Choose the nearest previously fitted temperature with valid results."""
    T_val = temp_sort_value(T)
    candidates = []

    for T_fit in fitted_Ts:
        row = row_map[T_fit]
        ok = all(bool(row.get(key, False)) for key in required_success)
        if not ok:
            continue

        T_fit_val = temp_sort_value(T_fit)
        if np.isfinite(T_val) and np.isfinite(T_fit_val):
            candidates.append(T_fit)

    if len(candidates) == 0:
        valid = [t for t in fitted_Ts if all(bool(row_map[t].get(k, False)) for k in required_success)]
        return valid[-1] if valid and not np.isfinite(T_val) else T_ref

    return min(candidates, key=lambda T_fit: abs(temp_sort_value(T_fit) - T_val))

def get_temperature_fit_order(data: dict[str, dict], T_ref: str) -> list[str]:
    """Return temperatures ordered outward from the reference temperature."""
    T_ref_value = temp_sort_value(T_ref)
    other_Ts = [T for T in data if T != T_ref]

    if np.isfinite(T_ref_value):
        return sorted(
            other_Ts,
            key=lambda T: (abs(temp_sort_value(T) - T_ref_value), temp_sort_value(T)),
        )

    return sorted(other_Ts, key=temp_sort_value)

def _validate_reference_temperature(data: dict[str, dict], config: TTSConfig) -> str:
    T_ref = normalize_condition_label(config.T_ref, config)
    if T_ref not in data:
        available = ", ".join(sorted(data.keys(), key=temp_sort_value))
        raise ValueError(f"T_ref={T_ref} was not found. Available temperatures: {available}")
    return T_ref


def make_fixed_aT_result(log10_aT: float = 0.0, n_points: int = 0) -> dict:
    log10_aT = float(log10_aT)
    return {
        "log10_aT": log10_aT,
        "aT": float(10.0 ** log10_aT),
        "loss_aT": np.nan,
        "success_aT": True,
        "n_overlap_aT": int(n_points),
        "aT_search_lower": log10_aT,
        "aT_search_upper": log10_aT,
        "aT_is_fixed": True,
    }


def make_fixed_bT_result(log10_bT: float = 0.0, n_points: int = 0) -> dict:
    log10_bT = float(log10_bT)
    return {
        "log10_bT": log10_bT,
        "bT": float(10.0 ** log10_bT),
        "loss_bT": np.nan,
        "success_bT": True,
        "n_overlap_bT": int(n_points),
        "bT_search_lower": log10_bT,
        "bT_search_upper": log10_bT,
        "bT_is_fixed": True,
    }


def estimate_log10_aT(ref: dict, target: dict, config: TTSConfig) -> dict:
    from scipy.optimize import minimize_scalar

    spline, x_range, _, _ = make_cubic_spline(ref["x"], ref["logTanDelta"])
    x_t = np.asarray(target["x"], dtype=float)
    y_t = np.asarray(target["logTanDelta"], dtype=float)

    def residuals_at(log10_aT: float) -> tuple[np.ndarray | None, int]:
        x_shift = x_t + float(log10_aT)
        mask = (x_shift >= x_range[0]) & (x_shift <= x_range[1])
        mask = mask & np.isfinite(x_shift) & np.isfinite(y_t)
        n_overlap = int(np.sum(mask))
        if n_overlap < config.min_overlap_points:
            return None, n_overlap
        y_fit = spline(x_shift[mask])
        residuals = y_t[mask] - y_fit
        residuals = residuals[np.isfinite(residuals)]
        if residuals.size < config.min_overlap_points:
            return None, int(residuals.size)
        return residuals, int(residuals.size)

    def objective(log10_aT: float) -> float:
        residuals, _ = residuals_at(log10_aT)
        if residuals is None:
            return np.inf
        return custom_composite_loss(residuals, b=config.loss_b, c=config.loss_c)

    bounds = tuple(float(v) for v in config.log10_aT_bounds)
    result = minimize_scalar(
        objective,
        bounds=bounds,
        method="bounded",
        options={"xatol": 1.0e-4},
    )
    _, n_overlap = residuals_at(float(result.x))
    success = bool(result.success and np.isfinite(result.fun) and n_overlap >= config.min_overlap_points)
    return {
        "log10_aT": float(result.x),
        "aT": float(10.0 ** result.x),
        "loss_aT": float(result.fun),
        "success_aT": success,
        "n_overlap_aT": int(n_overlap),
        "aT_search_lower": bounds[0],
        "aT_search_upper": bounds[1],
        "aT_is_fixed": False,
    }


def estimate_log10_bT(ref: dict, target: dict, log10_aT: float, config: TTSConfig) -> dict:
    from scipy.optimize import minimize_scalar

    sp_gp, range_gp, _, _ = make_cubic_spline(ref["x"], ref["logGp"])
    sp_gpp, range_gpp, _, _ = make_cubic_spline(ref["x"], ref["logGpp"])

    x_shift = np.asarray(target["x"], dtype=float) + float(log10_aT)
    y_gp = np.asarray(target["logGp"], dtype=float)
    y_gpp = np.asarray(target["logGpp"], dtype=float)

    x_min = max(range_gp[0], range_gpp[0])
    x_max = min(range_gp[1], range_gpp[1])
    mask = (x_shift >= x_min) & (x_shift <= x_max)
    mask = mask & np.isfinite(x_shift) & np.isfinite(y_gp) & np.isfinite(y_gpp)
    n_overlap = int(np.sum(mask))
    if n_overlap < config.min_overlap_points:
        return {
            "log10_bT": np.nan,
            "bT": np.nan,
            "loss_bT": np.inf,
            "success_bT": False,
            "n_overlap_bT": n_overlap,
            "bT_search_lower": float(config.log10_bT_bounds[0]),
            "bT_search_upper": float(config.log10_bT_bounds[1]),
            "bT_is_fixed": False,
        }

    x_use = x_shift[mask]
    gp_use = y_gp[mask]
    gpp_use = y_gpp[mask]

    def objective(log10_bT: float) -> float:
        residuals_gp = (gp_use + float(log10_bT)) - sp_gp(x_use)
        residuals_gpp = (gpp_use + float(log10_bT)) - sp_gpp(x_use)
        residuals = np.concatenate([residuals_gp, residuals_gpp])
        return custom_composite_loss(residuals, b=config.loss_b, c=config.loss_c)

    bounds = tuple(float(v) for v in config.log10_bT_bounds)
    result = minimize_scalar(
        objective,
        bounds=bounds,
        method="bounded",
        options={"xatol": 1.0e-4},
    )
    success = bool(result.success and np.isfinite(result.fun))
    return {
        "log10_bT": float(result.x),
        "bT": float(10.0 ** result.x),
        "loss_bT": float(result.fun),
        "success_bT": success,
        "n_overlap_bT": n_overlap,
        "bT_search_lower": bounds[0],
        "bT_search_upper": bounds[1],
        "bT_is_fixed": False,
    }


def estimate_horizontal_shift_factors(data: dict[str, dict], config: TTSConfig) -> pd.DataFrame:
    if config.measurement != "dynamic":
        from .scalar import scalar_horizontal, scalar_vertical
        return scalar_horizontal(data, config)
    shift_mode = normalize_shift_mode(config.shift_mode)
    estimate_aT = shift_mode in {"both", "horizontal_only"}
    estimate_bT_later = shift_mode in {"both", "vertical_only"}
    provisional_log10_bT = 0.0 if estimate_bT_later else float(config.fixed_log10_bT)

    t_ref = _validate_reference_temperature(data, config)
    row_map = {
        t_ref: {
            "T_label": t_ref,
            "T_value": temp_sort_value(t_ref),
            "log10_aT": 0.0,
            "aT": 1.0,
            "loss_aT": 0.0,
            "success_aT": True,
            "n_overlap_aT": len(data[t_ref]["x"]),
            "aT_search_lower": 0.0,
            "aT_search_upper": 0.0,
            "log10_bT": 0.0,
            "bT": 1.0,
            "loss_bT": 0.0,
            "success_bT": True,
            "n_overlap_bT": len(data[t_ref]["x"]),
            "bT_search_lower": 0.0,
            "bT_search_upper": 0.0,
            "match_to": None,
            "match_to_aT": None,
            "match_to_bT": None,
            "log10_aT_local": 0.0,
            "aT_local": 1.0,
            "log10_bT_local": 0.0,
            "bT_local": 1.0,
            "fit_order": 0,
            "is_reference": True,
            "shift_mode": shift_mode,
            "calculation_stage": "horizontal",
            "aT_is_fixed": not estimate_aT,
            "bT_is_fixed": True,
            "loss_function": "custom_composite",
            "loss_b": float(config.loss_b),
            "loss_c": float(config.loss_c),
        }
    }

    fitted = [t_ref]
    for order, temperature in enumerate(get_temperature_fit_order(data, t_ref), start=1):
        anchor = choose_nearest_fitted_temperature(
            temperature, fitted, row_map, t_ref, required_success=("success_aT",)
        )
        anchor_row = row_map[anchor]
        local_ref = make_reference_in_master_frame(
            data[anchor], anchor_row["log10_aT"], anchor_row["log10_bT"]
        )
        at = (
            estimate_log10_aT(local_ref, data[temperature], config)
            if estimate_aT
            else make_fixed_aT_result(config.fixed_log10_aT, len(data[temperature]["x"]))
        )
        bt = make_fixed_bT_result(provisional_log10_bT, len(data[temperature]["x"]))
        local_at = float(at["log10_aT"]) - float(anchor_row["log10_aT"])
        local_bt = float(bt["log10_bT"]) - float(anchor_row["log10_bT"])
        row_map[temperature] = {
            "T_label": temperature,
            "T_value": temp_sort_value(temperature),
            **at,
            **bt,
            "match_to": anchor,
            "match_to_aT": anchor,
            "match_to_bT": None,
            "log10_aT_local": local_at,
            "aT_local": 10.0 ** local_at,
            "log10_bT_local": local_bt,
            "bT_local": 10.0 ** local_bt,
            "fit_order": order,
            "is_reference": False,
            "shift_mode": shift_mode,
            "calculation_stage": "horizontal",
            "loss_function": "custom_composite",
            "loss_b": float(config.loss_b),
            "loss_c": float(config.loss_c),
        }
        fitted.append(temperature)

    result = pd.DataFrame(row_map.values())
    result = result.sort_values("T_value", na_position="last").reset_index(drop=True)
    return add_boundary_flags(result)


def estimate_vertical_shift_factors(
    data: dict[str, dict],
    horizontal_shifts: pd.DataFrame,
    config: TTSConfig,
) -> pd.DataFrame:
    if config.measurement != "dynamic":
        from .scalar import scalar_horizontal, scalar_vertical
        return scalar_vertical(data, horizontal_shifts, config)
    shift_mode = normalize_shift_mode(config.shift_mode)
    estimate_bT = shift_mode in {"both", "vertical_only"}
    t_ref = _validate_reference_temperature(data, config)

    required = {"T_label", "log10_aT", "aT", "success_aT", "fit_order", "is_reference"}
    missing = required - set(horizontal_shifts.columns)
    if missing:
        raise ValueError("horizontal_shifts is missing columns: " + ", ".join(sorted(missing)))

    horizontal = horizontal_shifts.copy()
    horizontal["T_label"] = horizontal["T_label"].astype(str)
    if set(horizontal["T_label"]) != set(data):
        raise ValueError("Temperature mismatch between data and horizontal_shifts.")

    row_map = horizontal.set_index("T_label").to_dict(orient="index")
    row_map[t_ref].update({
        "log10_bT": 0.0,
        "bT": 1.0,
        "loss_bT": 0.0,
        "success_bT": True,
        "n_overlap_bT": len(data[t_ref]["x"]),
        "bT_search_lower": 0.0,
        "bT_search_upper": 0.0,
        "bT_is_fixed": not estimate_bT,
        "match_to": None,
        "match_to_bT": None,
        "log10_bT_local": 0.0,
        "bT_local": 1.0,
        "calculation_stage": "horizontal_and_vertical",
        "shift_mode": shift_mode,
        "loss_function": "custom_composite",
        "loss_b": float(config.loss_b),
        "loss_c": float(config.loss_c),
    })

    fit_order = sorted(
        [t for t in data if t != t_ref],
        key=lambda t: int(row_map[t].get("fit_order", 10**9)),
    )
    fitted = [t_ref]
    for temperature in fit_order:
        anchor = choose_nearest_fitted_temperature(
            temperature,
            fitted,
            row_map,
            t_ref,
            required_success=("success_aT", "success_bT"),
        )
        anchor_row = row_map[anchor]
        target_row = row_map[temperature]
        local_ref = make_reference_in_master_frame(
            data[anchor], float(anchor_row["log10_aT"]), float(anchor_row["log10_bT"])
        )
        bt = (
            estimate_log10_bT(local_ref, data[temperature], float(target_row["log10_aT"]), config)
            if estimate_bT
            else make_fixed_bT_result(config.fixed_log10_bT, len(data[temperature]["x"]))
        )
        local_bt = float(bt["log10_bT"]) - float(anchor_row["log10_bT"])
        target_row.update({
            **bt,
            "match_to": anchor,
            "match_to_bT": anchor,
            "log10_bT_local": local_bt,
            "bT_local": 10.0 ** local_bt,
            "shift_mode": shift_mode,
            "calculation_stage": "horizontal_and_vertical",
            "loss_function": "custom_composite",
            "loss_b": float(config.loss_b),
            "loss_c": float(config.loss_c),
        })
        fitted.append(temperature)

    result = pd.DataFrame([{"T_label": t, **row} for t, row in row_map.items()])
    result = result.sort_values("T_value", na_position="last").reset_index(drop=True)
    return add_boundary_flags(result)


def estimate_shift_factors(data: dict[str, dict], config: TTSConfig) -> pd.DataFrame:
    horizontal = estimate_horizontal_shift_factors(data, config)
    return estimate_vertical_shift_factors(data, horizontal, config)


def add_boundary_flags(shifts: pd.DataFrame, eps: float = 1.0e-3) -> pd.DataFrame:
    out = shifts.copy()
    out["aT_hit_lower"] = np.abs(out["log10_aT"] - out["aT_search_lower"]) < eps
    out["aT_hit_upper"] = np.abs(out["log10_aT"] - out["aT_search_upper"]) < eps
    out["bT_hit_lower"] = np.abs(out["log10_bT"] - out["bT_search_lower"]) < eps
    out["bT_hit_upper"] = np.abs(out["log10_bT"] - out["bT_search_upper"]) < eps
    ref = out["is_reference"].astype(bool) if "is_reference" in out else False
    a_fixed = out["aT_is_fixed"].astype(bool) if "aT_is_fixed" in out else False
    b_fixed = out["bT_is_fixed"].astype(bool) if "bT_is_fixed" in out else False
    out.loc[ref | a_fixed, ["aT_hit_lower", "aT_hit_upper"]] = False
    out.loc[ref | b_fixed, ["bT_hit_lower", "bT_hit_upper"]] = False
    return out


def make_shifted_dataframe(data: dict[str, dict], shifts: pd.DataFrame) -> pd.DataFrame:
    if data and "response" in next(iter(data.values())):
        from .scalar import scalar_shifted_dataframe
        return scalar_shifted_dataframe(data, shifts)
    rows = []
    shift_map = shifts.set_index("T_label").to_dict(orient="index")

    for T, d in data.items():
        s = shift_map[T]
        log10_aT = float(s["log10_aT"])
        log10_bT = float(s["log10_bT"])

        x_shifted = d["x"] + log10_aT
        omega_shifted = 10.0 ** x_shifted
        Gp_shifted = d["Gp"] * (10.0 ** log10_bT)
        Gpp_shifted = d["Gpp"] * (10.0 ** log10_bT)

        for i in range(len(d["omega"])):
            rows.append({
                "T_label": T,
                "T_value": temp_sort_value(T),
                "omega": d["omega"][i],
                "Gp": d["Gp"][i],
                "Gpp": d["Gpp"][i],
                "tan_delta": d["tan_delta"][i],
                "logTanDelta": d["logTanDelta"][i],
                "aT": 10.0 ** log10_aT,
                "bT": 10.0 ** log10_bT,
                "omega_shifted": omega_shifted[i],
                "Gp_shifted": Gp_shifted[i],
                "Gpp_shifted": Gpp_shifted[i],
                "tan_delta_shifted": d["tan_delta"][i],
            })

    return pd.DataFrame(rows).sort_values(["T_value", "omega"]).reset_index(drop=True)
