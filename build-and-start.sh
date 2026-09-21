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

# 3. Sanity-check the Sherpa backend; warn (don't fail) if first-time setup
#    is still needed. Without it the daemon will start but dictate nothing.
step "Verify Sherpa streaming backend"
SHERPA_MODEL="$ROOT/models/sherpa-onnx-streaming-paraformer-bilingual-zh-en"
if [ ! -f "$SHERPA_MODEL/tokens.txt" ]; then
  printf '\nWARNING: Sherpa bilingual model not found at %s\n' "$SHERPA_MODEL"
  printf 'First-time setup needed; run once:\n  bash scripts/09-setup-sherpa.sh\n\n'
fi

# 3b. Same idea for the LLM corrector: warn-only, never block PTT.
#     Without the corrector, voiceime-engine simply skips text refinement.
step "Verify LLM corrector endpoint"
CORR="${VOICEIME_LLM_ENDPOINT:-http://127.0.0.1:19888}"
if curl -fsS --max-time 1 "$CORR/health" >/dev/null 2>&1; then
  printf '  ✓ LLM corrector reachable at %s\n' "$CORR"
  printf '    %s\n' "$(curl -fsS --max-time 1 "$CORR/health" | head -c 200)"
else
  printf '\nWARNING: LLM corrector not reachable at %s\n' "$CORR"
  printf 'First-time setup (OpenCode Zen free tier):\n'
  printf '  OPENCODE_API_KEY=sk-... bash scripts/12-setup-corrector.sh\n'
  printf '  bash scripts/13-install-corrector-service.sh\n\n'
fi

# 4. Refresh the systemd user unit (idempotent; picks up any new ExecStart
#    or Environment= changes from this checkout).
step "Refresh systemd user unit"
bash "$ROOT/scripts/10-install-service.sh"
systemctl --user daemon-reload

# 5. Start the daemon.
step "Start voiceime-ptt"
systemctl --user enable --now voiceime-ptt.service

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
