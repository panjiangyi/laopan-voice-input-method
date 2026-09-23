#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
MODEL=sherpa-onnx-qwen3-asr-0.6B-int8-2026-03-25
python3 -c 'import sherpa_onnx; assert hasattr(sherpa_onnx.OfflineRecognizer, "from_qwen3_asr"), "Upgrade sherpa-onnx to a version with Qwen3-ASR support"'
if [[ -f "$ROOT/models/$MODEL/.complete" ]]; then
  echo "Qwen3-ASR already installed."
  exit 0
fi
mkdir -p "$ROOT/models"
stage="$(mktemp -d "$ROOT/models/.qwen3-download.XXXXXX")"
trap 'rm -rf "$stage"' EXIT
curl -fL --retry 3 --connect-timeout 20 \
  -o "$stage/model.tar.bz2" \
  "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/$MODEL.tar.bz2"
tar -xjf "$stage/model.tar.bz2" -C "$stage"
for name in conv_frontend.onnx encoder.int8.onnx decoder.int8.onnx tokenizer/vocab.json tokenizer/merges.txt tokenizer/tokenizer_config.json; do
  test -s "$stage/$MODEL/$name"
done
mkdir -p "$ROOT/models/$MODEL"
cp -a "$stage/$MODEL/." "$ROOT/models/$MODEL/"
touch "$ROOT/models/$MODEL/.complete"
echo "Installed Qwen3-ASR. Benchmark before enabling VOICEIME_FINAL_BACKEND=qwen3."
