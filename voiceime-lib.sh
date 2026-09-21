#!/usr/bin/env bash
set -u
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
UNIT="voiceime-ptt.service"
LOCK="${XDG_RUNTIME_DIR:-/tmp}/voiceime.lock"
COOKIE="${XDG_RUNTIME_DIR:-/tmp}/voiceime-$(id -u).cookie"

export DISPLAY="${DISPLAY:-:1}"
export LD_LIBRARY_PATH="$ROOT/bin:${LD_LIBRARY_PATH:-}"
export PATH="$ROOT/bin:$PATH"

voiceime_lock() { exec 9>"$LOCK"; flock -w 5 9 || exit 1; }
voiceime_unlock() { exec 9>&-; }

voiceime_engine_pids() {
  pgrep -u "$(id -u)" -f -- "^[^ ]*python[0-9.]* $ROOT/voiceime-engine" 2>/dev/null || true
}
voiceime_legacy_pids() {
  pgrep -u "$(id -u)" -f -- "^[^ ]*python[0-9.]* $ROOT/nerd-dictation/nerd-dictation begin" 2>/dev/null || true
}
voiceime_pids() {
  { voiceime_engine_pids; voiceime_legacy_pids; } | awk 'NF && !seen[$0]++'
}

voiceime_pid() {
  local pid
  pid="$(voiceime_engine_pids | head -1)"
  if [ -n "$pid" ]; then echo "$pid"; return 0; fi
  pid="$(cat "$COOKIE" 2>/dev/null || true)"
  [[ "$pid" =~ ^[0-9]+$ ]] || return 1
  [ -d "/proc/$pid" ] || return 1
  echo "$pid"
}

voiceime_state() {
  local pid state
  pid="$(voiceime_pid)" || { echo none; return; }
  state="$(awk '{print $3}' "/proc/$pid/stat" 2>/dev/null)" || { echo none; return; }
  [ "$state" = T ] && echo suspended || echo recording
}

voiceime_resume() {
  local pid; pid="$(voiceime_pid)" || return 1
  [ "$(voiceime_state)" = suspended ] && kill -CONT "$pid" 2>/dev/null
}

voiceime_suspend() {
  local pid; pid="$(voiceime_pid)" || return 1
  [ "$(voiceime_state)" = recording ] && kill -USR1 "$pid" 2>/dev/null
  for _ in $(seq 1 100); do
    [ "$(voiceime_state)" != recording ] && return 0
    sleep 0.05
  done
  return 1
}

voiceime_ensure_daemon() {
  case "$(voiceime_state)" in suspended|recording) return 0 ;; esac
  systemctl --user start "$UNIT" >/dev/null 2>&1 ||     setsid "$ROOT/voiceime-ptt" >/dev/null 2>&1 < /dev/null &
  for _ in $(seq 1 300); do
    [ "$(voiceime_state)" = suspended ] && return 0
    sleep 0.1
  done
  return 1
}

voiceime_kill_all() {
  local pid pids
  pids="$(voiceime_pids)"
  for pid in $pids; do
    kill -TERM "$pid" 2>/dev/null || true
    kill -CONT "$pid" 2>/dev/null || true
  done
  sleep 0.2
  pids="$(voiceime_pids)"
  [ -n "$pids" ] && kill -KILL $pids 2>/dev/null || true
  pkill -u "$(id -u)" -x parec 2>/dev/null || true
  rm -f "$COOKIE"
}
