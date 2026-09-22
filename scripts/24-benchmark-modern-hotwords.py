#!/usr/bin/env python3
"""Benchmark modern hotword-capable final-pass ASR models on real VoiceIME audio."""
from __future__ import annotations

import argparse
import csv
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
PERSONAL = Path.home() / ".config" / "voiceime" / "hotwords.txt"

TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:[._+:/-][A-Za-z0-9+._:/-]+)*")
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
            if (is_cjk(p) and n.isascii() and n.isalnum()) or (
                p.isascii() and p.isalnum() and is_cjk(n)
            ):
                continue
            out.append(" ")
            continue
        if ch in COSMETIC:
            continue
        if ch in ",!?;:()[]{}":
            if p.isascii() and p.isalnum() and n.isascii() and n.isalnum():
                out.append(ch)
            continue
        if ch == ".":
            if p.isascii() and p.isalnum() and n.isascii() and n.isalnum():
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


def token_recall(ref: str, hyp: str) -> tuple[int, int]:
    expected = Counter(t.casefold() for t in TOKEN_RE.findall(ref))
    got = Counter(t.casefold() for t in TOKEN_RE.findall(hyp))
    return (
        sum(min(n, got[t]) for t, n in expected.items()),
        sum(expected.values()),
    )


def load_terms(path: Path) -> list[str]:
    if not path.is_file():
        return []
    result = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        term = raw.strip()
        if term and not term.startswith("#"):
            result.append(term)
    return result


def hotword_string() -> str:
    # Personal words come first because they are the most important and most
    # likely to be proper nouns. Keep the built-in list intentionally compact.
    seen = set()
    terms = []
    for term in load_terms(PERSONAL) + load_terms(PRIORITY):
        key = term.casefold()
        if key not in seen:
            seen.add(key)
            terms.append(term)
    return ",".join(terms)


def phrase_recall(ref: str, hyp: str, terms: list[str]) -> tuple[int, int]:
    r, h = ref.casefold(), hyp.casefold()
    present = [t for t in terms if t.casefold() in r]
    return sum(t.casefold() in h for t in present), len(present)


def load_manifest(path: Path):
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            wav = path.parent / Path(row["wav"]).name
            ref = (row.get("actual_text") or row.get("target_text") or "").strip()
            yield row["id"], wav, ref


def read_wav(path: Path) -> tuple[np.ndarray, float]:
    with wave.open(str(path), "rb") as wf:
        if (wf.getnchannels(), wf.getsampwidth(), wf.getframerate()) != (1, 2, 16000):
            raise ValueError(f"{path}: expected mono s16 16kHz")
        n = wf.getnframes()
        pcm = wf.readframes(n)
    return np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0, n / 16000


def make_qwen(hotwords: str):
    return sherpa_onnx.OfflineRecognizer.from_qwen3_asr(
        conv_frontend=str(QWEN / "conv_frontend.onnx"),
        encoder=str(QWEN / "encoder.int8.onnx"),
        decoder=str(QWEN / "decoder.int8.onnx"),
        tokenizer=str(QWEN / "tokenizer"),
        hotwords=hotwords,
        num_threads=2,
        sample_rate=16000,
        feature_dim=128,
        provider="cpu",
        max_total_len=768,
        max_new_tokens=192,
        temperature=1e-6,
        top_p=0.8,
        seed=42,
    )


def make_fun(hotwords: str):
    return sherpa_onnx.OfflineRecognizer.from_funasr_nano(
        encoder_adaptor=str(FUN / "encoder_adaptor.int8.onnx"),
        llm=str(FUN / "llm.int8.onnx"),
        embedding=str(FUN / "embedding.int8.onnx"),
        tokenizer=str(FUN / "Qwen3-0.6B"),
        num_threads=2,
        provider="cpu",
        system_prompt="You are a speech recognition model. Transcribe exactly.",
        user_prompt="语音转写:",
        max_new_tokens=192,
        temperature=1e-6,
        top_p=0.8,
        seed=42,
        language="",
        itn=True,
        hotwords=hotwords,
    )


def decode(recognizer, audio: np.ndarray) -> str:
    stream = recognizer.create_stream()
    stream.accept_waveform(16000, audio)
    recognizer.decode_stream(stream)
    result = stream.result
    return (result.text if hasattr(result, "text") else str(result)).strip()


