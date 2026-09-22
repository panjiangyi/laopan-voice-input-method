#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
mkdir -p "$ROOT/models"

download_asr() {
  local name="$1"
  local dir="$ROOT/models/$name"
  local url="https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/$name.tar.bz2"
  if [ ! -f "$dir/model.int8.onnx" ] || [ ! -f "$dir/tokens.txt" ]; then
    echo "  $name is missing or incomplete; downloading it now."
    local tmp
    tmp="$(mktemp --suffix=.tar.bz2)"
    trap 'rm -f "$tmp"' RETURN
    curl -fL --retry 3 --retry-delay 2 -o "$tmp" "$url"
    tar -xjf "$tmp" -C "$ROOT/models"
    rm -f "$tmp"
    trap - RETURN
  else
    echo "  $name is already installed; skipping download."
  fi
}

FINAL_NAME="sherpa-onnx-paraformer-zh-2024-03-09"
PUNCT_NAME="sherpa-onnx-punct-ct-transformer-zh-en-vocab272727-2024-04-12-int8"
PUNCT_DIR="$ROOT/models/$PUNCT_NAME"

echo "[1/2] Installing fast offline Paraformer final model..."
download_asr "$FINAL_NAME"
test -f "$ROOT/models/$FINAL_NAME/model.int8.onnx"
test -f "$ROOT/models/$FINAL_NAME/tokens.txt"

echo "[2/2] Installing deterministic Chinese/English punctuation model..."
if [ ! -f "$PUNCT_DIR/model.int8.onnx" ]; then
  echo "  $PUNCT_NAME is missing or incomplete; downloading it now."
  tmp="$(mktemp --suffix=.tar.bz2)"
  trap 'rm -f "$tmp"' EXIT
  curl -fL --retry 3 --retry-delay 2 -o "$tmp"     "https://github.com/k2-fsa/sherpa-onnx/releases/download/punctuation-models/$PUNCT_NAME.tar.bz2"
  tar -xjf "$tmp" -C "$ROOT/models"
  rm -f "$tmp"
  trap - EXIT
else
  echo "  $PUNCT_NAME is already installed; skipping download."
fi
test -f "$PUNCT_DIR/model.int8.onnx"

echo "Quality models ready."
