#!/usr/bin/env bash
# PiArena - Einrichtung am Raspberry Pi (als normaler Benutzer ausfuehren, NICHT mit sudo).
#
#   ./install.sh                 prueft python3, pygame, gpiozero, Chromium; installiert Fehlendes per apt
#   ./install.sh --autostart     zusaetzlich: Host startet nach jedem Neustart/Login von selbst
#   ./install.sh --kein-autostart  Autostart wieder ausschalten
#
# Mehrfach ausfuehren schadet nicht. Geaendert wird nur im eigenen Home
# (~/.config/systemd/user/pi-arena.service) - ausser den apt-Paketen.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UNIT_DIR="$HOME/.config/systemd/user"
UNIT="$UNIT_DIR/pi-arena.service"
AUTOSTART=""

for arg in "$@"; do
  case "$arg" in
    --autostart) AUTOSTART="an" ;;
    --kein-autostart) AUTOSTART="aus" ;;
    -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
    *) echo "Unbekannte Option: $arg (moeglich: --autostart, --kein-autostart)"; exit 2 ;;
  esac
done

if [ "$(id -u)" -eq 0 ]; then
  echo "Bitte OHNE sudo starten: ./install.sh  (sudo wird nur fuer apt gefragt)"
  exit 1
fi

ok()   { echo "  [OK]   $*"; }
fehlt() { echo "  [FEHLT] $*"; }

echo "== PiArena Einrichtung in $REPO"

# ---- 1) Pruefen
PAKETE=()
if command -v python3 >/dev/null 2>&1; then
  ok "python3 $(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')"
  if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
    echo "        Hinweis: Python 3.11 oder neuer empfohlen (Raspberry Pi OS Bookworm/Trixie)."
  fi
else
  fehlt "python3"; PAKETE+=(python3)
fi
for modul in pygame gpiozero; do
  if command -v python3 >/dev/null 2>&1 && python3 -c "import $modul" >/dev/null 2>&1; then
    ok "$modul"
  else
    fehlt "$modul"; PAKETE+=("python3-$modul")
  fi
done
if command -v python3 >/dev/null 2>&1 && python3 -c "import numpy" >/dev/null 2>&1; then
  ok "numpy (optional, fuer Musik ueber HDMI)"
else
  echo "  [--]   numpy fehlt (optional, nur fuer Musik ueber HDMI): sudo apt install -y python3-numpy"
fi
if command -v chromium-browser >/dev/null 2>&1 || command -v chromium >/dev/null 2>&1; then
  ok "Chromium (fuer die Browser-Runden an den Schueler-Pis)"
else
  echo "  [--]   Chromium nicht gefunden. Am Pi mit Desktop ist er vorinstalliert;"
  echo "         sonst: sudo apt install -y chromium   (aeltere Systeme: chromium-browser)"
fi
command -v curl >/dev/null 2>&1 && ok "curl (fuer den Beitritts-Befehl der Schueler)" \
  || echo "  [--]   curl fehlt (Schueler-Pis brauchen es zum Beitreten): sudo apt install -y curl"

# ---- 2) Fehlendes installieren
if [ "${#PAKETE[@]}" -gt 0 ]; then
  echo
  echo "Es fehlen: ${PAKETE[*]}"
  if ! command -v apt-get >/dev/null 2>&1; then
    echo "Kein apt gefunden - bitte die Pakete selbst installieren."
    exit 1
  fi
  if sudo -n true 2>/dev/null; then
    echo "Installiere mit: sudo apt install -y ${PAKETE[*]}"
    sudo apt-get install -y "${PAKETE[@]}"
  elif [ -t 0 ]; then
    read -r -p "Jetzt mit sudo installieren? (fragt evtl. nach dem Passwort) [j/N] " antwort
    case "$antwort" in
      j|J|ja|Ja|y|Y) sudo apt-get install -y "${PAKETE[@]}" ;;
      *) echo "Abgebrochen. Spaeter selbst: sudo apt install -y ${PAKETE[*]}"; exit 1 ;;
    esac
  else
    echo "sudo braucht ein Passwort. Bitte selbst ausfuehren:"
    echo "  sudo apt install -y ${PAKETE[*]}"
    exit 1
  fi
fi

chmod +x "$REPO/start.sh" "$REPO/stop.sh" "$REPO/install.sh" 2>/dev/null || true

# ---- 3) Autostart (nur auf Wunsch)
if [ "$AUTOSTART" = "an" ]; then
  if ! command -v systemctl >/dev/null 2>&1; then
    echo "systemctl fehlt - Autostart nicht moeglich."
    exit 1
  fi
  mkdir -p "$UNIT_DIR"
  tmp="$(mktemp "$UNIT_DIR/.pi-arena.XXXXXX")"
  cat > "$tmp" <<EOF
[Unit]
Description=PiArena Host (Multiplayer-Arena fuer die Pi-Platine)
After=default.target

[Service]
Type=simple
WorkingDirectory=$REPO
Environment=PYTHONUNBUFFERED=1
# warten, bis der Desktop (Wayland) da ist - sonst laeuft der Host ohne Bild
ExecStartPre=/bin/sh -c 'for i in \$(seq 90); do [ -S "\$XDG_RUNTIME_DIR/wayland-0" ] && exit 0; sleep 1; done; exit 0'
ExecStart=/usr/bin/env python3 $REPO/arena/host.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF
  mv -f "$tmp" "$UNIT"
  systemctl --user daemon-reload
  systemctl --user enable pi-arena.service >/dev/null
  echo
  echo "Autostart AN: $UNIT"
  echo "  Der Host startet ab jetzt nach jedem Neustart, sobald der Desktop da ist."
  echo "  Jetzt gleich starten:  systemctl --user start pi-arena   (oder ./start.sh)"
  echo "  Ausschalten:           ./install.sh --kein-autostart"
elif [ "$AUTOSTART" = "aus" ]; then
  if [ -f "$UNIT" ]; then
    systemctl --user disable --now pi-arena.service >/dev/null 2>&1 || true
    rm -f "$UNIT"
    systemctl --user daemon-reload || true
    echo "Autostart AUS (Datei entfernt: $UNIT)"
  else
    echo "Autostart war nicht eingerichtet."
  fi
fi

echo
echo "Fertig. Host starten:  ./start.sh        (beenden: ESC in der Lobby oder ./stop.sh)"
