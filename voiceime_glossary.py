#!/usr/bin/env python3
"""Deterministic domain-glossary correction for mixed Chinese/English ASR.

Unlike an LLM rewrite, this corrector is deliberately narrow:
- it NEVER edits CJK text;
- it only rewrites ASCII-rich spans to a canonical term that exists in the
  user's trusted glossary;
- short ambiguous words require near-exact matches;
- longer/multi-word proper nouns can tolerate ASR phonetic misspellings.

This makes corrections such as:
  poll request -> pull request
  get help actions -> GitHub Actions
  update sesion -> updateSession
  system d -> systemd
  Dabby Dental -> Darby Dental
  Henry Shine -> Henry Schein
without free-form rewriting.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PRIORITY = ROOT / "hotwords" / "priority.txt"
ALIASES = ROOT / "hotwords" / "aliases.tsv"
BUILTIN_GLOSSARIES = (
    ROOT / "hotwords" / "programming.txt",
    ROOT / "hotwords" / "work-tools.txt",
    ROOT / "hotwords" / "dental.txt",
)
COMPILED = Path(os.environ.get(
    "VOICEIME_HOTWORDS_FILE",
    ROOT / "hotwords" / "compiled.txt",
))
ASCII_RUN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9\s._+:/-]{1,80}")


def personal_glossary_path() -> Path:
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return config_home / "voiceime" / "hotwords.txt"


def _read_terms(path: Path) -> list[str]:
    if not path.is_file():
        return []
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def load_aliases() -> dict[str, str]:
    aliases: dict[str, str] = {}
    if not ALIASES.is_file():
        return aliases
    for raw in ALIASES.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw or raw.startswith("#") or "\t" not in raw:
            continue
        alias, canonical = raw.split("\t", 1)
        key = _ascii_signature(alias)
        if key and canonical.strip():
            aliases[key] = canonical.strip()
    return aliases


def _dedupe(terms: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for term in terms:
        key = term.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(term)
    return out


def load_terms() -> list[str]:
    """Terms allowed to participate in fuzzy correction.

    Keep fuzzy matching intentionally compact. Personal terms and the curated
    priority list contain proper nouns / code identifiers where ASR spelling
    repair is useful and low-risk.
    """
    return _dedupe(
        _read_terms(personal_glossary_path()) + _read_terms(PRIORITY)
    )


def load_exact_terms() -> list[str]:
    """All canonical vocabulary usable for exact case/spacing normalization.

    The large programming/work/dental lists contain many ordinary words. They
    are valuable when ASR already got the letters right ("react" -> "React"),
    but must not all participate in fuzzy matching or normal English would be
    over-corrected.
    """
    if COMPILED.is_file():
        return _dedupe(_read_terms(COMPILED))
    terms: list[str] = []
    terms.extend(_read_terms(personal_glossary_path()))
    for path in BUILTIN_GLOSSARIES:
        terms.extend(_read_terms(path))
    terms.extend(_read_terms(PRIORITY))
    return _dedupe(terms)


def _ascii_signature(text: str) -> str:
    return re.sub(r"[^a-z0-9+]", "", text.casefold())


def _edit_distance(a: str, b: str) -> int:
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(
                cur[-1] + 1,
                prev[j] + 1,
                prev[j - 1] + (ca != cb),
            ))
        prev = cur
    return prev[-1]


def _similarity(a: str, b: str) -> float:
    aa, bb = _ascii_signature(a), _ascii_signature(b)
    if not aa or not bb:
        return 0.0
    return 1.0 - _edit_distance(aa, bb) / max(len(aa), len(bb))


@dataclass(frozen=True)
class _Term:
    text: str
    signature: str
    words: tuple[str, ...]


class GlossaryCorrector:
    def __init__(
        self,
        terms: list[str] | None = None,
        aliases: dict[str, str] | None = None,
        exact_terms: list[str] | None = None,
    ) -> None:
        raw_terms = terms if terms is not None else load_terms()
        raw_exact = exact_terms if exact_terms is not None else load_exact_terms()
        self.aliases = aliases if aliases is not None else load_aliases()
        self.exact: dict[str, str] = {}
        for text in raw_exact:
            signature = _ascii_signature(text)
            if signature and signature not in self.exact:
                self.exact[signature] = text
        self.terms: list[_Term] = []
        seen: set[str] = set()
        for text in raw_terms:
            signature = _ascii_signature(text)
            if len(signature) < 2 or signature in seen:
                continue
            seen.add(signature)
            self.terms.append(_Term(
                text=text,
                signature=signature,
                words=tuple(text.casefold().split()),
            ))

    @staticmethod
    def _threshold(length: int) -> float:
        # Tiny acronyms are highly collision-prone (PR/IP/AI/etc.) and must
        # already be exact. Longer brand/technical names can safely tolerate
        # one or two ASR substitutions when there is a clear glossary winner.
        if length <= 4:
            return 0.99
        if length <= 7:
            return 0.83
        if length <= 11:
            return 0.78
        return 0.72

    def _best(self, candidate: str) -> str | None:
        sig = _ascii_signature(candidate)
        if len(sig) < 3:
            return None
        alias = self.aliases.get(sig)
        if alias is not None:
            return alias
        exact = self.exact.get(sig)
        if exact is not None:
            return exact

        ranked: list[tuple[float, float, _Term]] = []
        candidate_words = tuple(candidate.casefold().split())
        for term in self.terms:
            length_ratio = min(len(sig), len(term.signature)) / max(
                len(sig), len(term.signature)
            )
            if length_ratio < 0.64:
                continue
            raw = _similarity(candidate, term.text)
            if raw < 0.66:
                continue
            # If one word in a multi-word phrase is already exact, allow a
            # little more tolerance for the neighboring phonetic error:
            # "Dabby Dental" -> "Darby Dental".
            overlap = (
                len(term.words) > 1
                and any(word in term.words for word in candidate_words)
            )
            ranked.append((raw + (0.025 if overlap else 0.0), raw, term))

        if not ranked:
            return None
        ranked.sort(key=lambda item: item[0], reverse=True)
        score, raw, term = ranked[0]
        second = ranked[1][0] if len(ranked) > 1 else 0.0
        threshold = self._threshold(len(sig))
        if len(term.words) > 1 and any(
            word in term.words for word in candidate_words
        ):
            threshold -= 0.04

        if raw < threshold:
            return None
        if score - second < 0.04 and raw < 0.95:
            return None
        return term.text

    def _correct_run(self, run: str) -> str:
        trailing = run[len(run.rstrip()):]
        body = run.rstrip()
        if not body:
            return run
        tokens = body.split()
        if not tokens:
            return run

        out: list[str] = []
        i = 0
        while i < len(tokens):
            replacement: str | None = None
            replacement_width = 0
            for width in range(min(5, len(tokens) - i), 0, -1):
                candidate = " ".join(tokens[i:i + width])
                replacement = self._best(candidate)
                if replacement is not None:
                    replacement_width = width
                    break
            if replacement is None:
                out.append(tokens[i])
                i += 1
            else:
                out.append(replacement)
                i += replacement_width
        return " ".join(out) + trailing

    def correct(self, text: str) -> str:
        if not text or not self.terms:
            return text
        out: list[str] = []
        last = 0
        for match in ASCII_RUN_RE.finditer(text):
            out.append(text[last:match.start()])
            out.append(self._correct_run(match.group(0)))
            last = match.end()
        out.append(text[last:])
        return "".join(out)


if __name__ == "__main__":
    import sys
    corrector = GlossaryCorrector()
    for line in sys.stdin:
        print(corrector.correct(line.rstrip("\n")))
