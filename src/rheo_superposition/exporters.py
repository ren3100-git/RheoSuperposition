from __future__ import annotations

from pathlib import Path
import json

import numpy as np
import pandas as pd

from .models import TTSConfig
from .readers import normalize_stacked_variable_label, parse_rheology_input
from .shifts import estimate_shift_factors, make_shifted_dataframe


def public_shift_table(shifts, config):
    out = shifts.copy()
    out["measurement"] = config.measurement
    out["condition_name"] = config.condition_name
    out["condition_unit"] = config.condition_unit
    out["reference_condition"] = config.T_ref
    out["x_transform"] = "x_shifted = x * a_x"
    out["y_transform"] = "y_shifted = y * b_y"
    out = out.rename(columns={c: c.replace("T_label", "condition").replace("T_value", "condition_value").replace("aT", "a_x").replace("bT", "b_y") for c in out.columns})
    return out


def save_tts_outputs(
    data: dict[str, dict],
    shifts: pd.DataFrame,
    config: TTSConfig,
) -> pd.DataFrame | None:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    export_shifts = shifts.copy()
    export_shifts["loss_function"] = "custom_composite"
    export_shifts["loss_b"] = float(config.loss_b)
    export_shifts["loss_c"] = float(config.loss_c)
    public_shift_table(export_shifts, config).to_csv(config.output_dir / "rheo_shift_factors.csv", index=False)
    metadata = dict(measurement=config.measurement, condition_name=config.condition_name,
                    condition_unit=config.condition_unit, reference_condition=config.T_ref,
                    input_scale=config.input_scale, shift_mode=config.shift_mode,
                    x_transform="x_shifted = x * a_x", y_transform="y_shifted = y * b_y",
                    factor_note="a_x is the direct multiplier of the plotted horizontal variable. For time data, a_x = 1/a_T when a_T is defined by t_reduced = t/a_T. b_y is the direct response multiplier; no reciprocal modulus/compliance convention is imposed.")
    (config.output_dir / "analysis_metadata.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")

    if config.save_shifted_data:
        shifted = make_shifted_dataframe(data, export_shifts)
        shifted = shifted.rename(columns={"T_label": "condition", "T_value": "condition_value", "aT": "a_x", "bT": "b_y"})
        shifted.to_csv(config.output_dir / "rheo_shifted_data.csv", index=False)
        return shifted
    return None


def run_tts(config: TTSConfig):
    data, _ = parse_rheology_input(config)
    shifts = estimate_shift_factors(data, config)
    shifted = save_tts_outputs(data, shifts, config)
    return data, shifts, shifted


def run_tts_full(config: TTSConfig):
    data, trace_map = parse_rheology_input(config)
    shifts = estimate_shift_factors(data, config)
    shifted = save_tts_outputs(data, shifts, config)
    return data, shifts, shifted, trace_map

