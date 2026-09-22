#!/usr/bin/env python3
"""A/B the official sherpa-onnx Chinese-number ITN FST on VoiceIME samples."""
from __future__ import annotations

import argparse
import csv
import gc
import runpy
import wave
from collections import Counter
from pathlib import Path
import sys

import numpy as np
import sherpa_onnx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from voiceime_glossary import GlossaryCorrector  # noqa: E402

METRIC = runpy.run_path(str(ROOT / "scripts/15-evaluate-samples.py"))
metrics = METRIC["metrics"]
pct = METRIC["pct"]
ENGINE = runpy.run_path(str(ROOT / "voiceime-engine"))
semantic_signature = ENGINE["LLMCorrector"]._semantic_signature

FINAL = ROOT / "models/sherpa-onnx-paraformer-zh-2024-03-09"
ITN = ROOT / "models/itn_zh_number.fst"
PUNCT = (
    ROOT / "models"
    / "sherpa-onnx-punct-ct-transformer-zh-en-vocab272727-2024-04-12-int8"
    / "model.int8.onnx"
)
SAMPLE_RATE = 16000


def samples(manifest: Path):
    with manifest.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            wav = manifest.parent / Path(row["wav"]).name
            ref = (row.get("actual_text") or row.get("target_text") or "").strip()
            with wave.open(str(wav), "rb") as wf:
                pcm = wf.readframes(wf.getnframes())
            audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
            yield row["id"], ref, audio


def recognizer(rule_fsts: str = ""):
    return sherpa_onnx.OfflineRecognizer.from_paraformer(
        paraformer=str(FINAL / "model.int8.onnx"),
        tokens=str(FINAL / "tokens.txt"),
        num_threads=4,
        rule_fsts=rule_fsts,
    )


def punctuation():
    cfg = sherpa_onnx.OfflinePunctuationConfig(
        model=sherpa_onnx.OfflinePunctuationModelConfig(
            ct_transformer=str(PUNCT), num_threads=1, provider="cpu"
        )
    )
    return sherpa_onnx.OfflinePunctuation(cfg)


def decode(rec, audio):
    stream = rec.create_stream()
    stream.accept_waveform(SAMPLE_RATE, audio)
    rec.decode_stream(stream)
    result = stream.result
    return (result.text if hasattr(result, "text") else str(result)).strip()


def summarize(rows):
    sums = Counter()
    for row in rows:
        m = row["metrics"]
        for key in (
            "content_edits", "content_chars", "cjk_edits", "cjk_chars",
            "english_hits", "english_total", "number_hits", "number_total",
            "code_hits", "code_total", "punct_edits", "punct_count",
        ):
            sums[key] += m[key]

    def rate(a, b):
        return sums[a] / sums[b] if sums[b] else None

    return {
        "content_cer": rate("content_edits", "content_chars"),
        "cjk_cer": rate("cjk_edits", "cjk_chars"),
        "english_recall": rate("english_hits", "english_total"),
        "number_recall": rate("number_hits", "number_total"),
        "code_recall": rate("code_hits", "code_total"),
        "punct_error": rate("punct_edits", "punct_count"),
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("manifest", type=Path)
    p.add_argument("--output-dir", type=Path, default=ROOT / "benchmark-results-itn")
    args = p.parse_args()
    if not ITN.is_file():
        raise SystemExit(f"missing {ITN}")

    data = list(samples(args.manifest))
    glossary = GlossaryCorrector()
    punct = punctuation()
    rec = recognizer(str(ITN))
    rows = []

    for sid, ref, audio in data:
        raw = decode(rec, audio)
        gloss = glossary.correct(raw)
        candidate = punct.add_punctuation(gloss).strip()
        final = (
            candidate
            if candidate and semantic_signature(gloss) == semantic_signature(candidate)
            else gloss
        )
        m = metrics(ref, final)
        rows.append({
            "id": sid,
            "reference": ref,
            "itn_raw": raw,
            "itn_final": final,
            "metrics": m,
        })
        print(
            f"{sid}: CER={pct(m['content_cer'])} "
            f"NUM={pct(m['number_recall'])} CODE={pct(m['code_recall'])}  {final}"
        )

    del rec
    gc.collect()
    sm = summarize(rows)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    with (args.output_dir / "results.tsv").open("w", encoding="utf-8", newline="") as fh:
        fields = [
            "id", "reference", "itn_raw", "itn_final",
            "content_cer", "cjk_cer", "english_recall",
            "number_recall", "code_recall", "punct_error_rate",
        ]
        w = csv.DictWriter(fh, fieldnames=fields, delimiter="\t")
        w.writeheader()
        for row in rows:
            m = row["metrics"]
            w.writerow({
                "id": row["id"], "reference": row["reference"],
                "itn_raw": row["itn_raw"], "itn_final": row["itn_final"],
                "content_cer": m["content_cer"], "cjk_cer": m["cjk_cer"],
                "english_recall": m["english_recall"],
                "number_recall": m["number_recall"],
                "code_recall": m["code_recall"],
                "punct_error_rate": m["punct_error_rate"],
            })

    fmt = lambda v: "n/a" if v is None else f"{v:.2%}"
    report = [
        "# Chinese number ITN A/B",
        "",
        "Official sherpa-onnx itn_zh_number.fst applied inside offline Paraformer.",
        "",
        "| Pipeline | Content CER | Chinese CER | English recall | Number recall | Code recall | Punctuation error |",
        "|---|---:|---:|---:|---:|---:|---:|",
        f"| ITN + glossary + punctuation | {fmt(sm['content_cer'])} | "
        f"{fmt(sm['cjk_cer'])} | {fmt(sm['english_recall'])} | "
        f"{fmt(sm['number_recall'])} | {fmt(sm['code_recall'])} | "
        f"{fmt(sm['punct_error'])} |",
        "",
        "No-ITN raw offline baseline from the same corpus: 9.61% content CER, "
        "5.14% Chinese CER, 60.98% English recall, 0% number recall, 40% code recall.",
    ]
    (args.output_dir / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print("\n" + "\n".join(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
