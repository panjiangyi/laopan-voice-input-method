#!/usr/bin/env python3
"""Build VoiceIME's merged domain glossary.

Built-in vocabularies are always included by default. If the user has
~/.config/voiceime/hotwords.txt (or XDG_CONFIG_HOME equivalent), it is merged
last so personal terms participate in the same ASR contextual-bias list.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIR = ROOT / "hotwords"
DEFAULT_FILES = (
    "programming.txt",
    "work-tools.txt",
    "dental.txt",
)


def personal_glossary_path() -> Path:
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return config_home / "voiceime" / "hotwords.txt"


def read_terms(path: Path) -> list[str]:
    terms: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        term = raw.strip()
        if not term or term.startswith("#"):
            continue
        terms.append(term)
    return terms


def merge_terms(paths: list[Path]) -> list[str]:
    """Deduplicate case-insensitively while preserving first canonical form."""
    seen: set[str] = set()
    merged: list[str] = []
    for path in paths:
        for term in read_terms(path):
            key = term.casefold()
            if key in seen:
                continue
            seen.add(key)
            merged.append(term)
    return merged


def default_paths(*, include_personal: bool = True) -> list[Path]:
    paths = [DEFAULT_DIR / name for name in DEFAULT_FILES]
    personal = personal_glossary_path()
    if include_personal and personal.is_file():
        paths.append(personal)
    return paths


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "files",
        nargs="*",
        type=Path,
        help="Glossary files. Defaults to built-ins plus the personal glossary.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Optional output file. Without this flag, print to stdout.",
    )
    parser.add_argument(
        "--no-personal",
        action="store_true",
        help="Do not append ~/.config/voiceime/hotwords.txt to default inputs.",
    )
    args = parser.parse_args()

    paths = args.files or default_paths(include_personal=not args.no_personal)
    missing = [path for path in paths if not path.is_file()]
    if missing:
        parser.error("missing glossary file(s): " + ", ".join(map(str, missing)))

    terms = merge_terms(paths)
    text = "\n".join(terms) + "\n"

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
        print(f"wrote {len(terms)} unique terms to {args.output}")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
