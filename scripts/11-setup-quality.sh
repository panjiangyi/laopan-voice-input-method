#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
NAME="sherpa-onnx-fire-red-asr2-ctc-zh_en-int8-2026-02-25"
DIR="$ROOT/models/$NAME"
URL="https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/$NAME.tar.bz2"

echo "Installing optional high-accuracy final recognizer..."
mkdir -p "$ROOT/models"
if [ ! -d "$DIR" ]; then
  tmp="$(mktemp --suffix=.tar.bz2)"
  trap 'rm -f "$tmp"' EXIT
  curl -fL --retry 3 --retry-delay 2 -o "$tmp" "$URL"
  tar -xjf "$tmp" -C "$ROOT/models"
fi
test -f "$DIR/model.int8.onnx"
test -f "$DIR/tokens.txt"
echo "Installed: $DIR"
echo "Restarting VoiceIME..."
systemctl --user restart voiceime-ptt.service || true
