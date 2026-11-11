from types import SimpleNamespace
from unittest.mock import Mock

from rheo_superposition.gui.input_table import InputTable


def test_delete_temperature_removes_selected_triplet(monkeypatch):
    table = SimpleNamespace(
        rows=[["10", "", "", "25", "", "", "40", "", ""],
              ["w", "G1", "G2"] * 3, list(map(str, range(9)))],
        cell=(2, 4), commit=Mock(), render=Mock(), changed=Mock(),
    )
    monkeypatch.setattr("rheo_superposition.gui.input_table.messagebox.askyesno", lambda *a, **k: True)
    InputTable.delete_block(table)
    assert table.rows[0] == ["10", "", "", "40", "", ""]
    assert table.rows[2] == ["0", "1", "2", "6", "7", "8"]
    assert table.cell == (2, 3)
    table.changed.assert_called_once()


def test_delete_last_temperature_leaves_editable_blank_block(monkeypatch):
    table = SimpleNamespace(rows=[["25", "", ""]], cell=(0, 2),
                            commit=Mock(), render=Mock(), changed=Mock())
    monkeypatch.setattr("rheo_superposition.gui.input_table.messagebox.askyesno", lambda *a, **k: False)
    InputTable.delete_block(table)
    assert table.rows == [["25", "", ""]]
    table.changed.assert_not_called()
    monkeypatch.setattr("rheo_superposition.gui.input_table.messagebox.askyesno", lambda *a, **k: True)
    InputTable.delete_block(table)
    assert table.rows[0] == ["", "", ""]
    assert table.rows[1] == ["w", "G1", "G2"]
    assert table.cell == (0, 0)
