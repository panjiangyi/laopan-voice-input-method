#!/usr/bin/env python3
"""Benchmark modern final ASR candidates on VoiceIME's real recordings."""
from __future__ import annotations

import argparse
import csv
import gc
import importlib.util
import re
import time
import wave
from collections import Counter
from pathlib import Path

import numpy as np
import sherpa_onnx

ROOT = Path(__file__).resolve().parents[1]
QWEN = ROOT / "models" / "sherpa-onnx-qwen3-asr-0.6B-int8-2026-03-25"
FUN = ROOT / "models" / "sherpa-onnx-funasr-nano-int8-2025-12-30"
PRIORITY = ROOT / "hotwords" / "priority.txt"
SAMPLE_RATE = 16000
ENGLISH_RE = re.compile(
    r"[A-Za-z][A-Za-z0-9]*(?:[._+:/-][A-Za-z0-9+._:/-]+)*"
)
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


def normalize_content(text: str) -> str:
    chars = list(text.lower())
    out: list[str] = []

    def ascii_alnum(ch: str) -> bool:
        return bool(ch) and ch.isascii() and ch.isalnum()

    def prev_nonspace(i: int) -> str:
        j = i - 1
        while j >= 0 and chars[j].isspace():
            j -= 1
        return chars[j] if j >= 0 else ""

    def next_nonspace(i: int) -> str:
        j = i + 1
        while j < len(chars) and chars[j].isspace():
            j += 1
        return chars[j] if j < len(chars) else ""

    for i, ch in enumerate(chars):
        p, n = prev_nonspace(i), next_nonspace(i)
        if ch.isspace():
            if (is_cjk(p) and ascii_alnum(n)) or (ascii_alnum(p) and is_cjk(n)):
                continue
            out.append(" ")
            continue
        if ch in COSMETIC:
            continue
        if ch in ",!?;:()[]{}.":
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


def pair(ref: str, hyp: str) -> tuple[int, int]:
    a, b = normalize_content(ref), normalize_content(hyp)
    return edit_distance(a, b), len(a)


def cjk_pair(ref: str, hyp: str) -> tuple[int, int]:
    a = "".join(ch for ch in ref if is_cjk(ch))
    b = "".join(ch for ch in hyp if is_cjk(ch))
    return edit_distance(a, b), len(a)


def english_recall(ref: str, hyp: str) -> tuple[int, int]:
    expected = Counter(t.casefold() for t in ENGLISH_RE.findall(ref))
    got = Counter(t.casefold() for t in ENGLISH_RE.findall(hyp))
    return (
        sum(min(n, got[token]) for token, n in expected.items()),
        sum(expected.values()),
    )


def priority_terms() -> list[str]:
    return [
        x.strip() for x in PRIORITY.read_text(encoding="utf-8").splitlines()
        if x.strip() and not x.lstrip().startswith("#")
    ]


def hotwords_prompt() -> str:
    # Both Qwen3-ASR and FunASR Nano accept comma-separated hotwords.
    return ",".join(x.replace(",", " ") for x in priority_terms())


def priority_recall(ref: str, hyp: str) -> tuple[int, int]:
    r, h = ref.casefold(), hyp.casefold()
    terms = [x for x in priority_terms() if x.casefold() in r]
    return sum(x.casefold() in h for x in terms), len(terms)


def load_manifest(path: Path):
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            wav = path.parent / Path(row["wav"]).name
            ref = (row.get("actual_text") or row.get("target_text") or "").strip()
            with wave.open(str(wav), "rb") as wf:
                if (wf.getnchannels(), wf.getsampwidth(), wf.getframerate()) != (1, 2, 16000):
                    raise ValueError(f"{wav}: expected mono s16 16kHz")
                n = wf.getnframes()
                pcm = wf.readframes(n)
            audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
            yield row["id"], ref, audio, n / SAMPLE_RATE


def make_qwen(hotwords: str):
    return sherpa_onnx.OfflineRecognizer.from_qwen3_asr(
        conv_frontend=str(QWEN / "conv_frontend.onnx"),
        encoder=str(QWEN / "encoder.int8.onnx"),
        decoder=str(QWEN / "decoder.int8.onnx"),
        tokenizer=str(QWEN / "tokenizer"),
        num_threads=4,
        hotwords=hotwords,
        max_total_len=512,
        max_new_tokens=128,
        temperature=1e-6,
        top_p=0.8,
        seed=42,
    )


def make_funasr(hotwords: str):
    return sherpa_onnx.OfflineRecognizer.from_funasr_nano(
        encoder_adaptor=str(FUN / "encoder_adaptor.int8.onnx"),
        llm=str(FUN / "llm.int8.onnx"),
        embedding=str(FUN / "embedding.int8.onnx"),
        tokenizer=str(FUN / "Qwen3-0.6B"),
        num_threads=4,
        language="",
        itn=True,
        hotwords=hotwords,
        max_new_tokens=256,
        temperature=1e-6,
        top_p=0.8,
        seed=42,
    )


