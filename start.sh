#!/usr/bin/env bash
# MEGA-PARTY Host im Vollbild starten (am Pi mit Monitor).
#   ./start.sh                  normal: Host spielt mit, Browser-Runden an
#   ./start.sh --zuschauer      Host spielt nicht mit, nur Moderation
#   ./start.sh --ohne-web       ohne Browser-Runden (nur Taster-Spiele)
# Alle Optionen gehen direkt an party/mega.py (Liste: python3 party/mega.py --help).
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if command -v systemctl >/dev/null 2>&1 && systemctl --user is-active --quiet mega-party.service 2>/dev/null; then
  echo "MEGA-PARTY laeuft schon (Autostart). Neu starten: ./stop.sh && ./start.sh"
  exit 0
fi
if pgrep -f "party/mega.py" >/dev/null 2>&1; then
  echo "MEGA-PARTY laeuft schon. Erst beenden: ./stop.sh"
  exit 1
fi

# per SSH gestartet? -> trotzdem auf den Monitor des Pi
if [ -z "${WAYLAND_DISPLAY:-}" ] && [ -z "${DISPLAY:-}" ]; then
  export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
  [ -S "$XDG_RUNTIME_DIR/wayland-0" ] && export WAYLAND_DISPLAY=wayland-0
fi

cd "$REPO"
exec python3 party/mega.py "$@"
