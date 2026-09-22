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

download_model "sherpa-onnx-qwen3-asr-0.6B-int8-2026-03-25"
download_model "sherpa-onnx-funasr-nano-int8-2025-12-30"

Q="$ROOT/models/sherpa-onnx-qwen3-asr-0.6B-int8-2026-03-25"
F="$ROOT/models/sherpa-onnx-funasr-nano-int8-2025-12-30"

test -f "$Q/conv_frontend.onnx"
test -f "$Q/encoder.int8.onnx"
test -f "$Q/decoder.int8.onnx"
test -d "$Q/tokenizer"

test -f "$F/encoder_adaptor.int8.onnx"
test -f "$F/llm.int8.onnx"
test -f "$F/embedding.int8.onnx"
test -d "$F/Qwen3-0.6B"

echo "Modern hotword final-pass candidates are ready."
