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
CONTEXTUAL_ALIASES = ROOT / "hotwords" / "contextual-aliases.tsv"
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



def load_contextual_aliases() -> list[tuple[str, str, tuple[str, ...]]]:
    """Load exact mixed-script ASR artifacts guarded by nearby context.

    Some English product names are emitted as ordinary Chinese words
    (for example "Linear" -> "力量"). Replacing those globally would corrupt
    valid Chinese, so every entry must declare nearby technical context that
    makes the replacement safe enough to apply.
    """
    out: list[tuple[str, str, tuple[str, ...]]] = []
    if not CONTEXTUAL_ALIASES.is_file():
        return out
    for raw in CONTEXTUAL_ALIASES.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw or raw.startswith("#"):
            continue
        parts = [part.strip() for part in raw.split("\t")]
        if len(parts) < 3:
            continue
        alias, canonical, raw_context = parts[0], parts[1], parts[2]
        triggers = tuple(
            item.strip()
            for item in re.split(r"[|,]", raw_context)
            if item.strip()
        )
        if alias and canonical and triggers:
            out.append((alias, canonical, triggers))
    return out


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
        contextual_aliases: list[tuple[str, str, tuple[str, ...]]] | None = None,
    ) -> None:
        raw_terms = terms if terms is not None else load_terms()
        raw_exact = exact_terms if exact_terms is not None else load_exact_terms()
        self.aliases = aliases if aliases is not None else load_aliases()
        self.contextual_aliases = (
            contextual_aliases
            if contextual_aliases is not None
            else load_contextual_aliases()
        )
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


    @staticmethod
    def _has_context(window: str, trigger: str) -> bool:
        if not trigger:
            return False
        # ASCII technical tokens need boundaries so "PR" does not match the
        # start of an unrelated English word. CJK/mixed triggers use exact
        # substring matching.
        if trigger.isascii():
            pattern = (
                r"(?<![A-Za-z0-9_])"
                + re.escape(trigger)
                + r"(?![A-Za-z0-9_])"
            )
            return re.search(pattern, window, re.IGNORECASE) is not None
        return trigger.casefold() in window.casefold()

    @staticmethod
    def _with_ascii_boundaries(
        text: str, start: int, end: int, replacement: str
    ) -> str:
        """Prevent two repaired ASCII terms from being glued together."""
        if not replacement:
            return replacement
        prev_ch = text[start - 1] if start > 0 else ""
        next_ch = text[end] if end < len(text) else ""
        if (
            prev_ch
            and prev_ch.isascii()
            and prev_ch.isalnum()
            and replacement[0].isascii()
            and replacement[0].isalnum()
        ):
            replacement = " " + replacement
        if (
            next_ch
            and next_ch.isascii()
            and next_ch.isalnum()
            and replacement[-1].isascii()
            and replacement[-1].isalnum()
        ):
            replacement += " "
        return replacement

    def _correct_contextual_aliases(self, text: str) -> str:
        # Entries are intentionally ordered. A narrow mixed token such as
        # "ticke值" can first become "ticket", which then provides the
        # technical context needed to safely repair "力量" -> "Linear".
        for alias, canonical, triggers in self.contextual_aliases:
            pattern = re.compile(re.escape(alias), re.IGNORECASE)
            cursor = 0
            while cursor < len(text):
                match = pattern.search(text, cursor)
                if match is None:
                    break
                left = max(0, match.start() - 24)
                right = min(len(text), match.end() + 24)
                window = text[left:right]
                if not any(self._has_context(window, t) for t in triggers):
                    cursor = match.end()
                    continue
                replacement = self._with_ascii_boundaries(
                    text, match.start(), match.end(), canonical
                )
                text = text[:match.start()] + replacement + text[match.end():]
                cursor = match.start() + len(replacement)
        return text

    def correct(self, text: str) -> str:
        if not text:
            return text
        out: list[str] = []
        last = 0
        for match in ASCII_RUN_RE.finditer(text):
            out.append(text[last:match.start()])
            out.append(self._correct_run(match.group(0)))
            last = match.end()
        out.append(text[last:])
        return self._correct_contextual_aliases("".join(out))


if __name__ == "__main__":
    import sys
    corrector = GlossaryCorrector()
    for line in sys.stdin:
        print(corrector.correct(line.rstrip("\n")))
