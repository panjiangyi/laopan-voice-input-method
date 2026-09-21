#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
test -f "$ROOT/build/libvoiceime.so"
TARGET="${XDG_DATA_HOME:-$HOME/.local/share}/fcitx5/addon"
mkdir -p "$TARGET"
cat > "$TARGET/voiceime.conf" <<EOF
[Addon]
Name=VoiceIME native text input
Type=SharedLibrary
Library=$ROOT/build/libvoiceime
Category=Module
Version=0.1
OnDemand=False
EOF
echo "Installed $TARGET/voiceime.conf; restart Fcitx5 to load the addon."
