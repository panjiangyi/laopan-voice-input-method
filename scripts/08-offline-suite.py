#!/usr/bin/env python3
"""Evaluate the current VoiceIME ASR path with real character error rate.

This replaces the legacy Vosk/set-overlap benchmark. It runs the same default
recognition stack as voiceime-engine:
  sherpa-onnx streaming Paraformer -> optional FireRedASR2 final pass

Metrics:
  - exact match after normalization
  - Levenshtein character edit distance
  - CER = edits / reference characters

The script intentionally does not enable the experimental LLM rewriter.
"""
from __future__ import annotations

import argparse
import csv
import re
import runpy
import sys
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = runpy.run_path(str(ROOT / "voiceime-engine"))
SherpaRecognizer = ENGINE["SherpaRecognizer"]
FinalRecognizer = ENGINE["FinalRecognizer"]

CASES = [
    ("T-001", "你好这是一个测试"),
    ("T-002", "今天的天气不错"),
    ("T-003", "我正在使用语音输入"),
    ("T-004", "这个功能可以直接输入"),
    ("T-005", "请帮我记录这个问题"),
    ("T-101", "我想在Ubuntu上实现一个像输入法一样的语音输入工具"),
    ("T-102", "这个项目第一阶段应该先验证核心链路是否可行"),
    ("T-103", "如果效果不错后面再考虑基于开源项目进行二次开发"),
    ("T-201", "今天review一下这个pull request"),
    ("T-202", "我们需要测试Ubuntu和Wayland的兼容性"),
    ("T-203", "这个功能后面可以迁移到Fcitx5插件"),
]


def normalize(text: str) -> str:
    # CER is about recognition content, not formatting. Keep symbols that are
    # part of code/numbers; remove only whitespace and sentence punctuation.
    cosmetic = set("，。！？；、“”‘’,!?;")
    return "".join(
        ch.lower()
        for ch in text
        if not ch.isspace() and ch not in cosmetic
    )


def edit_distance(a: str, b: str) -> int:
    """Levenshtein distance with O(min(len(a), len(b))) memory."""
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


def cer(reference: str, hypothesis: str) -> tuple[int, float]:
    ref = normalize(reference)
    hyp = normalize(hypothesis)
    dist = edit_distance(ref, hyp)
    return dist, dist / max(len(ref), 1)


def raw_cer(reference: str, hypothesis: str) -> tuple[int, float]:
    ref = reference.lower()
    hyp = hypothesis.lower()
    dist = edit_distance(ref, hyp)
    return dist, dist / max(len(ref), 1)


def token_distance(pattern: str, reference: str, hypothesis: str) -> tuple[int, int]:
    """Return edit distance and reference count for one token category."""
    ref = re.findall(pattern, reference.lower())
    hyp = re.findall(pattern, hypothesis.lower())
    return edit_distance(ref, hyp), len(ref)


def load_cases(args) -> list[tuple[str, str, Path]]:
    if args.manifest:
        cases = []
        with args.manifest.open(encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh, delimiter="\t"):
                wav = Path(row["wav"])
                if not wav.is_absolute():
                    wav = args.manifest.parent / wav
                expected = row.get("actual_text") or row["target_text"]
                cases.append((row["id"], expected, wav))
        return cases
    return [(cid, expected, args.wav_dir / f"{cid}_16k.wav") for cid, expected in CASES]


def read_pcm16_mono_16k(path: Path) -> bytes:
    with wave.open(str(path), "rb") as wf:
        if wf.getnchannels() != 1:
            raise ValueError(f"{path}: expected mono WAV")
        if wf.getsampwidth() != 2:
            raise ValueError(f"{path}: expected 16-bit PCM WAV")
        if wf.getframerate() != 16000:
            raise ValueError(f"{path}: expected 16000 Hz WAV")
        return wf.readframes(wf.getnframes())