def build_igor_trace_shift_commands(
    trace_map: pd.DataFrame,
    shifts: pd.DataFrame,
    input_scale: str = "linear",
    graph_name: str = "",
    include_reference: bool = True,
    include_g1: bool = True,
    include_g2: bool = True,
    skip_failed: bool = True,
    measurement: str = "dynamic",
) -> str:
    """
    Generate IGOR commands to shift already plotted traces on a graph.

    This function does not create new waves. It uses ModifyGraph offset or
    muloffset to move existing G1/G2 traces only on the graph display.

    linear data:
        ModifyGraph muloffset(trace)={aT,bT}

    log10 data:
        ModifyGraph offset(trace)={log10_aT,log10_bT}

    ln data:
        ModifyGraph offset(trace)={ln(aT),ln(bT)}
    """
    required_trace_cols = {"T_label", "var", "trace"}
    missing_trace_cols = required_trace_cols - set(trace_map.columns)
    if missing_trace_cols:
        raise ValueError(f"trace_map is missing columns: {sorted(missing_trace_cols)}")

    required_shift_cols = {"T_label", "aT", "bT", "log10_aT", "log10_bT"}
    missing_shift_cols = required_shift_cols - set(shifts.columns)
    if missing_shift_cols:
        raise ValueError(f"shifts is missing columns: {sorted(missing_shift_cols)}")

    input_scale = str(input_scale).lower()
    if input_scale not in {"linear", "log10", "ln"}:
        raise ValueError("input_scale must be 'linear', 'log10', or 'ln'.")

    def _escape_igor_string(s: str) -> str:
        return str(s).replace("\\", "\\\\").replace('"', '\\"')

    def _window_option(name: str) -> str:
        name = str(name).strip()
        if name == "":
            return ""
        return f'/W=$"{_escape_igor_string(name)}" '

    def _trace_name(name: str) -> str:
        # Expected values are ordinary IGOR trace names such as Gp25 or Gp25#1.
        # If the same wave is plotted more than once, put the actual trace name in row 3.
        return str(name).strip()

    vars_to_shift = []
    if include_g1:
        vars_to_shift.append("G1")
    if include_g2:
        vars_to_shift.append("G2")

    if measurement != "dynamic":
        vars_to_shift = ["J" if measurement == "creep" else "G"]

    wopt = _window_option(graph_name)
    shift_map = shifts.set_index("T_label").to_dict(orient="index")

    lines = []
    lines.append("// RheoSuperposition display shift for already plotted traces")
    lines.append(f"// input_scale = {input_scale}")
    lines.append("// Original waves are not modified.")
    lines.append("// x_shifted = x * a_x; y_shifted = y * b_y (direct multipliers).")
    lines.append("")

    trace_map2 = trace_map.copy()
    trace_map2["T_label"] = trace_map2["T_label"].astype(str)
    trace_map2["var"] = trace_map2["var"].astype(str).map(normalize_stacked_variable_label)

    for T_label, block in trace_map2.groupby("T_label", sort=False):
        if T_label not in shift_map:
            raise ValueError(f"T_label={T_label} was not found in shifts.")

        s = shift_map[T_label]
        aT = float(s["aT"])
        bT = float(s["bT"])
        log10_aT = float(s["log10_aT"])
        log10_bT = float(s["log10_bT"])

        if not include_reference and np.isclose(aT, 1.0) and np.isclose(bT, 1.0):
            continue

        success_aT = bool(s.get("success_aT", True))
        success_bT = bool(s.get("success_bT", True))
        finite_shift = np.all(np.isfinite([aT, bT, log10_aT, log10_bT]))

        lines.append(f"// Condition = {T_label}")

        if skip_failed and (not success_aT or not success_bT or not finite_shift):
            lines.append(
                f"// skipped: invalid shift factor "
                f"(success_aT={success_aT}, success_bT={success_bT})"
            )
            lines.append("")
            continue

        for _, row in block.iterrows():
            var = str(row["var"])
            if var not in vars_to_shift:
                continue

            trace = _trace_name(row["trace"])
            if trace == "":
                continue

            if input_scale == "linear":
                lines.append(f"ModifyGraph {wopt}muloffset({trace})={{{aT:.15g},{bT:.15g}}}")
            elif input_scale == "log10":
                lines.append(f"ModifyGraph {wopt}offset({trace})={{{log10_aT:.15g},{log10_bT:.15g}}}")
            else:
                ln_aT = log10_aT * np.log(10.0)
                ln_bT = log10_bT * np.log(10.0)
                lines.append(f"ModifyGraph {wopt}offset({trace})={{{ln_aT:.15g},{ln_bT:.15g}}}")

        lines.append("")

    return "\n".join(lines)

def save_igor_trace_shift_commands(
    trace_map: pd.DataFrame,
    shifts: pd.DataFrame,
    config: TTSConfig,
    filename: str = "igor_trace_shift_commands.ipf",
    graph_name: str = "",
    include_reference: bool = True,
) -> Path:
    """Save IGOR trace-shift commands into config.output_dir."""
    config.output_dir.mkdir(parents=True, exist_ok=True)
    command_text = build_igor_trace_shift_commands(
        trace_map=trace_map,
        shifts=shifts,
        input_scale=config.input_scale,
        graph_name=graph_name,
        include_reference=include_reference,
        measurement=config.measurement,
    )
    out_path = config.output_dir / filename
    out_path.write_text(command_text, encoding="utf-8")
    return out_path
