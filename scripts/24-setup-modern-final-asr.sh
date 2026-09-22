#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
MODELS="$ROOT/models"
mkdir -p "$MODELS"

download() {
  local name="$1"
  local dir="$MODELS/$name"
  local url="https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/$name.tar.bz2"
  if [ -d "$dir" ]; then
    echo "Already installed: $name"
    return
  fi
  local tmp
  tmp="$(mktemp --suffix=.tar.bz2)"
  echo "Downloading $name..."
  curl -fL --retry 3 --retry-delay 2 -o "$tmp" "$url"
  tar -xjf "$tmp" -C "$MODELS"
  rm -f "$tmp"
}

python3 -m pip install --user --break-system-packages -U sherpa-onnx numpy || python3 -m pip install --user -U sherpa-onnx numpy

QWEN="sherpa-onnx-qwen3-asr-0.6B-int8-2026-03-25"
FUN="sherpa-onnx-funasr-nano-int8-2025-12-30"

download "$QWEN"
download "$FUN"

test -f "$MODELS/$QWEN/conv_frontend.onnx"
test -f "$MODELS/$QWEN/encoder.int8.onnx"
test -f "$MODELS/$QWEN/decoder.int8.onnx"
test -d "$MODELS/$QWEN/tokenizer"

test -f "$MODELS/$FUN/encoder_adaptor.int8.onnx"
test -f "$MODELS/$FUN/llm.int8.onnx"
test -f "$MODELS/$FUN/embedding.int8.onnx"
test -d "$MODELS/$FUN/Qwen3-0.6B"

echo "Modern final ASR candidates installed."
