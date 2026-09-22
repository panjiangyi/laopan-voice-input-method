#!/usr/bin/env bash
# build-and-start.sh — kill any running instance, rebuild from source,
# and start a fresh VoiceIME daemon so the project is immediately usable.
#
# Designed for day-to-day use after a `git pull`. First-time install of
# system packages (g++, fcitx5 dev libs, sherpa-onnx runtime, model
# downloads) is NOT done here — run README §"推荐安装" once before
# relying on this script.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "$0")" && pwd)"
cd "$ROOT"

step() { printf '\n=== %s ===\n' "$*"; }
die()  { printf 'build-and-start: %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -ne 0 ] || die "do not run as root; the daemon runs as your user"

# Collect all correction choices in one place. Environment variables remain
# the non-interactive interface for automation; a terminal gets friendly
# prompts with conservative defaults.
LLM_ENABLED="${VOICEIME_LLM_ENABLED:-0}"
LLM_MODE="${VOICEIME_LLM_MODE:-punctuation}"
LLM_TIMEOUT="${VOICEIME_LLM_TIMEOUT:-15.0}"
DEEPSEEK_MODEL="${DEEPSEEK_MODEL:-deepseek-v4-flash}"

if [ -t 0 ]; then
  step "Configure optional legacy AI correction"
  read -r -p "Enable legacy AI correction after each utterance? [y/N] " answer
  case "${answer:-N}" in
    [Yy]*) LLM_ENABLED=1 ;;
    *) LLM_ENABLED=0 ;;
  esac

  if [ "$LLM_ENABLED" = 1 ]; then
    printf '%s\n' \
      'Correction mode:' \
      '  1) punctuation — only punctuation/spacing (recommended)' \
      '  2) aggressive  — may repair words, but can change meaning'
    read -r -p "Choose [1]: " answer
    case "${answer:-1}" in
      1) LLM_MODE=punctuation ;;
      2) LLM_MODE=aggressive ;;
      *) die "invalid correction mode: $answer" ;;
    esac

    read -r -p "DeepSeek model [$DEEPSEEK_MODEL]: " answer
    DEEPSEEK_MODEL="${answer:-$DEEPSEEK_MODEL}"

    read -r -p "Engine wait timeout in seconds [$LLM_TIMEOUT]: " answer
    LLM_TIMEOUT="${answer:-$LLM_TIMEOUT}"
  fi
fi

case "$LLM_ENABLED" in 0|1) ;; *) die "VOICEIME_LLM_ENABLED must be 0 or 1" ;; esac
case "$LLM_MODE" in punctuation|aggressive) ;; *) die "invalid VOICEIME_LLM_MODE: $LLM_MODE" ;; esac
[[ "$LLM_TIMEOUT" =~ ^[0-9]+([.][0-9]+)?$ ]] || die "LLM timeout must be a positive number"
[[ "$DEEPSEEK_MODEL" =~ ^[A-Za-z0-9._:/+-]+$ ]] || die "model name contains unsupported characters"

export VOICEIME_LLM_ENABLED="$LLM_ENABLED"
export VOICEIME_LLM_MODE="$LLM_MODE"
export VOICEIME_LLM_TIMEOUT="$LLM_TIMEOUT"
export DEEPSEEK_MODEL

