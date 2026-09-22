#!/usr/bin/env python3
"""Benchmark the exact default VoiceIME mixed-language production gate.

This reports both the quality ceiling (offline final used for every utterance)
and the actual bounded-latency default:
  streaming Paraformer
  -> offline Paraformer large only when audio <= max_audio AND inference
     finishes within max_wait
  -> deterministic glossary correction
  -> guarded local punctuation restoration
"""
from __future__ import annotations

import argparse
import csv
import re
import time
import wave
from collections import Counter
from pathlib import Path
import sys

import numpy as np
import sherpa_onnx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from voiceime_glossary import GlossaryCorrector  # noqa: E402

SAMPLE_RATE = 16000
STREAMING = ROOT / "models" / "sherpa-onnx-streaming-paraformer-bilingual-zh-en"
FINAL = ROOT / "models" / "sherpa-onnx-paraformer-zh-2024-03-09"
PUNCT = (
    ROOT / "models"
    / "sherpa-onnx-punct-ct-transformer-zh-en-vocab272727-2024-04-12-int8"
    / "model.int8.onnx"
)
TOKEN_RE = re.compile(
    r"[A-Za-z][A-Za-z0-9]*(?:[._+:/-][A-Za-z0-9+._:/-]+)*"
)
PUNCT_SET = set("，。！？；：、“”‘’（）《》〈〉,.!?;:()[]{}…—")
COSMETIC = set("，。！？；：“”‘’（）《》〈〉")


def is_cjk(ch: str) -> bool:
    if not ch:
        return False
    cp = ord(ch)
    return (
        0x3400 <= cp <= 0x4DBF
        or 0x4E00 <= cp <= 0x9FFF
        or 0xF900 <= cp <= 0xFAFF
    )


def ascii_alnum(ch: str) -> bool:
    return bool(ch) and ch.isascii() and ch.isalnum()


def normalize_content(text: str) -> str:
    chars = list(text.lower())
    out: list[str] = []

    def prev(i: int) -> str:
        j = i - 1
        while j >= 0 and chars[j].isspace():
            j -= 1
        return chars[j] if j >= 0 else ""

    def nxt(i: int) -> str:
        j = i + 1
        while j < len(chars) and chars[j].isspace():
            j += 1
        return chars[j] if j < len(chars) else ""

    for i, ch in enumerate(chars):
        p, n = prev(i), nxt(i)
        if ch.isspace():
            if (is_cjk(p) and ascii_alnum(n)) or (
                ascii_alnum(p) and is_cjk(n)
            ):
                continue
            out.append(" ")
            continue
        if ch in COSMETIC:
            continue
        if ch in ",.!?;:()[]{}":
            if ascii_alnum(p) and ascii_alnum(n):
                out.append(ch)
            continue
        out.append(ch)
    return "".join(out)


def semantic_signature(text: str) -> str:
    chars = list(text)
    out: list[str] = []

    def prev(i: int) -> str:
        j = i - 1
        while j >= 0 and chars[j].isspace():
            j -= 1
        return chars[j] if j >= 0 else ""

    def nxt(i: int) -> str:
        j = i + 1
        while j < len(chars) and chars[j].isspace():
            j += 1
        return chars[j] if j < len(chars) else ""

    for i, ch in enumerate(chars):
        p, n = prev(i), nxt(i)
        if ch.isspace():
            if (is_cjk(p) and ascii_alnum(n)) or (
                ascii_alnum(p) and is_cjk(n)
            ):
                continue
            out.append(" ")
            continue
        if ch in set("，。！？；、“”‘’"):
            if ascii_alnum(p) and ascii_alnum(n):
                out.append(ch)
            continue
        if ch in set(",!?;"):
            if ascii_alnum(p) and ascii_alnum(n):
                out.append(ch)
            continue
        out.append(ch)
    return "".join(out)


def edit_distance(a: str, b: str) -> int:
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


def content_pair(ref: str, hyp: str) -> tuple[int, int]:
    a, b = normalize_content(ref), normalize_content(hyp)
    return edit_distance(a, b), len(a)


def cjk_pair(ref: str, hyp: str) -> tuple[int, int]:
    a = "".join(ch for ch in ref if is_cjk(ch))
    b = "".join(ch for ch in hyp if is_cjk(ch))
    return edit_distance(a, b), len(a)


