#!/usr/bin/env bash
# MEGA-PARTY beenden: Host (mega.py), Browser-Spielserver (webspiele.py) und ggf. den Autostart-Dienst.
# Der Autostart bleibt eingerichtet und startet beim naechsten Neustart wieder.
set -uo pipefail

if command -v systemctl >/dev/null 2>&1 && systemctl --user is-active --quiet mega-party.service 2>/dev/null; then
  systemctl --user stop mega-party.service && echo "Autostart-Dienst gestoppt."
fi

gestoppt=0
for muster in "party/mega.py" "party/webspiele.py" "webspiele.py"; do
  if pkill -f "$muster" 2>/dev/null; then
    gestoppt=1
  fi
done
sleep 1
for muster in "party/mega.py" "webspiele.py"; do
  pkill -9 -f "$muster" 2>/dev/null || true  # haengt noch was? -> hart beenden
done

if [ "$gestoppt" -eq 1 ]; then
  echo "MEGA-PARTY beendet. Ports 8081/8082 sind wieder frei."
else
  echo "Es lief keine MEGA-PARTY."
fi
