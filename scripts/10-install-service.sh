#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
mkdir -p "$UNIT_DIR"

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
Environment=VOICEIME_LLM_ENDPOINT=http://127.0.0.1:19888
Environment=VOICEIME_LLM_ENABLED=0
Environment=VOICEIME_LLM_MODE=punctuation
Environment=VOICEIME_LLM_TIMEOUT=2.0

[Install]
WantedBy=default.target
EOF

chmod +x "$ROOT/voiceime-engine" "$ROOT/voiceime-ptt" "$ROOT/voiceime-reset" "$ROOT/voiceime-mic"
systemctl --user daemon-reload
systemctl --user enable voiceime-ptt.service
# enable --now does not restart an already-running unit after Environment changes.
# restart both starts an inactive unit and refreshes an active one.
systemctl --user restart voiceime-ptt.service
sleep 1
"$ROOT/voiceime-status"