def transcribe(recognizer, audio: np.ndarray) -> str:
    stream = recognizer.create_stream()
    stream.accept_waveform(SAMPLE_RATE, audio)
    recognizer.decode_stream(stream)
    result = stream.result
    return (result.text if hasattr(result, "text") else str(result)).strip()


def evaluate(name: str, recognizer, samples):
    sums = Counter()
    rows = []
    for sid, ref, audio, duration in samples:
        t0 = time.monotonic()
        hyp = transcribe(recognizer, audio)
        elapsed = time.monotonic() - t0
        ce, cn = pair(ref, hyp)
        ze, zn = cjk_pair(ref, hyp)
        eh, en = english_recall(ref, hyp)
        hh, hn = priority_recall(ref, hyp)
        sums.update(
            content_edits=ce, content_chars=cn,
            cjk_edits=ze, cjk_chars=zn,
            english_hits=eh, english_total=en,
            hotword_hits=hh, hotword_total=hn,
        )
        sums["audio_ms"] += duration * 1000
        sums["compute_ms"] += elapsed * 1000
        rows.append({
            "model": name,
            "id": sid,
            "reference": ref,
            "hypothesis": hyp,
            "content_cer": ce / max(cn, 1),
            "cjk_cer": ze / max(zn, 1),
            "english_hits": eh,
            "english_total": en,
            "hotword_hits": hh,
            "hotword_total": hn,
            "elapsed_ms": elapsed * 1000,
        })
        print(f"{name} {sid}: CER={ce/max(cn,1):.2%} EN={eh}/{en} HW={hh}/{hn}")
        print(f"  REF: {ref}")
        print(f"  HYP: {hyp}")

    def rate(a, b):
        return a / b if b else None

    return {
        "model": name,
        "content_cer": rate(sums["content_edits"], sums["content_chars"]),
        "cjk_cer": rate(sums["cjk_edits"], sums["cjk_chars"]),
        "english_recall": rate(sums["english_hits"], sums["english_total"]),
        "hotword_recall": rate(sums["hotword_hits"], sums["hotword_total"]),
        "rtf": sums["compute_ms"] / max(sums["audio_ms"], 1),
        **dict(sums),
    }, rows


def fmt(v):
    return "n/a" if v is None else f"{v:.2%}"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("manifest", type=Path)
    p.add_argument("--output-dir", type=Path, default=ROOT / "benchmark-results-modern")
    args = p.parse_args()
    samples = list(load_manifest(args.manifest))
    prompt = hotwords_prompt()
    print(f"priority hotwords={len(priority_terms())} prompt_chars={len(prompt)}")

    configs = [
        ("qwen3-no-hotwords", lambda: make_qwen("")),
        ("qwen3-priority-hotwords", lambda: make_qwen(prompt)),
        ("funasr-nano-no-hotwords", lambda: make_funasr("")),
        ("funasr-nano-priority-hotwords", lambda: make_funasr(prompt)),
    ]
    summaries, all_rows = [], []
    for name, factory in configs:
        print(f"\n===== {name} =====")
        recognizer = factory()
        summary, rows = evaluate(name, recognizer, samples)
        summaries.append(summary)
        all_rows.extend(rows)
        del recognizer
        gc.collect()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    fields = ["model","content_cer","cjk_cer","english_recall","hotword_recall","rtf"]
    with (args.output_dir / "modern-final-summary.tsv").open("w", encoding="utf-8", newline="") as fh:
        w=csv.DictWriter(fh, fieldnames=fields, delimiter="\t")
        w.writeheader()
        for row in summaries:
            w.writerow({k:row.get(k) for k in fields})

    row_fields = [
        "model","id","reference","hypothesis","content_cer","cjk_cer",
        "english_hits","english_total","hotword_hits","hotword_total","elapsed_ms"
    ]
    with (args.output_dir / "modern-final-results.tsv").open("w", encoding="utf-8", newline="") as fh:
        w=csv.DictWriter(fh, fieldnames=row_fields, delimiter="\t")
        w.writeheader()
        w.writerows(all_rows)

    report=[
        "# Modern mixed-language final ASR benchmark","",
        "| Model | Content CER | Chinese CER | English recall | Priority hotword recall | RTF |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in summaries:
        report.append(
            f"| {row['model']} | {fmt(row['content_cer'])} | {fmt(row['cjk_cer'])} | "
            f"{fmt(row['english_recall'])} | {fmt(row['hotword_recall'])} | {row['rtf']:.3f} |"
        )
    best=min(
        summaries,
        key=lambda r: (
            r["content_cer"],
            -(r["english_recall"] or 0),
            r["rtf"],
        ),
    )
    report += [
        "",
        f"Best measured candidate by content CER: **{best['model']}**.",
        "",
        "Production adoption still requires comparing it against the current "
        "streaming Paraformer baseline (12.23% content CER, 8.22% Chinese CER, "
        "58.54% English recall) and validating finalization latency.",
    ]
    (args.output_dir / "modern-final-report.md").write_text(
        "\n".join(report)+"\n", encoding="utf-8"
    )
    print("\n" + "\n".join(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
