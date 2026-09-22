#!/usr/bin/env python3
"""Conservative context-aware number normalization for VoiceIME.

Global Chinese ITN is intentionally avoided: real-speech A/B showed it changes
natural prose such as dates, counts, percentages, and "三十条样本", worsening
Chinese CER. This module only converts number words when nearby language makes
an Arabic/code representation explicit.
"""
from __future__ import annotations

import re

DIGITS = {
    "零": "0", "〇": "0", "一": "1", "二": "2", "两": "2",
    "三": "3", "四": "4", "五": "5", "六": "6", "七": "7",
    "八": "8", "九": "9",
}
UNITS = {"十": 10, "百": 100, "千": 1000, "万": 10000}
NUM_CHARS = "零〇一二两三四五六七八九十百千万"
DIGIT_CHARS = "零〇一二两三四五六七八九"


def _digits(text: str) -> str | None:
    out = []
    for ch in text:
        if ch.isspace():
            continue
        value = DIGITS.get(ch)
        if value is None:
            return None
        out.append(value)
    return "".join(out) if out else None


def _integer(text: str) -> str | None:
    value = text.replace(" ", "")
    if not value:
        return None
    if all(ch in DIGITS for ch in value):
        return _digits(value)
    if any(ch not in DIGITS and ch not in UNITS for ch in value):
        return None

    total = 0
    section = 0
    number = 0
    for ch in value:
        if ch in DIGITS:
            number = int(DIGITS[ch])
            continue
        unit = UNITS[ch]
        if unit == 10000:
            section = (section + number) * unit
            total += section
            section = 0
            number = 0
        else:
            if number == 0:
                number = 1
            section += number * unit
            number = 0
    return str(total + section + number)


def _version(text: str) -> str | None:
    pieces = re.split(r"\s*点\s*", text.strip())
    if len(pieces) < 2:
        return None
    converted = [_integer(piece) for piece in pieces]
    if any(piece is None for piece in converted):
        return None
    return ".".join(converted)  # type: ignore[arg-type]


class ContextNumberNormalizer:
    # "user_id 等于一二三四五" -> 12345. Requiring >=2 spoken digits avoids
    # changing ordinary one-character Chinese values such as "设置为零".
    EQUAL_DIGITS = re.compile(
        rf"(等于\s*)([{DIGIT_CHARS}]{{2,}})"
    )
    # Explicit label: "数字四二" / "数字四十二" -> 数字42.
    LABELED_NUMBER = re.compile(
        rf"(数字\s*)([{NUM_CHARS}]+)"
    )
    # Code-ish delimiter context: "横杠二零二六下划线" -> 横杠2026下划线.
    BETWEEN_DELIMITERS = re.compile(
        rf"(横杠\s*)([{NUM_CHARS}]+)(\s*下划线)"
    )
    VERSION = re.compile(
        rf"(版本号(?:是)?\s*[vV]\s*)([{NUM_CHARS}]+(?:\s*点\s*[{NUM_CHARS}]+)+)"
    )
    PRICE_DECIMAL = re.compile(
        rf"(价格(?:是)?\s*)([{NUM_CHARS}]+)\s*点\s*"
        rf"([{DIGIT_CHARS}]+)(\s*(?:美元|元|块))"
    )

    @staticmethod
    def _replace_number(match: re.Match[str]) -> str:
        value = _integer(match.group(2))
        return match.group(0) if value is None else match.group(1) + value

    @staticmethod
    def _replace_between(match: re.Match[str]) -> str:
        value = _integer(match.group(2))
        if value is None:
            return match.group(0)
        return match.group(1) + value + match.group(3)

    @staticmethod
    def _replace_version(match: re.Match[str]) -> str:
        value = _version(match.group(2))
        return match.group(0) if value is None else match.group(1) + value

    @staticmethod
    def _replace_price(match: re.Match[str]) -> str:
        integer = _integer(match.group(2))
        fraction = _digits(match.group(3))
        if integer is None or fraction is None:
            return match.group(0)
        return match.group(1) + integer + "." + fraction + match.group(4)

    def correct(self, text: str) -> str:
        if not text:
            return text
        out = self.VERSION.sub(self._replace_version, text)
        out = self.PRICE_DECIMAL.sub(self._replace_price, out)
        out = self.BETWEEN_DELIMITERS.sub(self._replace_between, out)
        out = self.EQUAL_DIGITS.sub(self._replace_number, out)
        out = self.LABELED_NUMBER.sub(self._replace_number, out)
        return out


if __name__ == "__main__":
    import sys
    normalizer = ContextNumberNormalizer()
    for line in sys.stdin:
        print(normalizer.correct(line.rstrip("\n")))
