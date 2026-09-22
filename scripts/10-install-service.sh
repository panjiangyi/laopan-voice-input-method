#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
mkdir -p "$UNIT_DIR"

LLM_ENABLED="${VOICEIME_LLM_ENABLED:-0}"
LLM_MODE="${VOICEIME_LLM_MODE:-punctuation}"
LLM_TIMEOUT="${VOICEIME_LLM_TIMEOUT:-15.0}"
DEEPSEEK_MODEL="${DEEPSEEK_MODEL:-deepseek-v4-flash}"
ASR_BACKEND="${VOICEIME_ASR_BACKEND:-paraformer}"
HOTWORDS_SCORE="${VOICEIME_HOTWORDS_SCORE:-1.5}"
OUTPUT_MODE="${VOICEIME_OUTPUT_MODE:-preedit}"
FINAL_ENABLED="${VOICEIME_FINAL_ENABLED:-1}"
FINAL_MAX_WAIT="${VOICEIME_FINAL_MAX_WAIT:-0.8}"
PUNCTUATION_ENABLED="${VOICEIME_PUNCTUATION_ENABLED:-1}"
# Late-refinement rewrite is currently broken on this host (delete /
# append leaves the streaming text in place and appends the LLM fix
# after it). Default to disabled so the streaming ASR text already
# committed to the IC is what the user sees. Set
# VOICEIME_LLM_DISABLED=0 to re-enable once a working rewrite path
# is shipped.
LLM_DISABLED="${VOICEIME_LLM_DISABLED:-1}"

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
Environment=VOICEIME_ASR_BACKEND=$ASR_BACKEND
Environment=VOICEIME_HOTWORDS_SCORE=$HOTWORDS_SCORE
Environment=VOICEIME_HOTWORDS_FILE=$ROOT/hotwords/compiled.txt
Environment=VOICEIME_OUTPUT_MODE=$OUTPUT_MODE
Environment=VOICEIME_FINAL_ENABLED=$FINAL_ENABLED
Environment=VOICEIME_FINAL_MAX_WAIT=$FINAL_MAX_WAIT
Environment=VOICEIME_PUNCTUATION_ENABLED=$PUNCTUATION_ENABLED
Environment=VOICEIME_LLM_ENABLED=$LLM_ENABLED
Environment=VOICEIME_LLM_DISABLED=$LLM_DISABLED
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

chmod +x "$ROOT/voiceime-engine" "$ROOT/voiceime-ptt" "$ROOT/voiceime-reset" "$ROOT/voiceime-mic" "$ROOT/voiceime-overlay" "$ROOT/voiceime-hotwords"
systemctl --user daemon-reload
systemctl --user enable voiceime-ptt.service
systemctl --user enable voiceime-overlay.service
# enable --now does not restart an already-running unit after Environment changes.
# restart both starts an inactive unit and refreshes an active one.
systemctl --user restart voiceime-ptt.service
systemctl --user restart voiceime-overlay.service
sleep 1
"$ROOT/voiceime-status"
