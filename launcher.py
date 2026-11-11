from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# PyInstaller's Matplotlib run-time hook uses a disposable cache directory.
# Persist it instead, otherwise macOS scans every installed font on each launch.
if getattr(sys, "frozen", False):
    matplotlib_cache = Path.home() / "Library" / "Caches" / "RheoSuperposition" / "matplotlib"
    try:
        matplotlib_cache.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    else:
        os.environ["MPLCONFIGDIR"] = str(matplotlib_cache)

from rheo_superposition.gui.app import run_app


if __name__ == "__main__":
    run_app()
