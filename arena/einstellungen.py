"""EINSTELLUNGEN fuer den Host (PiArena) - hier darfst du drehen.

Alles, was man oft aendern will, steht an dieser einen Stelle:
Rundenzahl, Siegpunkte, Dauer der Browser-Runden und welche Spiele gerade NICHT mitspielen.
Einige Werte lassen sich auch beim Start setzen (python3 arena/host.py --help).
"""
import spieler as schueler_pi

PORT = schueler_pi.HOST_PORT  # 8081: Handy-Seite, Download /j, Spiel-API fuer die Pis (steht in spieler.py)
WEB_PORT = schueler_pi.WEB_PORT  # 8082: Browser-Spiele (arena/browserspiele.py)

MAX_RUNDEN = 10               # letzte Runde = Finale mit doppelten Punkten (--runden)
ZIEL_PUNKTE = 10              # wer das zuerst hat, gewinnt (10 LEDs) (--ziel)
PLATZ_PUNKTE = [3, 2, 1]      # Punkte fuer Platz 1/2/3
MAX_SPIELER = 60
WEB_DAUER_S = 90              # Spielzeit einer Browser-Runde in s (--web-dauer)
HOST_BROWSER_VORLAUF_S = 10   # so viele s vor Spielstart geht am Host der Browser auf (vorher: QR/URL sichtbar)

# Spiele, die der Host NICHT auswaehlt. Der Code bleibt erhalten - zum Aktivieren einfach den Namen loeschen.
# "morse" ist das Uebungs-Beispiel aus minispiele.py.
DEAKTIVIERT = {"binaer", "simon", "morse"}

# Wird beim Start gesetzt, nicht hier aendern:
WEB_BASIS = f"http://127.0.0.1:{WEB_PORT}"  # wo browserspiele.py laeuft; None = keine Browser-Runden (--ohne-web)
NUR = None                    # --nur morse,tap -> NUR diese Spiele (auch wenn sie in DEAKTIVIERT stehen)
