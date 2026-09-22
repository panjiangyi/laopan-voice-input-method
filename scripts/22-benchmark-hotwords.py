#!/usr/bin/env python3
"""A/B current Paraformer vs bilingual Zipformer contextual hotwords.

Uses the real sample manifest recorded by the user and reports:
- content CER
- Chinese-only CER
- English token recall
- domain-hotword phrase recall
- compute real-time factor (RTF)

The benchmark intentionally does not use FireRed or LLM correction so it
measures the streaming decoder itself.
"""
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
PARAFORMER = ROOT / "models" / "sherpa-onnx-streaming-paraformer-bilingual-zh-en"
ZIPFORMER = ROOT / "models" / "sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20"
HOTWORDS = ROOT / "hotwords" / "compiled.txt"
SAMPLE_RATE = 16000
TAIL_SEC = 1.0

ENGLISH_RE = re.compile(
    r"[A-Za-z][A-Za-z0-9]*(?:[._+:/-][A-Za-z0-9+._:/-]+)*"
)
COSMETIC = set("，。！？；：“”‘’（）《》〈〉")


def is_cjk(ch: str) -> bool:
    cp = ord(ch)
    return (
        0x3400 <= cp <= 0x4DBF
        or 0x4E00 <= cp <= 0x9FFF
        or 0xF900 <= cp <= 0xFAFF
    )


def _ascii_alnum(ch: str) -> bool:
    return bool(ch) and ch.isascii() and ch.isalnum()


def normalize_content(text: str) -> str:
    """Drop presentation punctuation/spacing but preserve code/number symbols."""
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
        p = prev_nonspace(i)
        n = next_nonspace(i)
        if ch.isspace():
            # Spaces between ASCII words can be semantic; CJK<->ASCII spacing
            # is presentation.
            if (is_cjk(p) and _ascii_alnum(n)) or (_ascii_alnum(p) and is_cjk(n)):
                continue
            out.append(" ")
            continue
        if ch in COSMETIC:
            continue
        if ch in ",!?;:()[]{}":
            if _ascii_alnum(p) and _ascii_alnum(n):
                out.append(ch)
            continue
        if ch == ".":
            # Decimal/version dots are semantic; sentence periods are not.
            if _ascii_alnum(p) and _ascii_alnum(n):
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


def token_recall(ref: str, hyp: str) -> tuple[int, int]:
    expected = Counter(t.casefold() for t in ENGLISH_RE.findall(ref))
    got = Counter(t.casefold() for t in ENGLISH_RE.findall(hyp))
    hits = sum(min(count, got[token]) for token, count in expected.items())
    return hits, sum(expected.values())


def read_hotwords() -> list[str]:
    terms = []
    for raw in HOTWORDS.read_text(encoding="utf-8").splitlines():
        term = raw.strip()
        if term and not term.startswith("#") and re.search(r"[A-Za-z]", term):
            terms.append(term)
    # Long phrases first so "GitHub Actions" is measured as a phrase rather
    # than only as "GitHub".
    return sorted(set(terms), key=lambda x: (-len(x), x.casefold()))


def phrase_recall(ref: str, hyp: str, terms: list[str]) -> tuple[int, int, list[str]]:
    r = ref.casefold()
    h = hyp.casefold()
    present = [term for term in terms if term.casefold() in r]
    hits = sum(term.casefold() in h for term in present)
    return hits, len(present), present


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
    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    return samples, n / SAMPLE_RATE


def decode(recognizer, samples: np.ndarray) -> str:
    stream = recognizer.create_stream()
    chunk = int(SAMPLE_RATE * 0.08)
    for i in range(0, len(samples), chunk):
        stream.accept_waveform(SAMPLE_RATE, samples[i:i + chunk])
        while recognizer.is_ready(stream):
            recognizer.decode_stream(stream)
    stream.accept_waveform(
        SAMPLE_RATE, np.zeros(int(TAIL_SEC * SAMPLE_RATE), dtype=np.float32)
    )
    try:
        stream.input_finished()
    except Exception:
        pass
    while recognizer.is_ready(stream):
        recognizer.decode_stream(stream)
    result = recognizer.get_result(stream)
    return (result.text if hasattr(result, "text") else str(result)).strip()


def pick(directory: Path, *names: str) -> str:
    for name in names:
        p = directory / name
        if p.exists():
            return str(p)
    raise FileNotFoundError(f"missing {names} in {directory}")


def make_paraformer():
    return sherpa_onnx.OnlineRecognizer.from_paraformer(
        tokens=pick(PARAFORMER, "tokens.txt"),
        encoder=pick(PARAFORMER, "encoder.int8.onnx", "encoder.onnx"),
        decoder=pick(PARAFORMER, "decoder.int8.onnx", "decoder.onnx"),
        num_threads=2,
        sample_rate=SAMPLE_RATE,
        feature_dim=80,
        decoding_method="greedy_search",
        enable_endpoint_detection=False,
    )


def make_zipformer(score: float | None):
    kwargs = dict(
        tokens=pick(ZIPFORMER, "tokens.txt"),
        encoder=pick(
            ZIPFORMER,
            "encoder-epoch-99-avg-1.int8.onnx",
            "encoder-epoch-99-avg-1.onnx",
        ),
        decoder=pick(
            ZIPFORMER,
            "decoder-epoch-99-avg-1.onnx",
            "decoder-epoch-99-avg-1.int8.onnx",
        ),
        joiner=pick(
            ZIPFORMER,
            "joiner-epoch-99-avg-1.int8.onnx",
            "joiner-epoch-99-avg-1.onnx",
        ),
        num_threads=2,
        sample_rate=SAMPLE_RATE,
        feature_dim=80,
        decoding_method="modified_beam_search",
        max_active_paths=4,
        enable_endpoint_detection=False,
    )
    if score is not None:
        kwargs.update(
            hotwords_file=str(HOTWORDS),
            hotwords_score=score,
            modeling_unit="bpe",
            bpe_vocab=pick(ZIPFORMER, "bpe.vocab"),
        )
    return sherpa_onnx.OnlineRecognizer.from_transducer(**kwargs)


