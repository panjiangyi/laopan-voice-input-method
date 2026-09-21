#!/usr/bin/env python3
"""Compare offline final-pass candidates on the recorded VoiceIME samples."""
from __future__ import annotations

import argparse
import csv
import gc
import json
import os
import runpy
import time
import wave
from collections import Counter
from pathlib import Path

import numpy as np
import sherpa_onnx

ROOT = Path(__file__).resolve().parents[1]
BENCH = runpy.run_path(str(ROOT / "scripts/15-evaluate-samples.py"))
metrics = BENCH["metrics"]
pct = BENCH["pct"]


def read_samples(manifest: Path):
    rows = []
    with manifest.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            wav = manifest.parent / Path(row["wav"]).name
            ref = (row.get("actual_text") or row.get("target_text") or "").strip()
            with wave.open(str(wav), "rb") as wf:
                if (wf.getnchannels(), wf.getsampwidth(), wf.getframerate()) != (1, 2, 16000):
                    raise ValueError(f"unexpected WAV format: {wav}")
                pcm = wf.readframes(wf.getnframes())
            samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
            rows.append((row["id"], ref, samples))
    return rows


def transcribe(recognizer, samples: np.ndarray) -> str:
    stream = recognizer.create_stream()
    stream.accept_waveform(16000, samples)
    recognizer.decode_stream(stream)
    result = stream.result
    return (result.text if hasattr(result, "text") else str(result)).strip()


def aggregate(rows: list[dict]) -> dict:
    sums = Counter()
    for row in rows:
        m = row["metrics"]
        for key in (
            "content_edits", "content_chars", "cjk_edits", "cjk_chars",
            "punct_edits", "punct_count", "english_hits", "english_total",
            "number_hits", "number_total", "code_hits", "code_total",
        ):
            sums[key] += m[key]

    def rate(a, b):
        return a / b if b else None

    return {
        "samples": len(rows),
        "content_cer": rate(sums["content_edits"], sums["content_chars"]),
        "cjk_cer": rate(sums["cjk_edits"], sums["cjk_chars"]),
        "punct_error_rate": rate(sums["punct_edits"], sums["punct_count"]),
        "english_recall": rate(sums["english_hits"], sums["english_total"]),
        "number_recall": rate(sums["number_hits"], sums["number_total"]),
        "code_recall": rate(sums["code_hits"], sums["code_total"]),
        **dict(sums),
    }


def recognizers():
    threads = max(1, min(4, (os.cpu_count() or 2) // 2))

    fire = ROOT / "models/sherpa-onnx-fire-red-asr2-ctc-zh_en-int8-2026-02-25"
    yield "fire-red-asr2-ctc", sherpa_onnx.OfflineRecognizer.from_fire_red_asr_ctc(
        model=str(fire / "model.int8.onnx"),
        tokens=str(fire / "tokens.txt"),
        num_threads=threads,
    )

    para = ROOT / "models/sherpa-onnx-paraformer-zh-2024-03-09"
    yield "paraformer-offline-large", sherpa_onnx.OfflineRecognizer.from_paraformer(
        paraformer=str(para / "model.int8.onnx"),
        tokens=str(para / "tokens.txt"),
        num_threads=threads,
    )

    sense = ROOT / "models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17"
    yield "sensevoice-itn", sherpa_onnx.OfflineRecognizer.from_sense_voice(
        model=str(sense / "model.int8.onnx"),
        tokens=str(sense / "tokens.txt"),
        num_threads=threads,
        language="auto",
        use_itn=True,
    )


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("manifest", type=Path)
    p.add_argument("--output-dir", type=Path, default=ROOT / "benchmark-results")
    args = p.parse_args()
    samples = read_samples(args.manifest)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    summaries = {}
    all_rows = []

    for name, rec in recognizers():
        print(f"\n=== {name} ===")
        model_rows = []
        t0 = time.monotonic()
        for sid, ref, audio in samples:
            start = time.monotonic()
            hyp = transcribe(rec, audio)
            elapsed = (time.monotonic() - start) * 1000
            m = metrics(ref, hyp)
            row = {
                "model": name,
                "id": sid,
                "reference": ref,
                "hypothesis": hyp,
                "elapsed_ms": elapsed,
                "metrics": m,
            }
            model_rows.append(row)
            all_rows.append(row)
            print(f"{sid}: CER={pct(m['content_cer'])}  {hyp}")
        summary = aggregate(model_rows)
        summary["compute_seconds"] = time.monotonic() - t0
        summaries[name] = summary
        del rec
        gc.collect()

    with (args.output_dir / "final-model-summary.tsv").open(
        "w", encoding="utf-8", newline=""
    ) as fh:
        fields = [
            "model", "content_cer", "cjk_cer", "english_recall",
            "number_recall", "code_recall", "punct_error_rate",
            "compute_seconds",
        ]
        w = csv.DictWriter(fh, fieldnames=fields, delimiter="\t")
        w.writeheader()
        for name, sm in summaries.items():
            w.writerow({"model": name, **{k: sm.get(k) for k in fields if k != "model"}})

    with (args.output_dir / "final-model-results.tsv").open(
        "w", encoding="utf-8", newline=""
    ) as fh:
        fields = [
            "model", "id", "reference", "hypothesis", "elapsed_ms",
            "content_cer", "cjk_cer", "english_recall",
            "number_recall", "code_recall", "punct_error_rate",
        ]
        w = csv.DictWriter(fh, fieldnames=fields, delimiter="\t")
        w.writeheader()
        for row in all_rows:
            m = row["metrics"]
            w.writerow({
                "model": row["model"],
                "id": row["id"],
                "reference": row["reference"],
                "hypothesis": row["hypothesis"],
                "elapsed_ms": f"{row['elapsed_ms']:.1f}",
                "content_cer": m["content_cer"],
                "cjk_cer": m["cjk_cer"],
                "english_recall": m["english_recall"],
                "number_recall": m["number_recall"],
                "code_recall": m["code_recall"],
                "punct_error_rate": m["punct_error_rate"],
            })

    (args.output_dir / "final-model-summary.json").write_text(
        json.dumps(summaries, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print("\n=== FINAL MODEL SUMMARY ===")
    print("model\tcontent CER\tCJK CER\tEnglish\tnumbers\tcode\tpunct\tseconds")
    for name, sm in summaries.items():
        print(
            f"{name}\t{pct(sm['content_cer'])}\t{pct(sm['cjk_cer'])}\t"
            f"{pct(sm['english_recall'])}\t{pct(sm['number_recall'])}\t"
            f"{pct(sm['code_recall'])}\t{pct(sm['punct_error_rate'])}\t"
            f"{sm['compute_seconds']:.2f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
