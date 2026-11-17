"""Compatibility entry for the production portable Amaro generator."""
import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).resolve().parents[3] / "scripts/build/harmonyos_ptc.py"), run_name="__main__")