def token_hits(ref: str, hyp: str) -> tuple[int, int]:
    expected = Counter(t.casefold() for t in TOKEN_RE.findall(ref))
    got = Counter(t.casefold() for t in TOKEN_RE.findall(hyp))
    lowered = hyp.casefold()
    hits = 0
    for token, count in expected.items():
        direct = got.get(token, 0)
        if direct:
            hits += min(count, direct)
        else:
            hits += min(count, lowered.count(token))
    return hits, sum(expected.values())


def punct_pair(ref: str, hyp: str) -> tuple[int, int]:
    a = "".join(ch for ch in ref if ch in PUNCT_SET)
    b = "".join(ch for ch in hyp if ch in PUNCT_SET)
    return edit_distance(a, b), len(a)


def load_samples(manifest: Path):
    with manifest.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            wav = manifest.parent / Path(row["wav"]).name
            ref = (row.get("actual_text") or row.get("target_text") or "").strip()
            with wave.open(str(wav), "rb") as wf:
                if (wf.getnchannels(), wf.getsampwidth(), wf.getframerate()) != (
                    1, 2, SAMPLE_RATE
                ):
                    raise ValueError(f"{wav}: expected mono s16 16kHz")
                frames = wf.getnframes()
                pcm = wf.readframes(frames)
            audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
            yield row["id"], ref, audio, frames / SAMPLE_RATE


def pick(directory: Path, *names: str) -> Path:
    for name in names:
        path = directory / name
        if path.exists():
            return path
    raise FileNotFoundError(f"none of {names!r} found in {directory}")


def make_streaming():
    return sherpa_onnx.OnlineRecognizer.from_paraformer(
        tokens=str(pick(STREAMING, "tokens.txt")),
        encoder=str(pick(STREAMING, "encoder.int8.onnx", "encoder.onnx")),
        decoder=str(pick(STREAMING, "decoder.int8.onnx", "decoder.onnx")),
        num_threads=4,
        sample_rate=SAMPLE_RATE,
        feature_dim=80,
        decoding_method="greedy_search",
        enable_endpoint_detection=False,
    )


def make_final():
    return sherpa_onnx.OfflineRecognizer.from_paraformer(
        paraformer=str(FINAL / "model.int8.onnx"),
        tokens=str(FINAL / "tokens.txt"),
        num_threads=4,
    )


def make_punctuation():
    cfg = sherpa_onnx.OfflinePunctuationConfig(
        model=sherpa_onnx.OfflinePunctuationModelConfig(
            ct_transformer=str(PUNCT),
            num_threads=1,
            provider="cpu",
        )
    )
    return sherpa_onnx.OfflinePunctuation(cfg)


def decode_streaming(asr, audio: np.ndarray) -> str:
    stream = asr.create_stream()
    chunk = int(SAMPLE_RATE * 0.08)
    for start in range(0, len(audio), chunk):
        stream.accept_waveform(SAMPLE_RATE, audio[start:start + chunk])
        while asr.is_ready(stream):
            asr.decode_stream(stream)
    stream.accept_waveform(SAMPLE_RATE, np.zeros(SAMPLE_RATE, dtype=np.float32))
    try:
        stream.input_finished()
    except Exception:
        pass
    while asr.is_ready(stream):
        asr.decode_stream(stream)
    result = asr.get_result(stream)
    return (result.text if hasattr(result, "text") else str(result)).strip()


def decode_final(asr, audio: np.ndarray) -> str:
    stream = asr.create_stream()
    stream.accept_waveform(SAMPLE_RATE, audio)
    asr.decode_stream(stream)
    result = stream.result
    return (result.text if hasattr(result, "text") else str(result)).strip()


def safe_punctuate(punctuation, text: str) -> tuple[str, bool]:
    candidate = punctuation.add_punctuation(text).strip()
    if candidate and semantic_signature(text) == semantic_signature(candidate):
        return candidate, False
    return text, bool(candidate and candidate != text)


