import numpy as np
import pandas as pd

from rheo_superposition.exporters import build_igor_trace_shift_commands


def test_igor_command_generation():
    trace_map = pd.DataFrame([
        {"T_label": "25", "var": "G1", "trace": "G1_25"},
        {"T_label": "25", "var": "G2", "trace": "G2_25"},
    ])
    shifts = pd.DataFrame([{
        "T_label": "25", "aT": 2.0, "bT": 3.0,
        "log10_aT": np.log10(2.0), "log10_bT": np.log10(3.0),
        "success_aT": True, "success_bT": True,
    }])
    text = build_igor_trace_shift_commands(trace_map, shifts, input_scale="linear")
    assert "muloffset(G1_25)={2,3}" in text
    assert "muloffset(G2_25)={2,3}" in text
