"""单一版本来源：backend/pyproject.toml。"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def app_version() -> str:
    path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return "0.1.0"
    match = re.search(r'(?m)^version\s*=\s*"([^"]+)"', text)
    return match.group(1) if match else "0.1.0"