def evaluate(name: str, recognizer, samples, terms):
    sums = Counter()
    rows = []
    started = time.monotonic()
    for sid, _wav, ref, audio, duration in samples:
        t0 = time.monotonic()
        hyp = decode(recognizer, audio)
        elapsed = time.monotonic() - t0

        ce, cn = content_pair(ref, hyp)
        ze, zn = cjk_pair(ref, hyp)
        eh, en = token_recall(ref, hyp)
        hh, hn, matched_terms = phrase_recall(ref, hyp, terms)
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
            "reference_hotwords": " | ".join(matched_terms),
            "elapsed_ms": elapsed * 1000,
        })
        print(f"{name} {sid}: CER={ce/max(cn,1):.2%} EN={eh}/{en} HW={hh}/{hn}")
        print(f"  REF: {ref}")
        print(f"  HYP: {hyp}")

    def rate(a, b):
        return a / b if b else None

    summary = {
        "model": name,
        "content_cer": rate(sums["content_edits"], sums["content_chars"]),
        "cjk_cer": rate(sums["cjk_edits"], sums["cjk_chars"]),
        "english_recall": rate(sums["english_hits"], sums["english_total"]),
        "hotword_recall": rate(sums["hotword_hits"], sums["hotword_total"]),
        "rtf": sums["compute_ms"] / max(sums["audio_ms"], 1),
        "wall_seconds": time.monotonic() - started,
        **dict(sums),
    }
    return summary, rows


def fmt(v):
    return "n/a" if v is None else f"{v:.2%}"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("manifest", type=Path)
    p.add_argument("--output-dir", type=Path, default=ROOT / "benchmark-results")
    p.add_argument("--scores", default="0.8,1.2,1.5,2.0,2.5")
    args = p.parse_args()

    terms = read_hotwords()
    samples = []
    for sid, wav, ref in load_manifest(args.manifest):
        audio, duration = read_wav(wav)
        samples.append((sid, wav, ref, audio, duration))

    configs = [("paraformer-current", make_paraformer)]
    configs.append(("zipformer-no-hotwords", lambda: make_zipformer(None)))
    for value in [float(x) for x in args.scores.split(",") if x.strip()]:
        configs.append((f"zipformer-hotwords-{value:g}", lambda v=value: make_zipformer(v)))

    summaries = []
    all_rows = []
    for name, factory in configs:
        print(f"\n===== {name} =====")
        recognizer = factory()
        summary, rows = evaluate(name, recognizer, samples, terms)
        summaries.append(summary)
        all_rows.extend(rows)
        del recognizer

    args.output_dir.mkdir(parents=True, exist_ok=True)
    summary_fields = [
        "model", "content_cer", "cjk_cer", "english_recall",
        "hotword_recall", "rtf", "wall_seconds",
    ]
    with (args.output_dir / "hotword-summary.tsv").open(
        "w", encoding="utf-8", newline=""
    ) as fh:
        w = csv.DictWriter(fh, fieldnames=summary_fields, delimiter="\t")
        w.writeheader()
        for row in summaries:
            w.writerow({key: row.get(key) for key in summary_fields})

    result_fields = [
        "model", "id", "reference", "hypothesis", "content_cer", "cjk_cer",
        "english_hits", "english_total", "hotword_hits", "hotword_total",
        "reference_hotwords", "elapsed_ms",
    ]
    with (args.output_dir / "hotword-results.tsv").open(
        "w", encoding="utf-8", newline=""
    ) as fh:
        w = csv.DictWriter(fh, fieldnames=result_fields, delimiter="\t")
        w.writeheader()
        w.writerows(all_rows)

    baseline = summaries[0]
    # Guardrail: candidate must not regress Chinese by >2 absolute points or
    # total content CER by >1 absolute point. Within the guardrail, maximize
    # domain hotword recall, then English recall, then minimize total CER/RTF.
    candidates = [
        row for row in summaries[1:]
        if row["model"].startswith("zipformer-hotwords-")
        and row["cjk_cer"] <= baseline["cjk_cer"] + 0.02
        and row["content_cer"] <= baseline["content_cer"] + 0.01
    ]
    winner = None
    if candidates:
        winner = min(
            candidates,
            key=lambda row: (
                -(row["hotword_recall"] or 0),
                -(row["english_recall"] or 0),
                row["content_cer"],
                row["rtf"],
            ),
        )

    report = [
        "# Mixed Chinese-English hotword benchmark",
        "",
        "| Decoder | Content CER | Chinese CER | English recall | Hotword recall | RTF |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in summaries:
        report.append(
            f"| {row['model']} | {fmt(row['content_cer'])} | "
            f"{fmt(row['cjk_cer'])} | {fmt(row['english_recall'])} | "
            f"{fmt(row['hotword_recall'])} | {row['rtf']:.3f} |"
        )
    report += ["", "## Automatic guardrail decision", ""]
    if winner:
        report.append(
            f"Selected **{winner['model']}**: it satisfies the Chinese/content "
            "regression guardrails and has the best domain-term recall."
        )
    else:
        report.append(
            "No hotword candidate satisfies the regression guardrails; keep "
            "Paraformer as the production default and do not trade Chinese "
            "accuracy for English bias."
        )
    (args.output_dir / "hotword-report.md").write_text(
        "\n".join(report) + "\n", encoding="utf-8"
    )
    print("\n" + "\n".join(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
