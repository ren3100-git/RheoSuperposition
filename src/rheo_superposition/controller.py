from __future__ import annotations

from pathlib import Path
from dataclasses import replace

import pandas as pd

from .exporters import save_igor_trace_shift_commands, save_tts_outputs
from .models import AppState, TTSConfig
from .readers import parse_rheology_input
from .shifts import estimate_horizontal_shift_factors, estimate_vertical_shift_factors


class TTSController:
    """Application workflow independent of Tkinter widgets."""

    def __init__(self) -> None:
        self.state = AppState()

    def load_data(self, config: TTSConfig):
        data, trace_map = parse_rheology_input(config)
        return self.set_data(data, trace_map, config)

    def set_data(self, data, trace_map, config: TTSConfig):
        self.state.config = config
        self.state.data = data
        self.state.trace_map = trace_map
        self.state.horizontal_shifts = None
        self.state.vertical_shifts = None
        self.state.vertical_stale = False
        self.state.horizontal_visible = {str(t): True for t in data}
        self.state.vertical_visible = {str(t): True for t in data}
        return data, trace_map

    def run_horizontal(self, config: TTSConfig) -> pd.DataFrame:
        if self.state.data is None:
            raise RuntimeError("Load data before estimating horizontal shifts.")
        result = estimate_horizontal_shift_factors(self.state.data, config)
        self.state.config = config
        self.state.horizontal_shifts = result
        self.state.vertical_shifts = None
        self.state.vertical_stale = False
        return result

    def run_vertical(self, horizontal_shifts: pd.DataFrame | None, config: TTSConfig) -> pd.DataFrame:
        if self.state.data is None:
            raise RuntimeError("Load data before estimating vertical shifts.")
        if horizontal_shifts is None:
            # An independent vertical fit starts in the original horizontal frame.
            config = replace(config, shift_mode="vertical_only", fixed_log10_aT=0.0)
            seed_config = replace(config, shift_mode="none", fixed_log10_bT=0.0)
            horizontal_shifts = estimate_horizontal_shift_factors(self.state.data, seed_config)
            horizontal_shifts["shift_mode"] = "vertical_only"
            horizontal_shifts["calculation_stage"] = "horizontal_fixed"
            horizontal_shifts["bT_is_fixed"] = horizontal_shifts["is_reference"].astype(bool)
            if "diagnostic" in horizontal_shifts:
                horizontal_shifts["diagnostic"] = ""
        result = estimate_vertical_shift_factors(self.state.data, horizontal_shifts, config)
        self.state.config = config
        self.state.horizontal_shifts = horizontal_shifts
        self.state.vertical_shifts = result
        self.state.vertical_stale = False
        return result

    def export(self, shifts: pd.DataFrame, config: TTSConfig) -> tuple[pd.DataFrame | None, Path]:
        if self.state.data is None or self.state.trace_map is None:
            raise RuntimeError("Load data before exporting.")
        shifted = save_tts_outputs(self.state.data, shifts, config)
        command_path = save_igor_trace_shift_commands(
            trace_map=self.state.trace_map,
            shifts=shifts,
            config=config,
            filename="igor_trace_shift_commands.txt",
            graph_name="",
            include_reference=True,
        )
        return shifted, command_path
