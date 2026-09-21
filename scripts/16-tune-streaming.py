#!/usr/bin/env python3
"""Sweep streaming final-silence duration on the real recorded sample set."""
from __future__ import annotations

import argparse
import csv
import runpy
import time
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
ENGINE = runpy.run_path(str(ROOT / "voiceime-engine"))
BENCH = runpy.run_path(str(ROOT / "scripts/15-evaluate-samples.py"))
SherpaRecognizer = ENGINE["SherpaRecognizer"]
content_error = BENCH["content_error"]


def load_manifest(path: Path):
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            wav = path.parent / Path(row["wav"]).name
            ref = (row.get("actual_text") or row.get("target_text") or "").strip()
            yield row["id"], wav, ref


def read_pcm(path: Path) -> bytes:
    with wave.open(str(path), "rb") as wf:
        if (wf.getnchannels(), wf.getsampwidth(), wf.getframerate()) != (1, 2, 16000):
            raise ValueError(f"unexpected WAV format: {path}")
        return wf.readframes(wf.getnframes())


def decode(asr, pcm: bytes, tail_ms: int) -> tuple[str, float]:
    stream = asr.create_stream()
    t0 = time.monotonic()
    for start in range(0, len(pcm), 3200):
        asr.accept_pcm(stream, pcm[start:start + 3200])
        asr.decode_ready(stream)
    stream.accept_waveform(
        16000, np.zeros(int(tail_ms * 16), dtype=np.float32)
    )
    try:
        stream.input_finished()
    except Exception:
        pass
    asr.decode_ready(stream)
    text = asr.text(stream).strip()
    return text, (time.monotonic() - t0) * 1000


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("manifest", type=Path)
    p.add_argument("--output", type=Path, default=ROOT / "benchmark-results/streaming-tail-sweep.tsv")
    p.add_argument(
        "--tail-ms",
        default="100,200,350,500,700,1000",
        help="comma separated silence durations",
    )
    args = p.parse_args()
    tails = [int(v) for v in args.tail_ms.split(",")]

    samples = [
        (sid, wav, ref, read_pcm(wav))
        for sid, wav, ref in load_manifest(args.manifest)
    ]
    asr = SherpaRecognizer()
    rows = []

    for tail in tails:
        edits = chars = exact = 0
        compute_ms = 0.0
        per_sample = []
        for sid, _wav, ref, pcm in samples:
            text, ms = decode(asr, pcm, tail)
            e, n = content_error(ref, text)
            edits += e
            chars += n
            exact += int(e == 0)
            compute_ms += ms
            per_sample.append((sid, e, text))
        cer = edits / max(chars, 1)
        rows.append({
            "tail_ms": tail,
            "content_cer": cer,
            "exact_samples": exact,
            "samples": len(samples),
            "compute_ms": compute_ms,
        })
        print(
            f"tail={tail:4d}ms  CER={cer:.2%}  exact={exact}/{len(samples)} "
            f"compute={compute_ms/1000:.2f}s"
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=rows[0].keys(), delimiter="\t")
        w.writeheader()
        w.writerows(rows)

    best = min(rows, key=lambda r: (r["content_cer"], r["tail_ms"]))
    print(
        f"BEST tail={best['tail_ms']}ms CER={best['content_cer']:.2%} "
        f"exact={best['exact_samples']}/{best['samples']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
