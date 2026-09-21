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

test -f "$ROOT/models/sherpa-onnx-paraformer-zh-2024-03-09/model.int8.onnx"
test -f "$ROOT/models/sherpa-onnx-paraformer-zh-2024-03-09/tokens.txt"
test -f "$ROOT/models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/model.int8.onnx"
test -f "$ROOT/models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/tokens.txt"
