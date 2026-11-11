from pathlib import Path

import numpy as np

from rheo_superposition.models import TTSConfig
from rheo_superposition.readers import convert_to_linear, normalize_temp_label, parse_rheology_input


def test_convert_to_linear():
    assert np.allclose(convert_to_linear([0, 1], "log10"), [1, 10])
    assert np.allclose(convert_to_linear([0, 1], "ln"), [1, np.e])


def test_normalize_temperature():
    assert normalize_temp_label("25°C") == "25"
    assert normalize_temp_label(" 25.5 C ") == "25.5"


def test_column_name_input(tmp_path: Path):
    path = tmp_path / "input.csv"
    path.write_text(
        "omega_25,G1_25,G2_25\n"
        "1,10,5\n2,20,10\n3,30,15\n4,40,20\n",
        encoding="utf-8",
    )
    config = TTSConfig(data_path=path, input_format="column_names", input_scale="linear")
    data, trace_map = parse_rheology_input(config)
    assert "25" in data
    assert len(data["25"]["omega"]) == 4
    assert set(trace_map["var"]) == {"w", "G1", "G2"}


def test_editor_and_csv_use_same_parser(tmp_path):
    import pandas as pd

    from rheo_superposition.readers import parse_stacked_header_table

    raw = pd.DataFrame([
        [25, None, None], ["w", "G1", "G2"], ["w25", "gp25", "gpp25"],
        [1, 10, 5], [2, 20, 10], [3, 30, 15], [4, 40, 20],
    ])
    path = tmp_path / "stacked.csv"
    raw.to_csv(path, header=False, index=False)
    config = TTSConfig(data_path=path, input_format="stacked_header", input_scale="linear")
    edited, traces = parse_stacked_header_table(raw, config, strict=True)
    loaded, csv_traces = parse_rheology_input(config)
    np.testing.assert_allclose(edited["25"]["Gp"], loaded["25"]["Gp"])
    pd.testing.assert_frame_equal(traces, csv_traces)
    raw.iat[3, 1] = 99
    edited, _ = parse_stacked_header_table(raw, config, strict=True)
    assert edited["25"]["Gp"][0] == 99


def test_editor_rejects_invalid_cells():
    import pandas as pd
    import pytest

    from rheo_superposition.readers import parse_stacked_header_table

    raw = pd.DataFrame([
        [25, None, None], ["w", "G1", "G2"], ["w25", "gp25", "gpp25"],
        [1, "bad", 5], [2, 20, 10], [3, 30, 15], [4, 40, 20], [5, 50, 25],
    ])
    with pytest.raises(ValueError, match="Row 4, T=25"):
        parse_stacked_header_table(raw, TTSConfig(input_scale="linear"), strict=True)
