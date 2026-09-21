#!/usr/bin/env python3
"""Evaluate VoiceIME on a recorded sample manifest.

Runs the production recognition stack:
  streaming Sherpa Paraformer -> optional FireRedASR2 final pass

Outputs:
  results.tsv       per-sample hypotheses and metrics
  summary.json      aggregate metrics for streaming/final
  report.md         human-readable regression report

The manifest format is the one produced by scripts/14-record-samples.sh:
  id, wav, target_text, actual_text
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import runpy
import time
import wave
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = runpy.run_path(str(ROOT / "voiceime-engine"))
SherpaRecognizer = ENGINE["SherpaRecognizer"]
FinalRecognizer = ENGINE["FinalRecognizer"]

COSMETIC_PUNCT = set("，。！？；：、“”‘’（）《》〈〉,.!?;:()[]{}")
PUNCT = COSMETIC_PUNCT | set("…—")
TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:[._+:/-][A-Za-z0-9+._:/-]+)*")
NUMBER_RE = re.compile(r"(?<![A-Za-z0-9_])[+-]?\d+(?:\.\d+)*(?![A-Za-z0-9_])")
CODE_RE = re.compile(
    r"(?:\b[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+\b)"
    r"|(?:\b[A-Z][A-Z0-9_]{2,}\b)"
    r"|(?:\b[A-Za-z][A-Za-z0-9]*(?:[.+:/-][A-Za-z0-9+._:/-]+)+\b)"
    r"|(?:\bC\+\+\b)"
)


def is_cjk(ch: str) -> bool:
    cp = ord(ch)
    return (
        0x3400 <= cp <= 0x4DBF
        or 0x4E00 <= cp <= 0x9FFF
        or 0xF900 <= cp <= 0xFAFF
    )


def edit_distance(a: str, b: str) -> int:
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i]
        for j, cb in enumerate(b, 1):
            curr.append(min(
                curr[-1] + 1,
                prev[j] + 1,
                prev[j - 1] + (ca != cb),
            ))
        prev = curr
    return prev[-1]


def _prev_nonspace(chars: list[str], i: int) -> str:
    j = i - 1
    while j >= 0 and chars[j].isspace():
        j -= 1
    return chars[j] if j >= 0 else ""


def _next_nonspace(chars: list[str], i: int) -> str:
    j = i + 1
    while j < len(chars) and chars[j].isspace():
        j += 1
    return chars[j] if j < len(chars) else ""


def _is_ascii_word_char(ch: str) -> bool:
    return bool(ch) and ch.isascii() and ch.isalnum()


def normalize_content(text: str) -> str:
    """Normalize presentation only; preserve numeric/code semantics.

    Examples that must stay different:
      1.5 != 15
      -10 != 10
      C++ != C
      user_id != userid

    Natural sentence punctuation and CJK<->ASCII boundary spaces are cosmetic.
    """
    chars = list(text.lower())
    out: list[str] = []
    always_cosmetic = set("，。！？；：“”‘’（）《》〈〉")
    conditional_ascii = set(",.!?;:()[]{}")

    for i, ch in enumerate(chars):
        prev_ch = _prev_nonspace(chars, i)
        next_ch = _next_nonspace(chars, i)

        if ch.isspace():
            if (
                (is_cjk(prev_ch) and _is_ascii_word_char(next_ch))
                or (_is_ascii_word_char(prev_ch) and is_cjk(next_ch))
            ):
                continue
            out.append(" ")
            continue

        if ch in always_cosmetic:
            continue

        if ch in conditional_ascii:
            # ASCII punctuation embedded inside a number/code token is
            # semantic. A sentence delimiter is presentation.
            if _is_ascii_word_char(prev_ch) and _is_ascii_word_char(next_ch):
                out.append(ch)
            continue

        # Preserve + - _ / and any other program/number punctuation.
        out.append(ch)

    return "".join(out)


def content_error(reference: str, hypothesis: str) -> tuple[int, int]:
    ref = normalize_content(reference)
    hyp = normalize_content(hypothesis)
    return edit_distance(ref, hyp), len(ref)


def cjk_error(reference: str, hypothesis: str) -> tuple[int, int]:
    ref = "".join(ch for ch in reference if is_cjk(ch))
    hyp = "".join(ch for ch in hypothesis if is_cjk(ch))
    return edit_distance(ref, hyp), len(ref)


def punctuation_error(reference: str, hypothesis: str) -> tuple[int, int]:
    ref = "".join(ch for ch in reference if ch in PUNCT)
    hyp = "".join(ch for ch in hypothesis if ch in PUNCT)
    return edit_distance(ref, hyp), len(ref)


def extract_tokens(regex: re.Pattern[str], text: str) -> list[str]:
    return [m.group(0) for m in regex.finditer(text)]


def token_hits(tokens: list[str], hypothesis: str) -> tuple[int, int]:
    """Multiset exact-token recall, case-insensitive."""
    expected = Counter(t.lower() for t in tokens)
    got = Counter(t.lower() for t in TOKEN_RE.findall(hypothesis))
    # Numbers/code symbols may not be matched by TOKEN_RE, so also compare
    # literal substrings for anything missing from got.
    lowered = hypothesis.lower()
    hits = 0
    for token, count in expected.items():
        direct = got.get(token, 0)
        if direct:
            hits += min(count, direct)
        else:
            hits += min(count, lowered.count(token))
    return hits, sum(expected.values())


def read_pcm(path: Path) -> tuple[bytes, float]:
    with wave.open(str(path), "rb") as wf:
        if wf.getnchannels() != 1 or wf.getsampwidth() != 2 or wf.getframerate() != 16000:
            raise ValueError(
                f"{path}: expected mono 16-bit PCM 16000 Hz, got "
                f"{wf.getnchannels()}ch/{wf.getsampwidth()*8}bit/{wf.getframerate()}Hz"
            )
        frames = wf.getnframes()
        return wf.readframes(frames), frames / 16000.0


def recognize(asr, final_asr, pcm: bytes) -> tuple[str, str, float, float]:
    stream = asr.create_stream()
    chunk_bytes = 3200  # 100ms int16 mono
    t0 = time.monotonic()
    for start in range(0, len(pcm), chunk_bytes):
        asr.accept_pcm(stream, pcm[start:start + chunk_bytes])
        asr.decode_ready(stream)
    streaming = asr.finalize(stream).strip()
    streaming_ms = (time.monotonic() - t0) * 1000

    t1 = time.monotonic()
    final = streaming
    try:
        refined = final_asr.transcribe(pcm)
        if refined:
            final = refined
    except Exception as ex:
        print(f"WARN FireRed failed: {ex!r}")
    final_ms = (time.monotonic() - t1) * 1000
    return streaming, final, streaming_ms, final_ms


def rate(errors: int, total: int) -> float | None:
    return errors / total if total else None


def pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2%}"


def recall(hits: int, total: int) -> float | None:
    return hits / total if total else None


def load_manifest(path: Path):
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            wav = path.parent / Path(row["wav"]).name
            reference = (row.get("actual_text") or row.get("target_text") or "").strip()
            yield row["id"], wav, reference


def metrics(reference: str, hypothesis: str) -> dict:
    ce, cn = content_error(reference, hypothesis)
    ze, zn = cjk_error(reference, hypothesis)
    pe, pn = punctuation_error(reference, hypothesis)

    english = extract_tokens(TOKEN_RE, reference)
    numbers = extract_tokens(NUMBER_RE, reference)
    code = extract_tokens(CODE_RE, reference)

    eh, en = token_hits(english, hypothesis)
    nh, nn = token_hits(numbers, hypothesis)
    kh, kn = token_hits(code, hypothesis)

    return {
        "content_edits": ce,
        "content_chars": cn,
        "content_cer": rate(ce, cn),
        "cjk_edits": ze,
        "cjk_chars": zn,
        "cjk_cer": rate(ze, zn),
        "punct_edits": pe,
        "punct_count": pn,
        "punct_error_rate": rate(pe, pn),
        "english_hits": eh,
        "english_total": en,
        "english_recall": recall(eh, en),
        "number_hits": nh,
        "number_total": nn,
        "number_recall": recall(nh, nn),
        "code_hits": kh,
        "code_total": kn,
        "code_recall": recall(kh, kn),
    }


def aggregate(rows: list[dict], prefix: str) -> dict:
    sums = Counter()
    for row in rows:
        m = row[prefix]
        for key in (
            "content_edits", "content_chars", "cjk_edits", "cjk_chars",
            "punct_edits", "punct_count", "english_hits", "english_total",
            "number_hits", "number_total", "code_hits", "code_total",
        ):
            sums[key] += m[key]

    return {
        "samples": len(rows),
        "content_cer": rate(sums["content_edits"], sums["content_chars"]),
        "cjk_cer": rate(sums["cjk_edits"], sums["cjk_chars"]),
        "punct_error_rate": rate(sums["punct_edits"], sums["punct_count"]),
        "english_recall": recall(sums["english_hits"], sums["english_total"]),
        "number_recall": recall(sums["number_hits"], sums["number_total"]),
        "code_recall": recall(sums["code_hits"], sums["code_total"]),
        **dict(sums),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "benchmark-results")
    args = parser.parse_args()

    asr = SherpaRecognizer()
    final_asr = FinalRecognizer()
    rows: list[dict] = []

    for sample_id, wav, reference in load_manifest(args.manifest):
        if not wav.exists():
            raise FileNotFoundError(wav)
        pcm, duration = read_pcm(wav)
        streaming, final, stream_ms, final_ms = recognize(asr, final_asr, pcm)
        sm = metrics(reference, streaming)
        fm = metrics(reference, final)
        delta = fm["content_cer"] - sm["content_cer"]
        verdict = "same"
        if delta < -1e-12:
            verdict = "improved"
        elif delta > 1e-12:
            verdict = "worse"

        row = {
            "id": sample_id,
            "wav": str(wav),
            "reference": reference,
            "streaming_text": streaming,
            "final_text": final,
            "duration_sec": duration,
            "streaming_ms": stream_ms,
            "final_pass_ms": final_ms,
            "fire_red_effect": verdict,
            "streaming": sm,
            "final": fm,
        }
        rows.append(row)
        print(
            f"{sample_id}: stream CER={pct(sm['content_cer'])} "
            f"final CER={pct(fm['content_cer'])} FireRed={verdict}"
        )
        print(f"  REF: {reference}")
        print(f"  STR: {streaming}")
        print(f"  FIN: {final}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    streaming_summary = aggregate(rows, "streaming")
    final_summary = aggregate(rows, "final")
    summary = {
        "manifest": str(args.manifest),
        "streaming": streaming_summary,
        "final": final_summary,
        "fire_red": {
            "improved": sum(r["fire_red_effect"] == "improved" for r in rows),
            "same": sum(r["fire_red_effect"] == "same" for r in rows),
            "worse": sum(r["fire_red_effect"] == "worse" for r in rows),
        },
        "timing": {
            "audio_seconds": sum(r["duration_sec"] for r in rows),
            "streaming_compute_seconds": sum(r["streaming_ms"] for r in rows) / 1000,
            "final_compute_seconds": sum(r["final_pass_ms"] for r in rows) / 1000,
        },
    }

    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    fields = [
        "id", "reference", "streaming_text", "final_text", "fire_red_effect",
        "streaming_content_cer", "final_content_cer",
        "streaming_cjk_cer", "final_cjk_cer",
        "streaming_english_recall", "final_english_recall",
        "streaming_number_recall", "final_number_recall",
        "streaming_code_recall", "final_code_recall",
        "streaming_punct_error", "final_punct_error",
        "duration_sec", "streaming_ms", "final_pass_ms",
    ]
    with (args.output_dir / "results.tsv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        for r in rows:
            writer.writerow({
                "id": r["id"],
                "reference": r["reference"],
                "streaming_text": r["streaming_text"],
                "final_text": r["final_text"],
                "fire_red_effect": r["fire_red_effect"],
                "streaming_content_cer": r["streaming"]["content_cer"],
                "final_content_cer": r["final"]["content_cer"],
                "streaming_cjk_cer": r["streaming"]["cjk_cer"],
                "final_cjk_cer": r["final"]["cjk_cer"],
                "streaming_english_recall": r["streaming"]["english_recall"],
                "final_english_recall": r["final"]["english_recall"],
                "streaming_number_recall": r["streaming"]["number_recall"],
                "final_number_recall": r["final"]["number_recall"],
                "streaming_code_recall": r["streaming"]["code_recall"],
                "final_code_recall": r["final"]["code_recall"],
                "streaming_punct_error": r["streaming"]["punct_error_rate"],
                "final_punct_error": r["final"]["punct_error_rate"],
                "duration_sec": f"{r['duration_sec']:.3f}",
                "streaming_ms": f"{r['streaming_ms']:.1f}",
                "final_pass_ms": f"{r['final_pass_ms']:.1f}",
            })

    worst = sorted(
        rows,
        key=lambda r: (r["final"]["content_cer"] or 0),
        reverse=True,
    )[:10]
    report = [
        "# VoiceIME real-sample ASR benchmark",
        "",
        f"Samples: **{len(rows)}**",
        "",
        "| Metric | Streaming | FireRed final |",
        "|---|---:|---:|",
        f"| Content CER | {pct(streaming_summary['content_cer'])} | {pct(final_summary['content_cer'])} |",
        f"| Chinese CER | {pct(streaming_summary['cjk_cer'])} | {pct(final_summary['cjk_cer'])} |",
        f"| English token recall | {pct(streaming_summary['english_recall'])} | {pct(final_summary['english_recall'])} |",
        f"| Number token recall | {pct(streaming_summary['number_recall'])} | {pct(final_summary['number_recall'])} |",
        f"| Code token recall | {pct(streaming_summary['code_recall'])} | {pct(final_summary['code_recall'])} |",
        f"| Punctuation error rate | {pct(streaming_summary['punct_error_rate'])} | {pct(final_summary['punct_error_rate'])} |",
        "",
        "FireRed effect: "
        f"**{summary['fire_red']['improved']} improved**, "
        f"**{summary['fire_red']['same']} unchanged**, "
        f"**{summary['fire_red']['worse']} worse**.",
        "",
        "## Worst final samples",
        "",
    ]
    for r in worst:
        report += [
            f"### {r['id']} — CER {pct(r['final']['content_cer'])}",
            f"- Reference: {r['reference']}",
            f"- Streaming: {r['streaming_text']}",
            f"- Final: {r['final_text']}",
            f"- FireRed: {r['fire_red_effect']}",
            "",
        ]

    (args.output_dir / "report.md").write_text(
        "\n".join(report) + "\n",
        encoding="utf-8",
    )

    print("\n" + "\n".join(report[:18]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
