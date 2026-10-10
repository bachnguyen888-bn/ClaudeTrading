"""
Tiny .env reader, so the project needs no extra packages.

Reads KEY=VALUE lines from .env into os.environ. Values that are already set
in your shell win over values in the file.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict


def load_env_file(path: str | Path = ".env") -> Dict[str, str]:
    """Load .env (if it exists) and return the key/value pairs found in it."""
    path = Path(path)
    values: Dict[str, str] = {}
    if not path.exists():
        return values

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        values[key] = value
        os.environ.setdefault(key, value)
    return values