# 0. Make sure the project scripts are executable (a fresh checkout often
#    loses +x, and 10-install-service.sh also resets these bits).
step "Refresh executable bits"
chmod +x "$ROOT"/voiceime-* "$ROOT"/native/*.sh "$ROOT"/scripts/*.sh

# 1. Stop whatever is currently running.
step "Stop existing daemon / instances"
if [ -x "$ROOT/voiceime-reset" ]; then
  "$ROOT/voiceime-reset" || true
else
  systemctl --user stop voiceime-ptt.service 2>/dev/null || true
fi
# Belt and braces: nuke any straggler engine / recorder / dictation process
# that escaped the reset path (e.g. crashed before the cookie was written).
pkill -u "$(id -u)" -x parec                    2>/dev/null || true
pkill -u "$(id -u)" -f "$ROOT/voiceime-engine"  2>/dev/null || true
pkill -u "$(id -u)" -f "$ROOT/voiceime-ptt"     2>/dev/null || true

# 2. Rebuild the Fcitx5 native bridge.
step "Rebuild Fcitx5 addon (native/ → build/libvoiceime.so)"
command -v g++ >/dev/null || die "g++ not installed"
command -v fcitx5 >/dev/null || die "fcitx5 not installed"

# native/build.sh puts Fcitx5 headers under /usr/include/Fcitx5 by default.
# Detect the missing-dev-package case up front so we can offer to fix it.
FCITX_INC="${FCITX_DEV_ROOT:-/usr}/include/Fcitx5"
needs_fcitx_dev=0
for sub in Core/Addon addon addoninstance; do
  # voiceime.cpp includes <fcitx/addonfactory.h>, which lives under Core/.
  [ -f "$FCITX_INC/Core/fcitx/addonfactory.h" ] || needs_fcitx_dev=1
  break
done
if [ "$needs_fcitx_dev" = 1 ]; then
  missing_pkgs="libfcitx5core-dev libfcitx5utils-dev libfcitx5config-dev"
  printf 'Fcitx5 dev headers not found at %s/Core.\n' "$FCITX_INC"
  printf 'Missing build-time packages: %s\n' "$missing_pkgs"
  if command -v sudo >/dev/null 2>&1 && [ -t 0 ]; then
    read -r -p "Install them now with sudo? [Y/n] " ans
    case "${ans:-Y}" in
      [Yy]*)
        sudo apt-get update
        sudo apt-get install -y $missing_pkgs
        ;;
      *)
        die "install them yourself then re-run: sudo apt-get install -y $missing_pkgs"
        ;;
    esac
  else
    die "install them yourself then re-run: sudo apt-get install -y $missing_pkgs"
  fi
fi

bash "$ROOT/native/build.sh"
bash "$ROOT/native/install.sh"
# Pick up the freshly-installed addon. fcitx5 -r can hang without a TTY
# and nohup&+disown leaves an orphan when nothing is listening. Instead,
# start a fresh fcitx5 detached from this shell with the right env, and
# kill any leftover first so we don't double-start.
pkill -u "$(id -u)" -x fcitx5 2>/dev/null || true
sleep 0.2
setsid env DISPLAY="${DISPLAY:-:0}" \
           DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=/run/user/$(id -u)/bus}" \
           fcitx5 >/tmp/fcitx5.log 2>&1 < /dev/null &
disown 2>/dev/null || true
# Give fcitx5 a moment to register its D-Bus service before the engine
# below tries to talk to org.voiceime.Input.
for _ in $(seq 1 30); do
  busctl --user status org.voiceime.Input >/dev/null 2>&1 && break
  sleep 0.1
done

# 3. Verify streaming + final quality models. Missing quality models are safe:
#    VoiceIME falls back to streaming text, but the user should know they are
#    not actually testing the new final pipeline.
step "Verify production ASR models"
SHERPA_MODEL="$ROOT/models/sherpa-onnx-streaming-paraformer-bilingual-zh-en"
FINAL_MODEL="$ROOT/models/sherpa-onnx-paraformer-zh-2024-03-09"
PUNCT_MODEL="$ROOT/models/sherpa-onnx-punct-ct-transformer-zh-en-vocab272727-2024-04-12-int8"
if [ ! -f "$SHERPA_MODEL/tokens.txt" ]; then
  printf '\nWARNING: streaming Paraformer missing at %s\n' "$SHERPA_MODEL"
  printf 'Run once:\n  bash scripts/09-setup-sherpa.sh\n\n'
fi
if [ ! -f "$FINAL_MODEL/model.int8.onnx" ] || [ ! -f "$PUNCT_MODEL/model.int8.onnx" ]; then
  printf '\nWARNING: final quality models are incomplete.\n'
  printf 'To test PR #6 fully, run:\n  bash scripts/11-setup-quality.sh\n\n'
else
  printf '  ✓ streaming + offline final + punctuation models ready\n'
fi

# 3b. DeepSeek is legacy/optional in the preedit pipeline.
step "Configure optional DeepSeek correction"
systemctl --user disable --now voiceime-corrector.service 2>/dev/null || true
if [ "$LLM_ENABLED" = 1 ]; then
  [ -s "$ROOT/.env" ] || die "AI correction enabled but $ROOT/.env is missing"
  grep -q '^DEEPSEEK_API_KEY=' "$ROOT/.env" || die "DEEPSEEK_API_KEY missing from .env"
  printf '  ✓ Direct DeepSeek correction enabled: mode=%s model=%s timeout=%ss\n' \
    "$LLM_MODE" "$DEEPSEEK_MODEL" "$LLM_TIMEOUT"
else
  printf '  AI correction disabled\n'
fi

# 4. Refresh the systemd user unit (idempotent; picks up any new ExecStart
#    or Environment= changes from this checkout).
step "Refresh systemd user unit"
bash "$ROOT/scripts/10-install-service.sh"
systemctl --user daemon-reload

# 5. Start the daemon.
step "Start voiceime-ptt"
systemctl --user enable --now voiceime-ptt.service
systemctl --user enable --now voiceime-overlay.service

# 6. Wait until the daemon is actually idle (suspended = loaded and ready
#    for PTT) instead of declaring victory on "active" alone.
printf 'Waiting for daemon to reach idle... '
state=""
for _ in $(seq 1 60); do
  state="$("$ROOT/voiceime-status" 2>/dev/null \
            | awk -F': *' '/^state:[[:space:]]*/{print $2; exit}')"
  case "$state" in
    suspended|recording) printf 'ok (%s)\n' "$state"; break ;;
  esac
  sleep 0.1
done
if [ "$state" != suspended ] && [ "$state" != recording ]; then
  printf 'timed out (state=%s)\n' "${state:-none}"
  printf 'Check: journalctl --user -u voiceime-ptt -n 80 --no-pager\n'
fi

step "Status"
"$ROOT/voiceime-status"

step "Ready"
printf 'Hold right Alt to dictate.  Ctrl+Alt+V toggles.  Ctrl+Alt+B forces stop.\n'
printf 'Logs: journalctl --user -u voiceime-ptt -f\n'
