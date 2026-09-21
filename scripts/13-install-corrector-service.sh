#!/usr/bin/env bash
# 13-install-corrector-service.sh — install the voiceime-corrector systemd
# user unit. The corrector is a thin wrapper that calls `opencode run` for
# each utterance. There is no venv, no local model, no API key needed
# (opencode handles provider auth via its own credentials store).
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
mkdir -p "$UNIT_DIR"
MODEL="${VOICEIME_CORRECTOR_MODEL:-opencode/muse-spark-1.3-contributor-free}"
VARIANT="${VOICEIME_CORRECTOR_VARIANT:-xhigh}"

# Locate the opencode binary so the unit file uses an absolute path and
# doesn't depend on the user's PATH after a non-login session starts.
OPENCODE_BIN="$(command -v opencode || true)"
if [ -z "$OPENCODE_BIN" ] && [ -x "$HOME/.opencode/bin/opencode" ]; then
  OPENCODE_BIN="$HOME/.opencode/bin/opencode"
fi
if [ -z "$OPENCODE_BIN" ]; then
  printf 'ERROR: opencode CLI not found.\n' >&2
  printf 'Install from https://opencode.ai/ then re-run this script.\n' >&2
  exit 1
fi
printf 'opencode found at %s\n' "$OPENCODE_BIN"

# Quick auth check so a not-logged-in user finds out before the systemd
# unit starts looping restarts.
if ! "$OPENCODE_BIN" models >/dev/null 2>&1; then
  printf 'WARNING: opencode cannot list models (auth missing?).\n' >&2
  printf 'Run:  %s providers   to log in.\n' "$OPENCODE_BIN" >&2
fi

cat > "$UNIT_DIR/voiceime-corrector.service" <<EOF
[Unit]
Description=VoiceIME AI text corrector
After=default.target
PartOf=graphical-session.target

[Service]
Type=simple
WorkingDirectory=$ROOT
ExecStart=/usr/bin/python3 $ROOT/voiceime-corrector
Restart=on-failure
RestartSec=2
Environment=PYTHONUNBUFFERED=1
Environment=PATH=$HOME/.opencode/bin:/usr/local/bin:/usr/bin:/bin
Environment=VOICEIME_CORRECTOR_HOST=127.0.0.1
Environment=VOICEIME_CORRECTOR_PORT=19888
Environment=VOICEIME_CORRECTOR_MODEL=$MODEL
Environment=VOICEIME_CORRECTOR_VARIANT=$VARIANT

[Install]
WantedBy=default.target
EOF

chmod +x "$ROOT/voiceime-corrector" "$ROOT/voiceime-engine" "$ROOT/voiceime-ptt"
systemctl --user daemon-reload
systemctl --user daemon-reload
systemctl --user enable voiceime-corrector.service
systemctl --user restart voiceime-corrector.service

# Wait briefly for the port to come up so the user sees an immediate ✓.
echo -n "Waiting for voiceime-corrector to listen on :19888... "
ready=0
for _ in $(seq 1 30); do
  if curl -fsS --max-time 1 http://127.0.0.1:19888/health >/dev/null 2>&1; then
    ready=1; break
  fi
  sleep 0.2
done
if [ "$ready" = 1 ]; then
  printf 'ok\n'
  curl -s http://127.0.0.1:19888/health
  echo
else
  printf 'timed out\n'
  echo "Check: journalctl --user -u voiceime-corrector -n 80 --no-pager"
fi
