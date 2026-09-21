#!/usr/bin/env bash
# 12-setup-corrector.sh — verify opencode CLI is installed and authenticated.
#
# The corrector now shells out to `opencode run` for each utterance, so the
# only prerequisites are:
#   1. The `opencode` binary is on PATH (or in ~/.opencode/bin/opencode).
#   2. Some provider is authenticated (`opencode providers` shows status).
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"

OPENCODE_BIN="$(command -v opencode || true)"
if [ -z "$OPENCODE_BIN" ] && [ -x "$HOME/.opencode/bin/opencode" ]; then
  OPENCODE_BIN="$HOME/.opencode/bin/opencode"
fi
if [ -z "$OPENCODE_BIN" ]; then
  printf 'opencode CLI not found.\n'
  printf 'Install it from https://opencode.ai/ then re-run this script.\n'
  exit 1
fi
printf 'opencode: %s\n' "$OPENCODE_BIN"

# Verify the model the corrector will use is actually available.
if ! "$OPENCODE_BIN" models 2>/dev/null \
     | grep -q '^opencode/muse-spark-1.3-contributor-free$'; then
  printf '\nWARNING: model opencode/muse-spark-1.3-contributor-free not in `opencode models`.\n'
  printf 'Either your opencode version is too old, or your account lost access.\n'
  printf 'Run `opencode providers` to confirm at least one provider is logged in.\n'
fi

printf '\nNext:\n'
printf '  bash scripts/13-install-corrector-service.sh\n'
printf '  ./build-and-start.sh   # restart voiceime-ptt to pick up the wrapper\n'
