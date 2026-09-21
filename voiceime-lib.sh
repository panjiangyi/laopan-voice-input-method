#!/usr/bin/env bash
# Shared helpers for the voiceime scripts.
#
# Invariant: at most ONE nerd-dictation process exists. It is owned by the
# voiceime-ptt daemon, stays suspended (SIGSTOP, mic released, 0% CPU) when
# idle, and is flipped to recording by signals:
#
#   SIGCONT -> record        SIGUSR1 -> flush text, release mic, suspend
#
# The daemon uses a private cookie so manual upstream tests cannot replace its
# PID. Hotkeys resume its loaded model rather than starting another instance.

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ND="$ROOT/nerd-dictation/nerd-dictation"
COOKIE="${XDG_RUNTIME_DIR:-/tmp}/voiceime-$(id -u).cookie"
LOCK="${XDG_RUNTIME_DIR:-/tmp}/voiceime.lock"
UNIT="voiceime-ptt.service"

export DISPLAY="${DISPLAY:-:1}"
export LD_LIBRARY_PATH="$ROOT/bin:${LD_LIBRARY_PATH:-}"
export PATH="$ROOT/bin:$PATH"

# Serialize hotkey presses; the fd is closed again before anything long-running.
voiceime_lock() { exec 9>"$LOCK"; flock -w 5 9 || exit 1; }
voiceime_unlock() { exec 9>&-; }

# Every live nerd-dictation process (there should never be more than one).
voiceime_pids() { pgrep -u "$(id -u)" -f -- "^[^ ]*python[0-9.]* $ND begin" 2>/dev/null; }

# PID recorded in the cookie, if it is still a dictation process.
voiceime_pid() {
  local pid
  pid="$(cat "$COOKIE" 2>/dev/null)" || return 1
  [[ "$pid" =~ ^[0-9]+$ ]] || return 1
  grep -qa "nerd-dictation" "/proc/$pid/cmdline" 2>/dev/null || return 1
  echo "$pid"
}

# none | starting | suspended | recording
voiceime_state() {
  local pid state caught
  pid="$(voiceime_pid)" || { echo none; return; }
  state="$(awk '{print $3}' "/proc/$pid/stat" 2>/dev/null)" || { echo none; return; }
  # The cookie is written before Vosk loads. SIGUSR1 has its default (fatal)
  # action until the recording loop installs its handlers.
  caught="$(awk '/^SigCgt:/ {print $2}' "/proc/$pid/status" 2>/dev/null)"
  if [ -z "$caught" ] || (( (16#$caught & 512) == 0 )); then
    echo starting
    return
  fi
  [ "$state" = T ] && echo suspended || echo recording
}

voiceime_resume() {
  local pid; pid="$(voiceime_pid)" || return 1
  [ "$(voiceime_state)" = suspended ] && kill -CONT "$pid" 2>/dev/null
  return 0
}

voiceime_suspend() {
  local pid; pid="$(voiceime_pid)" || return 1
  # SIGUSR1 sent to a stopped process stays pending and would re-suspend it
  # immediately after the next resume.
  [ "$(voiceime_state)" = recording ] && kill -USR1 "$pid" 2>/dev/null
  for _ in $(seq 1 100); do
    [ "$(voiceime_state)" != recording ] && return 0
    sleep 0.05
  done
  echo "voiceime: timed out waiting for dictation to suspend" >&2
  return 1
}

# Make sure the push-to-talk daemon (and therefore the dictation process) is up.
voiceime_ensure_daemon() {
  case "$(voiceime_state)" in
    suspended|recording) return 0 ;;
  esac
  if systemctl --user list-unit-files "$UNIT" >/dev/null 2>&1 &&
     systemctl --user cat "$UNIT" >/dev/null 2>&1; then
    systemctl --user start "$UNIT" >/dev/null 2>&1
  else
    setsid "$ROOT/voiceime-ptt" >/dev/null 2>&1 < /dev/null &
  fi
  for _ in $(seq 1 100); do   # model load, up to ~10s
    [ "$(voiceime_state)" = suspended ] && return 0
    sleep 0.1
  done
  return 1
}

# Emergency cleanup: kill every dictation process and any orphaned recorder.
voiceime_kill_all() {
  local pids children pid
  pids="$(voiceime_pids)" || true
  if [ -n "$pids" ]; then
    children=""
    for pid in $pids; do
      children="$children $(pgrep -P "$pid" 2>/dev/null | tr '\n' ' ')"
    done
    kill -CONT $pids 2>/dev/null || true   # a stopped process ignores SIGTERM
    kill $pids 2>/dev/null || true
    for _ in 1 2 3 4 5 6 7 8 9 10; do
      [ -z "$(voiceime_pids)" ] && break
      sleep 0.2
    done
    pids="$(voiceime_pids)" || true
    [ -n "$pids" ] && kill -9 $pids 2>/dev/null
    for pid in $children; do
      [ -d "/proc/$pid" ] && kill -9 "$pid" 2>/dev/null
    done
  fi
  rm -f "$COOKIE"
  return 0
}
