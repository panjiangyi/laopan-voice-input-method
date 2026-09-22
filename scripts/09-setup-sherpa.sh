#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
MODEL_NAME="sherpa-onnx-streaming-paraformer-bilingual-zh-en"
MODEL_DIR="$ROOT/models/$MODEL_NAME"
URL="https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/$MODEL_NAME.tar.bz2"

echo "[1/4] Installing runtime packages..."
sudo apt-get update
sudo apt-get install -y python3-pip python3-numpy python3-gi pulseaudio-utils bzip2 curl xinput

echo "[2/4] Installing sherpa-onnx..."
python3 -m pip install --user --break-system-packages -U sherpa-onnx   || python3 -m pip install --user -U sherpa-onnx

echo "[3/4] Downloading production Paraformer..."
mkdir -p "$ROOT/models"
if [ ! -d "$MODEL_DIR" ]; then
  tmp="$(mktemp --suffix=.tar.bz2)"
  trap 'rm -f "$tmp"' EXIT
  curl -fL --retry 3 --retry-delay 2 -o "$tmp" "$URL"
  tar -xjf "$tmp" -C "$ROOT/models"
fi

test -f "$MODEL_DIR/tokens.txt"
test -f "$MODEL_DIR/encoder.int8.onnx" -o -f "$MODEL_DIR/encoder.onnx"
test -f "$MODEL_DIR/decoder.int8.onnx" -o -f "$MODEL_DIR/decoder.onnx"

echo "[4/4] Paraformer ready."

echo "Done."
echo "Production streaming backend: Paraformer"
echo "Experimental Zipformer hotword setup: bash scripts/21-setup-hotword-asr.sh"
echo "Next: bash scripts/10-install-service.sh"