def evaluate(name, recognizer, samples, terms):
    sums = Counter()
    rows = []
    for sid, ref, audio, duration in samples:
        t0 = time.monotonic()
        hyp = decode(recognizer, audio)
        elapsed = time.monotonic() - t0
        ce, cn = pair(ref, hyp)
        ze, zn = cjk_pair(ref, hyp)
        eh, en = token_recall(ref, hyp)
        hh, hn = phrase_recall(ref, hyp, terms)
        sums.update(content_edits=ce, content_chars=cn, cjk_edits=ze, cjk_chars=zn,
                    english_hits=eh, english_total=en, hotword_hits=hh, hotword_total=hn)
        sums["compute_ms"] += elapsed * 1000
        sums["audio_ms"] += duration * 1000
        rows.append({
            "model": name, "id": sid, "reference": ref, "hypothesis": hyp,
            "content_cer": ce / max(cn, 1), "cjk_cer": ze / max(zn, 1),
            "english_hits": eh, "english_total": en,
            "hotword_hits": hh, "hotword_total": hn,
            "elapsed_ms": elapsed * 1000,
        })
        print(f"{name} {sid}: CER={ce/max(cn,1):.2%} EN={eh}/{en} HW={hh}/{hn}")
        print(f"  HYP: {hyp}")

    def rate(a,b):
        return a / b if b else None
    return {
        "model": name,
        "content_cer": rate(sums["content_edits"], sums["content_chars"]),
        "cjk_cer": rate(sums["cjk_edits"], sums["cjk_chars"]),
        "english_recall": rate(sums["english_hits"], sums["english_total"]),
        "hotword_recall": rate(sums["hotword_hits"], sums["hotword_total"]),
        "rtf": sums["compute_ms"] / max(sums["audio_ms"], 1),
    }, rows


def fmt(v):
    return "n/a" if v is None else f"{v:.2%}"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("manifest", type=Path)
    p.add_argument("--output-dir", type=Path, default=ROOT / "benchmark-results-modern")
    args = p.parse_args()

    samples = []
    for sid, wav, ref in load_manifest(args.manifest):
        audio, duration = read_wav(wav)
        samples.append((sid, ref, audio, duration))

    hot = hotword_string()
    terms = [x for x in hot.split(",") if x]
    print(f"priority hotwords: {len(terms)} terms, {len(hot)} chars")

    configs = [
        ("qwen3-no-hotwords", lambda: make_qwen("")),
        ("qwen3-hotwords", lambda: make_qwen(hot)),
        ("funasr-nano-no-hotwords", lambda: make_fun("")),
        ("funasr-nano-hotwords", lambda: make_fun(hot)),
    ]

    summaries, rows = [], []
    for name, factory in configs:
        print(f"\n===== {name} =====")
        rec = factory()
        summary, detail = evaluate(name, rec, samples, terms)
        summaries.append(summary)
        rows.extend(detail)
        del rec

    args.output_dir.mkdir(parents=True, exist_ok=True)
    fields = ["model","content_cer","cjk_cer","english_recall","hotword_recall","rtf"]
    with (args.output_dir / "summary.tsv").open("w", encoding="utf-8", newline="") as fh:
        w=csv.DictWriter(fh,fieldnames=fields,delimiter="\t"); w.writeheader(); w.writerows(summaries)
    rfields = ["model","id","reference","hypothesis","content_cer","cjk_cer",
               "english_hits","english_total","hotword_hits","hotword_total","elapsed_ms"]
    with (args.output_dir / "results.tsv").open("w", encoding="utf-8", newline="") as fh:
        w=csv.DictWriter(fh,fieldnames=rfields,delimiter="\t"); w.writeheader(); w.writerows(rows)

    report=[
        "# Modern hotword final-pass benchmark","",
        "Current production streaming baseline from the same 30 samples: "
        "**12.23% content CER, 8.22% Chinese CER, 58.54% English token recall**.","",
        "| Model | Content CER | Chinese CER | English recall | Hotword recall | RTF |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for s in summaries:
        report.append(
            f"| {s['model']} | {fmt(s['content_cer'])} | {fmt(s['cjk_cer'])} | "
            f"{fmt(s['english_recall'])} | {fmt(s['hotword_recall'])} | {s['rtf']:.3f} |"
        )
    report += ["", "## Decision guardrail", ""]
    eligible=[
        s for s in summaries if
        s["content_cer"] <= 0.1223 + 0.01 and
        s["cjk_cer"] <= 0.0822 + 0.02 and
        (s["english_recall"] or 0) >= 0.5854
    ]
    if eligible:
        winner=min(eligible,key=lambda s:(-(s["english_recall"] or 0),-(s["hotword_recall"] or 0),s["content_cer"],s["rtf"]))
        report.append(f"Eligible winner: **{winner['model']}**.")
    else:
        report.append("No candidate passes the production guardrail; keep Paraformer-only production behavior.")
    (args.output_dir/"report.md").write_text("\n".join(report)+"\n",encoding="utf-8")
    print("\n"+"\n".join(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
