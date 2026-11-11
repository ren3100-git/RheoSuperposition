from __future__ import annotations

import json
import sys
from pathlib import Path

SETTINGS_PATH = (
    Path.home()
    / "Library"
    / "Application Support"
    / "RheoSuperposition"
    / "settings.json"
)


LEGACY_SETTINGS_PATH = SETTINGS_PATH.parent.parent / "TimeTempSuperposition" / "settings.json"

def load_path_settings() -> dict[str, str]:
    try:
        path = SETTINGS_PATH if SETTINGS_PATH.exists() else LEGACY_SETTINGS_PATH
        if not path.exists():
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        print(f"Warning: failed to read settings: {exc}", file=sys.stderr)
        return {}
    return {
        key: value
        for key, value in payload.items()
        if key in {"input_file", "output_dir"} and isinstance(value, str)
    }


def save_path_settings(input_file: str, output_dir: str) -> None:
    payload = {"input_file": input_file.strip(), "output_dir": output_dir.strip()}
    temporary = SETTINGS_PATH.with_suffix(".tmp")
    try:
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(SETTINGS_PATH)
    except OSError as exc:
        print(f"Warning: failed to save settings: {exc}", file=sys.stderr)
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _nearest_existing_directory(path: Path) -> Path:
    candidate = path.expanduser()
    if not candidate.is_dir():
        candidate = candidate.parent
    while candidate != candidate.parent and not candidate.is_dir():
        candidate = candidate.parent
    return candidate if candidate.is_dir() else Path.home()


def input_dialog_initial_directory(current_value: str) -> Path:
    current = Path(current_value.strip() or Path.home())
    return _nearest_existing_directory(current)


def output_dialog_initial_directory(current_value: str) -> Path:
    current = Path(current_value.strip() or Path.home())
    return _nearest_existing_directory(current)
