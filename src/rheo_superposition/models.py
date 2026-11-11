from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import math
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class TTSConfig:
    data_path: Path = Path("input_rheology.csv")
    output_dir: Path = Path("tts_output")

    input_delimiter: str = "auto"
    input_scale: str = "linear"
    input_format: str = "stacked_header"

    measurement: str = "dynamic"
    condition_name: str = "Temperature"
    condition_unit: str = "°C"

    shift_mode: str = "both"
    fixed_log10_aT: float = 0.0
    fixed_log10_bT: float = 0.0

    stacked_header_temperature_row: int = 0
    stacked_header_variable_row: int = 1
    stacked_header_trace_row: int = 2
    stacked_header_data_start_row: int = 3
    stacked_header_block_size: int = 3
    stacked_header_expected_vars: tuple[str, ...] = ("w", "G1", "G2")

    omega_col_prefixes: tuple[str, ...] = ("omega", "w")
    omega_col_suffixes: tuple[str, ...] = ("",)
    gp_col_prefixes: tuple[str, ...] = ("G1", "Gp")
    gp_col_suffixes: tuple[str, ...] = ("",)
    gpp_col_prefixes: tuple[str, ...] = ("G2", "Gpp")
    gpp_col_suffixes: tuple[str, ...] = ("",)

    column_case_sensitive: bool = False
    temp_label_strip_suffixes: tuple[str, ...] = ("°C", "℃", "degC", "C")

    T_ref: str = "25"
    log10_aT_bounds: tuple[float, float] = (-6.0, 6.0)
    log10_bT_bounds: tuple[float, float] = (-6.0, 6.0)
    min_overlap_points: int = 5

    # Custom composite loss:
    # rho(x) = b x^4 / ((0.481 c)^2 + |x|^3)
    #          + x^2 / ((0.333 c)^2 + x^2)
    loss_b: float = 0.1
    loss_c: float = 0.5

    save_shifted_data: bool = True


    def __post_init__(self):
        for bounds in (self.log10_aT_bounds, self.log10_bT_bounds):
            if len(bounds) != 2 or not all(math.isfinite(v) for v in bounds) or bounds[0] >= bounds[1]:
                raise ValueError("Shift bounds must be finite and increasing.")
        if not all(math.isfinite(v) for v in (self.fixed_log10_aT, self.fixed_log10_bT, self.loss_b, self.loss_c)):
            raise ValueError("Fixed shifts and loss parameters must be finite.")
        if self.loss_b <= 0 or self.loss_c <= 0:
            raise ValueError("Loss parameters must be positive.")
        if self.measurement not in {"dynamic", "relaxation", "creep"}:
            raise ValueError("Unknown measurement type.")
        if not self.condition_name.strip():
            raise ValueError("Condition name is required.")
        if self.input_scale not in {"linear", "log10", "ln"}:
            raise ValueError("Unknown input scale.")
        if self.min_overlap_points < 4:
            raise ValueError("Minimum overlap must be at least 4.")
        if self.measurement != "dynamic":
            object.__setattr__(self, "stacked_header_block_size", 2)
            object.__setattr__(self, "stacked_header_expected_vars", ("t", self.response_name))
        if self.condition_name.lower() != "temperature":
            object.__setattr__(self, "temp_label_strip_suffixes", ())

    @property
    def response_name(self):
        return "J" if self.measurement == "creep" else "G"

    @property
    def condition_axis_label(self):
        return self.condition_name + (f" ({self.condition_unit})" if self.condition_unit else "")


@dataclass
class AppState:
    config: TTSConfig | None = None
    data: dict[str, dict[str, Any]] | None = None
    trace_map: pd.DataFrame | None = None
    horizontal_shifts: pd.DataFrame | None = None
    vertical_shifts: pd.DataFrame | None = None
    vertical_stale: bool = False
    horizontal_visible: dict[str, bool] = field(default_factory=dict)
    vertical_visible: dict[str, bool] = field(default_factory=dict)
