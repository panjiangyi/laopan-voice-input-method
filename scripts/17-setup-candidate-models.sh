#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
mkdir -p "$ROOT/models"

download_model() {
  local name="$1"
  local dir="$ROOT/models/$name"
  local url="https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/$name.tar.bz2"
  if [ -d "$dir" ]; then
    echo "Already installed: $name"
    return
  fi
  local tmp
  tmp="$(mktemp --suffix=.tar.bz2)"
  trap 'rm -f "$tmp"' RETURN
  echo "Downloading $name..."
  curl -fL --retry 3 --retry-delay 2 -o "$tmp" "$url"
  tar -xjf "$tmp" -C "$ROOT/models"
  rm -f "$tmp"
  trap - RETURN
}

download_model "sherpa-onnx-paraformer-zh-2024-03-09"
download_model "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17"
download_model "sherpa-onnx-zipformer-zh-en-2023-11-22"

test -f "$ROOT/models/sherpa-onnx-paraformer-zh-2024-03-09/model.int8.onnx"
test -f "$ROOT/models/sherpa-onnx-paraformer-zh-2024-03-09/tokens.txt"
test -f "$ROOT/models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/model.int8.onnx"
test -f "$ROOT/models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/tokens.txt"

test -f "$ROOT/models/sherpa-onnx-zipformer-zh-en-2023-11-22/encoder-epoch-34-avg-19.onnx"
test -f "$ROOT/models/sherpa-onnx-zipformer-zh-en-2023-11-22/decoder-epoch-34-avg-19.onnx"
test -f "$ROOT/models/sherpa-onnx-zipformer-zh-en-2023-11-22/joiner-epoch-34-avg-19.onnx"
test -f "$ROOT/models/sherpa-onnx-zipformer-zh-en-2023-11-22/tokens.txt"

PUNCT_NAME="sherpa-onnx-punct-ct-transformer-zh-en-vocab272727-2024-04-12-int8"
PUNCT_DIR="$ROOT/models/$PUNCT_NAME"
if [ ! -d "$PUNCT_DIR" ]; then
  tmp="$(mktemp --suffix=.tar.bz2)"
  curl -fL --retry 3 --retry-delay 2 -o "$tmp"     "https://github.com/k2-fsa/sherpa-onnx/releases/download/punctuation-models/$PUNCT_NAME.tar.bz2"
  tar -xjf "$tmp" -C "$ROOT/models"
  rm -f "$tmp"
fi
test -f "$PUNCT_DIR/model.int8.onnx"
