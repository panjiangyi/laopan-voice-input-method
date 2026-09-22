#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
MODEL_NAME="sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20"
MODEL_DIR="$ROOT/models/$MODEL_NAME"
URL="https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/$MODEL_NAME.tar.bz2"
HOTWORDS="$ROOT/hotwords/compiled.txt"

echo "[1/5] Installing hotword ASR runtime..."
python3 -m pip install --user --break-system-packages -U sherpa-onnx sentencepiece   || python3 -m pip install --user -U sherpa-onnx sentencepiece

echo "[2/5] Downloading bilingual streaming Zipformer..."
mkdir -p "$ROOT/models"
if [ ! -d "$MODEL_DIR" ]; then
  tmp="$(mktemp --suffix=.tar.bz2)"
  trap 'rm -f "$tmp"' EXIT
  curl -fL --retry 3 --retry-delay 2 -o "$tmp" "$URL"
  tar -xjf "$tmp" -C "$ROOT/models"
fi

encoder="$MODEL_DIR/encoder-epoch-99-avg-1.int8.onnx"
decoder="$MODEL_DIR/decoder-epoch-99-avg-1.onnx"
joiner="$MODEL_DIR/joiner-epoch-99-avg-1.int8.onnx"
tokens="$MODEL_DIR/tokens.txt"
bpe_model="$MODEL_DIR/bpe.model"
bpe_vocab="$MODEL_DIR/bpe.vocab"

for f in "$encoder" "$decoder" "$joiner" "$tokens"; do
  test -f "$f" || { echo "missing model file: $f" >&2; exit 1; }
done

echo "[3/5] Preparing BPE vocabulary..."
if [ ! -f "$bpe_vocab" ]; then
  test -f "$bpe_model" || {
    echo "model package is missing bpe.model; cannot encode English hotwords safely" >&2
    exit 1
  }
  python3 - "$bpe_model" "$bpe_vocab" <<'PY'
import sentencepiece as spm
import sys

model, output = sys.argv[1:3]
sp = spm.SentencePieceProcessor(model_file=model)
with open(output, "w", encoding="utf-8") as f:
    for i in range(sp.get_piece_size()):
        f.write(f"{sp.id_to_piece(i)}\t{sp.get_score(i)}\n")
print(f"wrote {sp.get_piece_size()} BPE entries to {output}")
PY
fi

echo "[4/5] Building merged VoiceIME hotwords..."
mkdir -p "$ROOT/hotwords"
python3 "$ROOT/scripts/20-build-glossary.py" -o "$HOTWORDS"
test -s "$HOTWORDS"

echo "[5/5] Validating hotword recognizer initialization..."
VOICEIME_HOTWORD_MODEL="$MODEL_DIR" VOICEIME_HOTWORDS_FILE="$HOTWORDS" python3 - "$ROOT" <<'PY'
import os
import sys
from pathlib import Path
import sherpa_onnx

root = Path(sys.argv[1])
model = Path(os.environ["VOICEIME_HOTWORD_MODEL"])
hotwords = Path(os.environ["VOICEIME_HOTWORDS_FILE"])
recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
    tokens=str(model / "tokens.txt"),
    encoder=str(model / "encoder-epoch-99-avg-1.int8.onnx"),
    decoder=str(model / "decoder-epoch-99-avg-1.onnx"),
    joiner=str(model / "joiner-epoch-99-avg-1.int8.onnx"),
    num_threads=2,
    sample_rate=16000,
    feature_dim=80,
    decoding_method="modified_beam_search",
    max_active_paths=4,
    hotwords_file=str(hotwords),
    hotwords_score=1.5,
    modeling_unit="bpe",
    bpe_vocab=str(model / "bpe.vocab"),
    enable_endpoint_detection=False,
)
stream = recognizer.create_stream()
assert stream is not None
print(f"validated {hotwords} with bilingual Zipformer")
PY

echo "Hotword ASR ready: $MODEL_DIR"
echo "Merged hotwords: $HOTWORDS"
