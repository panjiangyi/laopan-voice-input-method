#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
mkdir -p "$UNIT_DIR"

LLM_ENABLED="${VOICEIME_LLM_ENABLED:-1}"
LLM_MODE="${VOICEIME_LLM_MODE:-punctuation}"
LLM_TIMEOUT="${VOICEIME_LLM_TIMEOUT:-15.0}"
DEEPSEEK_MODEL="${DEEPSEEK_MODEL:-deepseek-v4-flash}"

cat > "$UNIT_DIR/voiceime-ptt.service" <<EOF
[Unit]
Description=VoiceIME push-to-talk daemon
After=graphical-session.target
PartOf=graphical-session.target

[Service]
Type=simple
WorkingDirectory=$ROOT
ExecStart=$ROOT/voiceime-ptt
ExecStopPost=$ROOT/voiceime-reset --keep-service
Restart=on-failure
RestartSec=1
Environment=PYTHONUNBUFFERED=1
Environment=VOICEIME_ENGINE=sherpa
Environment=VOICEIME_FINAL_ENABLED=0
Environment=VOICEIME_LLM_ENABLED=$LLM_ENABLED
Environment=VOICEIME_LLM_MODE=$LLM_MODE
Environment=VOICEIME_LLM_TIMEOUT=$LLM_TIMEOUT
Environment=DEEPSEEK_MODEL=$DEEPSEEK_MODEL

[Install]
WantedBy=default.target
EOF

cat > "$UNIT_DIR/voiceime-overlay.service" <<EOF
[Unit]
Description=VoiceIME on-screen recording indicator
After=graphical-session.target voiceime-ptt.service
PartOf=voiceime-ptt.service

[Service]
Type=simple
WorkingDirectory=$ROOT
ExecStart=/usr/bin/python3 $ROOT/voiceime-overlay
Restart=on-failure
RestartSec=1
Environment=PYTHONUNBUFFERED=1
Environment=DISPLAY=${DISPLAY:-:1}

[Install]
WantedBy=default.target
EOF

chmod +x "$ROOT/voiceime-engine" "$ROOT/voiceime-ptt" "$ROOT/voiceime-reset" "$ROOT/voiceime-mic" "$ROOT/voiceime-overlay"
systemctl --user daemon-reload
systemctl --user enable voiceime-ptt.service
systemctl --user enable voiceime-overlay.service
# enable --now does not restart an already-running unit after Environment changes.
# restart both starts an inactive unit and refreshes an active one.
systemctl --user restart voiceime-ptt.service
systemctl --user restart voiceime-overlay.service
sleep 1
"$ROOT/voiceime-status"
