#!/usr/bin/env python3
"""PiArena - HOST: das Programm fuer den Pi mit Monitor/Beamer. Dieses Programm startest du.

WAS PASSIERT?
  Jede/r in der Klasse hat einen eigenen Pi mit derselben Platine und spielt JEDER GEGEN JEDEN.
  Der Host zeigt am Monitor die Lobby (Beitritts-Befehl + QR-Code), sagt die Runden an, zaehlt mit
  und kuert am Ende den Sieger. Die Schueler-Pis treten bei mit:   curl http://<HOST-IP>:8081/j | python3

  Der Moderator (wer am Host sitzt) spielt selbst mit. Seine Taster steuern, solange keine Runde laeuft:
    MITTE = Start / Weiter    RECHTS = Runde ueberspringen    LINKS = Demo-Bots an/aus (in der Lobby)
  Tastatur am Host: Leertaste = Mitte, Pfeil links/rechts, N = ueberspringen, A S D = eigene Taster, ESC = Ende.

WIE STARTEN?
  python3 arena/host.py                       am Pi (Vollbild, Moderator spielt mit, Name = Hostname)
  python3 arena/host.py --name Max            eigener Name fuer den Moderator
  python3 arena/host.py --zuschauer           Moderator spielt nicht mit
  python3 arena/host.py --ohne-web            ohne Browser-Runden
  python3 arena/host.py --sim --fenster       am Laptop ohne Platine, im Fenster
  python3 arena/host.py --fenster --nur morse NUR dieses Spiel (zum Testen deines eigenen Spiels)
  python3 arena/host.py --selbsttest --sim    eine ganze Partie ohne Menschen als Test

WELCHE DATEI MACHT WAS? (alle in arena/, siehe arena/README.md)
  host.py          dieses Programm: liest die Start-Optionen und startet alles
  einstellungen.py Rundenzahl, Siegpunkte, DEAKTIVIERT (Spiele, die nicht mitspielen)
  minispiele.py    die Taster-Minispiele - HIER baust du eigene Spiele
  spieler.py       Programm fuer die Schueler-Pis (Platine, Verbindung zum Host)
  ablauf.py        Spielablauf und Punkte (ohne Grafik)
  monitor.py       das Bild am Monitor (pygame)
  webserver.py     Netzwerk: Anfragen der Pis/Handys, Download /j, Live-Bild
  browserspiele.py Server fuer die Browser-Spiele (startet der Host selbst mit)
"""
import argparse
import os
import sys

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HIER)  # damit "import minispiele" usw. auch von einem anderen Ordner aus klappt

import einstellungen as E  # noqa: E402
import minispiele  # noqa: E402
from ablauf import WEB_SPIELE  # noqa: E402


def nur_spiele(text):
    """'--nur morse,tap' -> {"morse", "tap"}. Unbekannter Name -> Fehlermeldung mit allen gueltigen Namen."""
    gueltig = list(minispiele.SPIELE) + list(WEB_SPIELE)
    namen = {n.strip().lower() for n in text.split(",") if n.strip()}
    falsch = sorted(namen - set(gueltig))
    if falsch or not namen:
        print(f"FEHLER: --nur {text!r}: unbekanntes Spiel {', '.join(falsch) or '(leer)'}.")
        print(f"  Gueltige Namen: {', '.join(gueltig)}")
        print("  (Taster-Spiele stehen in SPIELE in arena/minispiele.py, Browser-Spiele in WEB_SPIELE in arena/ablauf.py)")
        sys.exit(2)
    return namen


def main():
    ap = argparse.ArgumentParser(description="PiArena Host")
    ap.add_argument("--name", default=None, help="Name des Moderators als Mitspieler (Standard: Hostname)")
    ap.add_argument("--zuschauer", action="store_true", help="nicht mitspielen, nur moderieren")
    ap.add_argument("--sim", action="store_true", help="ohne GPIO (Laptop)")
    ap.add_argument("--fenster", action="store_true", help="im Fenster statt Vollbild")
    ap.add_argument("--runden", type=int, default=E.MAX_RUNDEN, help="maximale Rundenzahl (letzte = Finale x2)")
    ap.add_argument("--ziel", type=int, default=E.ZIEL_PUNKTE, help="Punkte zum Sieg")
    ap.add_argument("--schnell", action="store_true", help="kurze Ansagen/Auswertungen")
    ap.add_argument("--nur", default=None, metavar="SPIEL",
                    help="nur diese Spiele, mit Komma getrennt (auch wenn sie in DEAKTIVIERT stehen), z.B. --nur morse")
    ap.add_argument("--selbsttest", action="store_true", help="ganze Partie ohne Menschen als Test")
    ap.add_argument("--web-dauer", type=int, default=E.WEB_DAUER_S, help="Spielzeit der Browser-Runden in s")
    ap.add_argument("--web-server", default=f"127.0.0.1:{E.WEB_PORT}",
                    help="browserspiele.py-Server (host:port); lokal wird er automatisch mitgestartet")
    ap.add_argument("--ohne-web", action="store_true", help="keine Browser-Runden, browserspiele.py nicht starten")
    a = ap.parse_args()

    # Start-Optionen in die Einstellungen uebernehmen (die anderen Dateien lesen sie von dort)
    E.WEB_DAUER_S = max(20, min(600, a.web_dauer))
    E.WEB_BASIS = None if a.ohne_web else "http://" + a.web_server
    if a.nur:
        E.NUR = nur_spiele(a.nur)
        print("Nur diese Spiele:", ", ".join(sorted(E.NUR)))

    if a.selbsttest:
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        from selbsttest import selbsttest
        sys.exit(selbsttest(a.sim))

    # per SSH gestartet? -> trotzdem auf den Pi-Monitor (labwc/Wayland)
    if sys.platform.startswith("linux") and not os.environ.get("WAYLAND_DISPLAY") and not os.environ.get("DISPLAY"):
        laufzeit = f"/run/user/{os.getuid()}"
        if os.path.exists(os.path.join(laufzeit, "wayland-0")):
            os.environ["WAYLAND_DISPLAY"] = "wayland-0"
            os.environ.setdefault("XDG_RUNTIME_DIR", laufzeit)

    from monitor import App
    from webserver import PortBelegt
    try:
        app = App(sim=a.sim, fenster=a.fenster, name=a.name, spielt=not a.zuschauer,
                  schnell=a.schnell, max_runden=max(1, a.runden), ziel=max(1, a.ziel))
    except PortBelegt as e:
        print("FEHLER:", e)
        sys.exit(2)
    try:
        app.lauf()
    except KeyboardInterrupt:
        pass
    finally:
        app.beenden()
        print("Tschuess!")


if __name__ == "__main__":
    main()
