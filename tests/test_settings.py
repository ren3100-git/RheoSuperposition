from pathlib import Path

from rheo_superposition.settings import input_dialog_initial_directory, output_dialog_initial_directory


def test_dialog_directories_fall_back_to_existing_parent(tmp_path: Path):
    missing_file = tmp_path / "missing" / "input.csv"
    assert input_dialog_initial_directory(str(missing_file)) == tmp_path
    assert output_dialog_initial_directory(str(tmp_path)) == tmp_path
