#!/usr/bin/env python3
"""Build a compact prompt-hotword list for modern ASR final models."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRIORITY = ROOT / "hotwords" / "priority.txt"


def personal_path() -> Path:
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return config_home / "voiceime" / "hotwords.txt"


def read(path: Path) -> list[str]:
    if not path.is_file():
        return []
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def terms() -> list[str]:
    seen = set()
    out = []
    for term in read(PRIORITY) + read(personal_path()):
        key = term.casefold()
        if key not in seen:
            seen.add(key)
            out.append(term)
    return out


def comma_separated() -> str:
    # Qwen3-ASR/FunASR Nano expect ASCII-comma-separated hotwords.
    return ",".join(term.replace(",", " ") for term in terms())


if __name__ == "__main__":
    print(comma_separated())
