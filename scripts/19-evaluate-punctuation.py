#!/usr/bin/env python3
"""Evaluate deterministic punctuation restoration on real ASR outputs."""
from __future__ import annotations

import argparse
import csv
import runpy
import time
from pathlib import Path

import sherpa_onnx

ROOT = Path(__file__).resolve().parents[1]
BENCH = runpy.run_path(str(ROOT / "scripts/15-evaluate-samples.py"))
punctuation_error = BENCH["punctuation_error"]
normalize_content = BENCH["normalize_content"]
pct = BENCH["pct"]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("results_tsv", type=Path)
    p.add_argument("--output", type=Path, default=ROOT / "benchmark-results/punctuation.tsv")
    args = p.parse_args()

    model = (
        ROOT
        / "models"
        / "sherpa-onnx-punct-ct-transformer-zh-en-vocab272727-2024-04-12-int8"
        / "model.int8.onnx"
    )
    cfg = sherpa_onnx.OfflinePunctuationConfig(
        model=sherpa_onnx.OfflinePunctuationModelConfig(
            ct_transformer=str(model),
            num_threads=1,
            provider="cpu",
        )
    )
    restorer = sherpa_onnx.OfflinePunctuation(cfg)

    rows = []
    totals = {
        "streaming_before_e": 0, "streaming_before_n": 0,
        "streaming_after_e": 0, "streaming_after_n": 0,
        "hybrid_before_e": 0, "hybrid_before_n": 0,
        "hybrid_after_e": 0, "hybrid_after_n": 0,
        "semantic_mutations": 0,
        "elapsed_ms": 0.0,
    }

    with args.results_tsv.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            ref = row["reference"]
            out = {"id": row["id"], "reference": ref}
            for key in ("streaming", "hybrid"):
                source = row[f"{key}_text"]
                be, bn = punctuation_error(ref, source)
                t0 = time.monotonic()
                restored = restorer.add_punctuation(source)
                elapsed = (time.monotonic() - t0) * 1000
                ae, an = punctuation_error(ref, restored)

                safe = normalize_content(source) == normalize_content(restored)
                if not safe:
                    totals["semantic_mutations"] += 1

                totals[f"{key}_before_e"] += be
                totals[f"{key}_before_n"] += bn
                totals[f"{key}_after_e"] += ae
                totals[f"{key}_after_n"] += an
                totals["elapsed_ms"] += elapsed

                out[f"{key}_source"] = source
                out[f"{key}_punctuated"] = restored
                out[f"{key}_safe"] = "1" if safe else "0"
                out[f"{key}_before_error"] = be / max(bn, 1)
                out[f"{key}_after_error"] = ae / max(an, 1)
                out[f"{key}_elapsed_ms"] = elapsed
            rows.append(out)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "id", "reference",
        "streaming_source", "streaming_punctuated", "streaming_safe",
        "streaming_before_error", "streaming_after_error", "streaming_elapsed_ms",
        "hybrid_source", "hybrid_punctuated", "hybrid_safe",
        "hybrid_before_error", "hybrid_after_error", "hybrid_elapsed_ms",
    ]
    with args.output.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, delimiter="\t")
        w.writeheader()
        w.writerows(rows)

    def rr(prefix: str, stage: str):
        return totals[f"{prefix}_{stage}_e"] / max(totals[f"{prefix}_{stage}_n"], 1)

    print("=== PUNCTUATION SUMMARY ===")
    print(
        f"streaming: {pct(rr('streaming','before'))} -> "
        f"{pct(rr('streaming','after'))}"
    )
    print(
        f"hybrid:    {pct(rr('hybrid','before'))} -> "
        f"{pct(rr('hybrid','after'))}"
    )
    print(
        f"semantic mutations: {totals['semantic_mutations']} "
        f"(runtime must reject any such candidate)"
    )
    print(f"total punctuation compute: {totals['elapsed_ms']:.1f} ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
