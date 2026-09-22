#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
MODEL_NAME="sherpa-onnx-streaming-paraformer-bilingual-zh-en"
MODEL_DIR="$ROOT/models/$MODEL_NAME"
URL="https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/$MODEL_NAME.tar.bz2"

echo "[1/5] Checking system packages..."
APT_PACKAGES=(
  g++ fcitx5 libfcitx5core-dev libfcitx5utils-dev libfcitx5config-dev
  python3-pip python3-numpy python3-gi python3-cairo gir1.2-gtk-3.0
  pulseaudio-utils bzip2 curl xinput xdotool
)
missing_packages=()
for package in "${APT_PACKAGES[@]}"; do
  if ! dpkg-query -W -f='${Status}' "$package" 2>/dev/null \
      | grep -q '^install ok installed$'; then
    missing_packages+=("$package")
  fi
done
if ((${#missing_packages[@]})); then
  printf 'Installing missing packages: %s\n' "${missing_packages[*]}"
  sudo apt-get update
  sudo apt-get install -y "${missing_packages[@]}"
else
  echo "  All system packages are already installed; skipping apt."
fi

echo "[2/5] Checking sherpa-onnx..."
if python3 -c 'import sherpa_onnx' >/dev/null 2>&1; then
  echo "  sherpa-onnx is already installed; skipping pip."
else
  python3 -m pip install --user --break-system-packages sherpa-onnx \
    || python3 -m pip install --user sherpa-onnx
fi

echo "[3/5] Checking bilingual streaming model..."
mkdir -p "$ROOT/models"
if [ ! -f "$MODEL_DIR/tokens.txt" ] \
    || { [ ! -f "$MODEL_DIR/encoder.int8.onnx" ] && [ ! -f "$MODEL_DIR/encoder.onnx" ]; } \
    || { [ ! -f "$MODEL_DIR/decoder.int8.onnx" ] && [ ! -f "$MODEL_DIR/decoder.onnx" ]; }; then
  echo "  Streaming model is missing or incomplete; downloading it now."
  tmp="$(mktemp --suffix=.tar.bz2)"
  trap 'rm -f "$tmp"' EXIT
  curl -fL --retry 3 --retry-delay 2 -o "$tmp" "$URL"
  tar -xjf "$tmp" -C "$ROOT/models"
  rm -f "$tmp"
  trap - EXIT
else
  echo "  Streaming model is already installed; skipping download."
fi

test -f "$MODEL_DIR/tokens.txt"
test -f "$MODEL_DIR/encoder.int8.onnx" -o -f "$MODEL_DIR/encoder.onnx"
test -f "$MODEL_DIR/decoder.int8.onnx" -o -f "$MODEL_DIR/decoder.onnx"

echo "[4/5] Streaming model ready."

echo "[5/5] Installing final/punctuation quality models..."
bash "$ROOT/scripts/11-setup-quality.sh"

echo "Done."
echo "Next: bash scripts/10-install-service.sh"