def recognize_current(asr, final_asr, pcm: bytes) -> tuple[str, str]:
    stream = asr.create_stream()
    chunk_bytes = 3200 * 2  # 100 ms @ 16kHz, int16 mono
    for start in range(0, len(pcm), chunk_bytes):
        asr.accept_pcm(stream, pcm[start:start + chunk_bytes])
        asr.decode_ready(stream)
    streaming = asr.finalize(stream).strip()

    final = streaming
    try:
        refined = final_asr.transcribe(pcm)
        if refined:
            final = refined
    except Exception as ex:
        print(
            f"WARN: FireRed second pass failed, using streaming result: {ex!r}",
            file=sys.stderr,
        )
    return streaming, final


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest",
        type=Path,
        help="TSV produced by 14-record-samples.sh (uses actual_text)",
    )
    parser.add_argument(
        "--wav-dir",
        type=Path,
        default=ROOT / "logs",
        help="directory containing T-xxx_16k.wav files",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "logs" / "current_asr_cer.tsv",
    )
    args = parser.parse_args()

    if args.manifest and args.output == ROOT / "logs" / "current_asr_cer.tsv":
        args.output = args.manifest.parent / "asr-evaluation.tsv"

    print("Loading current VoiceIME recognizers...")
    asr = SherpaRecognizer()
    final_asr = FinalRecognizer()

    rows = []
    total_edits = 0
    total_ref_chars = 0
    exact_count = 0
    raw_edits = 0
    raw_chars = 0
    category_totals = {
        "english": [0, 0],
        "number": [0, 0],
        "punctuation": [0, 0],
        "code": [0, 0],
    }

    for cid, expected, wav in load_cases(args):
        if not wav.exists():
            print(f"{cid}: SKIP missing {wav}")
            continue

        pcm = read_pcm16_mono_16k(wav)
        streaming, final = recognize_current(asr, final_asr, pcm)
        distance, rate = cer(expected, final)
        raw_distance, raw_rate = raw_cer(expected, final)
        ref_len = len(normalize(expected))
        exact = normalize(expected) == normalize(final)

        total_edits += distance
        total_ref_chars += ref_len
        exact_count += int(exact)
        raw_edits += raw_distance
        raw_chars += len(expected)
        category_values = {}
        for name, pattern in {
            "english": r"[a-z]+(?:[_-][a-z0-9]+)*",
            "number": r"\d+(?:\.\d+)*",
            "punctuation": r"[，。！？；：、“”‘’（）(),.!?;:_-]",
            "code": r"\b[a-z][a-z0-9]*(?:[_-][a-z0-9]+)+\b",
        }.items():
            errors, count = token_distance(pattern, expected, final)
            category_totals[name][0] += errors
            category_totals[name][1] += count
            category_values[f"{name}_errors"] = errors
            category_values[f"{name}_reference"] = count
        rows.append({
            "case": cid,
            "expected": expected,
            "streaming": streaming,
            "final": final,
            "edit_distance": distance,
            "ref_chars": ref_len,
            "cer": f"{rate:.6f}",
            "raw_cer": f"{raw_rate:.6f}",
            "exact": "1" if exact else "0",
            **category_values,
        })

        print(f"{cid}: expected={expected}")
        print(f"       streaming={streaming}")
        print(f"       final={final}")
        print(f"       edit_distance={distance} CER={rate:.2%} exact={exact}")

    if not rows:
        print("No WAV cases found; nothing evaluated.", file=sys.stderr)
        return 2

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "case", "expected", "streaming", "final",
                "edit_distance", "ref_chars", "cer", "exact",
                "raw_cer", "english_errors", "english_reference",
                "number_errors", "number_reference",
                "punctuation_errors", "punctuation_reference",
                "code_errors", "code_reference",
            ],
            delimiter="\t",
        )
        writer.writeheader()
        writer.writerows(rows)

    micro_cer = total_edits / max(total_ref_chars, 1)
    print()
    print(
        f"SUMMARY cases={len(rows)} exact={exact_count}/{len(rows)} "
        f"content_accuracy={1 - micro_cer:.2%} "
        f"raw_accuracy={1 - raw_edits / max(raw_chars, 1):.2%}"
    )
    for name, (errors, count) in category_totals.items():
        if count:
            accuracy = max(0.0, 1 - errors / count)
            print(f"{name}_accuracy={accuracy:.2%} (errors={errors}, reference={count})")
        else:
            print(f"{name}_accuracy=N/A (no reference tokens)")
    print(f"TSV: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