def add_metrics(counter: Counter, ref: str, hyp: str) -> None:
    ce, cn = content_pair(ref, hyp)
    ze, zn = cjk_pair(ref, hyp)
    eh, en = token_hits(ref, hyp)
    pe, pn = punct_pair(ref, hyp)
    counter.update(
        content_edits=ce, content_chars=cn,
        cjk_edits=ze, cjk_chars=zn,
        english_hits=eh, english_total=en,
        punct_edits=pe, punct_total=pn,
    )


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("manifest", type=Path)
    p.add_argument("--max-wait", type=float, default=1.2)
    p.add_argument("--max-audio", type=float, default=10.0)
    p.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "benchmark-results-production",
    )
    args = p.parse_args()

    streaming_asr = make_streaming()
    final_asr = make_final()
    glossary = GlossaryCorrector()
    punctuation = make_punctuation()

    stages = {
        "streaming": Counter(),
        "streaming+glossary+punct": Counter(),
        "offline-quality-ceiling": Counter(),
        "default-gated-production": Counter(),
    }
    rows = []
    total_audio = total_final_compute = 0.0
    punctuation_rejected = 0
    final_used = final_timeout = final_long_skip = 0

    for sid, ref, audio, duration in load_samples(args.manifest):
        streaming = decode_streaming(streaming_asr, audio)
        streaming_gloss = glossary.correct(streaming)
        streaming_post, rejected = safe_punctuate(punctuation, streaming_gloss)
        punctuation_rejected += int(rejected)

        final_started = time.monotonic()
        raw_final = decode_final(final_asr, audio)
        final_elapsed = time.monotonic() - final_started
        total_final_compute += final_elapsed
        total_audio += duration

        final_gloss = glossary.correct(raw_final)
        final_post, rejected = safe_punctuate(punctuation, final_gloss)
        punctuation_rejected += int(rejected)

        if duration > args.max_audio:
            production = streaming_post
            decision = "streaming-long"
            final_long_skip += 1
        elif final_elapsed > args.max_wait:
            production = streaming_post
            decision = "streaming-timeout"
            final_timeout += 1
        else:
            production = final_post
            decision = "offline-final"
            final_used += 1

        stage_texts = {
            "streaming": streaming,
            "streaming+glossary+punct": streaming_post,
            "offline-quality-ceiling": final_post,
            "default-gated-production": production,
        }
        for name, hyp in stage_texts.items():
            add_metrics(stages[name], ref, hyp)

        rows.append({
            "id": sid,
            "reference": ref,
            "streaming": streaming,
            "offline_final": raw_final,
            "production": production,
            "decision": decision,
            "audio_sec": f"{duration:.3f}",
            "final_elapsed_ms": f"{final_elapsed * 1000:.1f}",
        })
        print(
            f"{sid}: {decision} audio={duration:.2f}s "
            f"final={final_elapsed:.3f}s  {production}"
        )

    def rate(c: Counter, a: str, b: str):
        return c[a] / c[b] if c[b] else None

    summaries = []
    for name, c in stages.items():
        summaries.append({
            "stage": name,
            "content_cer": rate(c, "content_edits", "content_chars"),
            "cjk_cer": rate(c, "cjk_edits", "cjk_chars"),
            "english_recall": rate(c, "english_hits", "english_total"),
            "punct_error": rate(c, "punct_edits", "punct_total"),
        })

    args.output_dir.mkdir(parents=True, exist_ok=True)
    with (args.output_dir / "summary.tsv").open(
        "w", encoding="utf-8", newline=""
    ) as fh:
        fields = ["stage", "content_cer", "cjk_cer", "english_recall", "punct_error"]
        w = csv.DictWriter(fh, fieldnames=fields, delimiter="\t")
        w.writeheader()
        w.writerows(summaries)

    with (args.output_dir / "results.tsv").open(
        "w", encoding="utf-8", newline=""
    ) as fh:
        fields = [
            "id", "reference", "streaming", "offline_final", "production",
            "decision", "audio_sec", "final_elapsed_ms",
        ]
        w = csv.DictWriter(fh, fieldnames=fields, delimiter="\t")
        w.writeheader()
        w.writerows(rows)

    fmt = lambda v: "n/a" if v is None else f"{v:.2%}"
    report = [
        "# Exact default VoiceIME production benchmark",
        "",
        f"Gate: final wait <= **{args.max_wait:.2f}s**, audio <= "
        f"**{args.max_audio:.2f}s**.",
        "",
        "| Stage | Content CER | Chinese CER | English recall | Punctuation error |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in summaries:
        report.append(
            f"| {row['stage']} | {fmt(row['content_cer'])} | "
            f"{fmt(row['cjk_cer'])} | {fmt(row['english_recall'])} | "
            f"{fmt(row['punct_error'])} |"
        )
    report += [
        "",
        f"Default gate used offline final for **{final_used}/30** samples; "
        f"timed out on **{final_timeout}**; long-audio skips **{final_long_skip}**.",
        f"Offline final RTF: **{total_final_compute/max(total_audio, 1e-9):.3f}** "
        f"({total_final_compute:.2f}s compute / {total_audio:.2f}s audio).",
        f"Punctuation guard rejected **{punctuation_rejected}** lexical mutations.",
    ]
    (args.output_dir / "report.md").write_text(
        "\n".join(report) + "\n", encoding="utf-8"
    )
    print("\n" + "\n".join(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
