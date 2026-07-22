"""Packaged asset paths that work in source and PyInstaller builds."""

from __future__ import annotations

from pathlib import Path
import sys


def asset_path(name: str) -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS")) / "flashforge" / "assets" / name
    return Path(__file__).parent / "assets" / name


def app_icon_path() -> Path:
    return asset_path("flashforge.ico")
