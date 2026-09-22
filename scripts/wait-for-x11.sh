#!/usr/bin/env bash
# Start a VoiceIME component only after the user's X11/Xwayland session is
# usable.  The user systemd manager may reach default.target before GDM has
# created the display socket or imported DISPLAY/XAUTHORITY.
set -euo pipefail

if [ "$#" -eq 0 ]; then
  echo "usage: $0 COMMAND [ARG ...]" >&2
  exit 2
fi

runtime_dir="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
attempt=0

while :; do
  displays=()
  [ -n "${DISPLAY:-}" ] && displays+=("$DISPLAY")
  for socket in /tmp/.X11-unix/X*; do
    [ -S "$socket" ] || continue
    displays+=(":${socket##*/X}")
  done

  authorities=()
  [ -n "${XAUTHORITY:-}" ] && authorities+=("$XAUTHORITY")
  authorities+=("$runtime_dir/gdm/Xauthority" "$HOME/.Xauthority")

  for display in "${displays[@]}"; do
    for authority in "${authorities[@]}"; do
      [ -r "$authority" ] || continue
      if env DISPLAY="$display" XAUTHORITY="$authority" \
        xinput list --id-only "Virtual core XTEST keyboard" >/dev/null 2>&1; then
        export DISPLAY="$display"
        export XAUTHORITY="$authority"
        echo "[voiceime-session] X11 ready on $DISPLAY" >&2
        exec "$@"
      fi
    done
  done

  if (( attempt % 10 == 0 )); then
    echo "[voiceime-session] waiting for the graphical session" >&2
  fi
  attempt=$((attempt + 1))
  sleep 1
done
