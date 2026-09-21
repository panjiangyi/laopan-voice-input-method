#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
# Optional sysroot for unpacked Ubuntu development packages (no sudo needed).
INCLUDE="${FCITX_DEV_ROOT:-/usr}/include/Fcitx5"
mkdir -p "$ROOT/build"
g++ -std=c++17 -O2 -Wall -Wextra -fPIC -shared \
    -I"$INCLUDE/Core" -I"$INCLUDE/Utils" -I"$INCLUDE/Config" \
    "$ROOT/native/voiceime.cpp" -o "$ROOT/build/libvoiceime.so" \
    -l:libFcitx5Core.so.7 -l:libFcitx5Utils.so.2
