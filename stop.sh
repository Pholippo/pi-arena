#!/usr/bin/env bash
# PiArena beenden: Host (arena/host.py), Browser-Spielserver (arena/browserspiele.py) und ggf. den Autostart-Dienst.
# Der Autostart bleibt eingerichtet und startet beim naechsten Neustart wieder.
set -uo pipefail

if command -v systemctl >/dev/null 2>&1 && systemctl --user is-active --quiet pi-arena.service 2>/dev/null; then
  systemctl --user stop pi-arena.service && echo "Autostart-Dienst gestoppt."
fi

gestoppt=0
for muster in "arena/host.py" "arena/browserspiele.py" "browserspiele.py"; do
  if pkill -f "$muster" 2>/dev/null; then
    gestoppt=1
  fi
done
sleep 1
for muster in "arena/host.py" "browserspiele.py"; do
  pkill -9 -f "$muster" 2>/dev/null || true  # haengt noch was? -> hart beenden
done

if [ "$gestoppt" -eq 1 ]; then
  echo "PiArena beendet. Ports 8081/8082 sind wieder frei."
else
  echo "Es lief kein PiArena."
fi
