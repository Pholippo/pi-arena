"""WEBSERVER - die Netzwerk-Seite des Hosts (PiArena), Port 8081.

WAS MACHT DIE DATEI?
  - beantwortet alle Anfragen von Schueler-Pis und Handys (/join, /state, /act)
  - liefert das Programm fuer die Schueler-Pis aus:  curl http://HOST:8081/j | python3
    (spieler.py + minispiele.py zu EINER Datei zusammengebaut, Host-Adressen schon eingetragen)
  - liefert die Handy-Seite (arena/web/handy.html) und das Live-Bild des Monitors (/live)
  - findet die eigenen IP-Adressen und ruft jede Sekunde per UDP "PI-ARENA 8081" ins Netz,
    damit Clients den Host auch ohne Adresse finden

WER BENUTZT SIE?  arena/monitor.py (App) startet den Server beim Start des Hosts.
"""
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import spieler as schueler_pi
from einstellungen import PORT, WEB_PORT

HIER = os.path.dirname(os.path.abspath(__file__))
BUNDLE_MARKE = "from minispiele import *"


def spieler_programm(hosts):
    """Das Programm fuer die Schueler-Pis (GET /j) als EINE Datei: In spieler.py wird die Zeile
    'from minispiele import *' durch den Inhalt von minispiele.py ersetzt, dazu die Host-Adressen."""
    with open(os.path.join(HIER, "spieler.py"), encoding="utf-8") as f:
        code = f.read()
    with open(os.path.join(HIER, "minispiele.py"), encoding="utf-8") as f:
        spiele = f.read()
    if spiele.startswith("#!"):
        spiele = spiele.split("\n", 1)[1]  # die Startzeile hat spieler.py schon
    zeilen = code.split("\n")
    marke = [i for i, z in enumerate(zeilen) if z.startswith(BUNDLE_MARKE)]
    if len(marke) != 1:
        raise RuntimeError("spieler.py: Zeile 'from minispiele import *' fehlt oder ist doppelt")
    zeilen[marke[0]] = "# ===== ab hier: minispiele.py (vom Host eingesetzt) =====\n" + spiele.rstrip("\n") + \
        "\n# ===== Ende minispiele.py ====="
    code = "\n".join(zeilen)
    return code.replace("STANDARD_HOSTS = []", f"STANDARD_HOSTS = {hosts!r}", 1)


# ---------------------------------------------------------------- Netzwerk


def netz_art(iface):
    """Beschriftung fuer den Monitor aus dem Schnittstellen-Namen: wlan0 -> WLAN, eth0 -> KABEL."""
    if iface.startswith(("wlan", "wl")):
        return "WLAN"
    if iface.startswith(("eth", "en")):
        return "KABEL"
    return "NETZ"


def netz_adressen():
    """Alle IPv4-Adressen des Hosts als [(art, ip, broadcast)] - WLAN zuerst, dann Kabel, dann Rest.
    Linux: 'ip -4 -o addr' (mit Schnittstellen-Namen). Sonst (Windows-Laptop): Hostname + Standard-Route."""
    gefunden = []
    try:
        out = subprocess.run(["ip", "-4", "-o", "addr", "show"], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=2).stdout
        for iface, ip, brd in re.findall(r"^\d+:\s+(\S+)\s+inet (\d+\.\d+\.\d+\.\d+)/\d+(?:\s+brd (\S+))?", out, re.M):
            gefunden.append((netz_art(iface), ip, brd or None))
    except (OSError, subprocess.SubprocessError):
        pass
    if not gefunden:
        ips = []
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))  # sendet nichts, waehlt nur die Schnittstelle mit der Standard-Route
            ips.append(s.getsockname()[0])
            s.close()
        except OSError:
            pass
        try:
            ips += socket.gethostbyname_ex(socket.gethostname())[2]
        except OSError:
            pass
        gefunden = [("NETZ", ip, None) for ip in dict.fromkeys(ips)]
    reihenfolge = {"WLAN": 0, "KABEL": 1}
    gefunden = [g for g in gefunden if not g[1].startswith(("127.", "169.254."))]  # ohne Loopback/Notfall-Adressen
    gefunden.sort(key=lambda g: reihenfolge.get(g[0], 2))  # sort ist stabil -> sonst Reihenfolge wie gefunden
    return gefunden or [("LOKAL", "127.0.0.1", None)]


def leuchtfeuer(broadcasts, stop):
    """Ruft jede Sekunde 'PI-ARENA 8081' per UDP in alle Netze -> Clients finden den Host von selbst."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    nachricht = f"PI-ARENA {PORT}".encode()
    ziele = ["255.255.255.255", "127.0.0.1"] + [b for b in broadcasts if b]
    while not stop.is_set():
        for z in ziele:
            try:
                s.sendto(nachricht, (z, schueler_pi.SUCH_PORT))
            except OSError:
                pass  # z.B. kein Netz -> naechste Sekunde nochmal
        stop.wait(1.0)
    s.close()


# ---------------------------------------------------------------- Handy-Seite (arena/web/handy.html)

ERSATZ_SEITE = """<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width">
<body style="font-family:sans-serif;background:#111;color:#eee;padding:20px"><h1>PI-ARENA</h1>
<p>web/handy.html fehlt am Host - Handy-Spiel gerade nicht moeglich.</p></body>"""


# /live = Spiegel des Monitors im Browser (z.B. Beamer). Das JPEG wird nur gebaut, solange jemand zuschaut.
TV = {"jpg": b"", "t": 0.0, "gefragt": 0.0}
TV_SEITE = """<!doctype html><html lang=de><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>PI-ARENA Live</title>
<style>html,body{margin:0;height:100%;background:#000}img{width:100vw;height:100vh;object-fit:contain;display:block}</style>
</head><body><img id=b alt="PI-ARENA live"><script>
const b=document.getElementById('b');let n=0;
function lade(){const i=new Image();i.onload=()=>{b.src=i.src;setTimeout(lade,350)};
i.onerror=()=>setTimeout(lade,1000);i.src='/tv.jpg?'+(n++)}lade();
b.onclick=()=>document.documentElement.requestFullscreen&&document.documentElement.requestFullscreen();
</script></body></html>"""


# /tv = Weiterleitung zum Browser-Spiel (aeltere Anleitung/Lesezeichen zeigen auf :8081/tv)
TV_WEITER = """<!doctype html><html lang=de><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>PI-ARENA Spiel</title></head>
<body style="font-family:sans-serif;background:#111;color:#eee;padding:20px">
<script>location.replace(location.protocol+'//'+location.hostname+':WEBPORT/')</script>
<p>Weiter zum Spiel: <a id=l href="/" style="color:#ffd23f">Port WEBPORT</a> (Live-Bild: <a href="/live" style="color:#aaa">/live</a>)</p>
<script>var l=document.getElementById('l');l.href=location.protocol+'//'+location.hostname+':WEBPORT/';l.textContent=l.href</script>
<noscript><p>Ohne JavaScript: Adresse dieses Hosts mit <b>:WEBPORT</b> statt :8081 oeffnen.</p></noscript>
</body></html>""".replace("WEBPORT", str(WEB_PORT))


def handy_seite():
    try:
        with open(os.path.join(HIER, "web", "handy.html"), encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ERSATZ_SEITE


def starte_web(app):
    show = app.show

    class H(BaseHTTPRequestHandler):
        timeout = 10  # haengende Verbindungen nicht ewig festhalten

        def log_message(self, *a):
            pass

        def _antwort(self, body, typ, code=200):
            daten = body if isinstance(body, bytes) else body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", typ)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(daten)))
            self.end_headers()
            self.wfile.write(daten)

        def _json(self, obj):
            self._antwort(json.dumps(obj), "application/json")

        def do_GET(self):
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            if u.path == "/state":
                self._json(show.api_state(q.get("id", "")))
            elif u.path == "/j":  # curl http://HOST:8081/j | python3
                adresse = (self.headers.get("Host") or "").rsplit(":", 1)[0]  # die Adresse aus dem curl-Befehl
                self._antwort(app.client_code(adresse), "text/x-python; charset=utf-8")
            elif u.path in ("/", "/index.html"):
                self._antwort(handy_seite(), "text/html; charset=utf-8")
            elif u.path == "/tv.jpg":
                TV["gefragt"] = time.monotonic()
                self._antwort(TV["jpg"] or b"", "image/jpeg")
            elif u.path == "/tv":  # schon offene /tv-Seiten: F5 -> direkt ins Browser-Spiel auf 8082
                self._antwort(TV_WEITER, "text/html; charset=utf-8")
            elif u.path == "/live":  # alte Spiegel-Seite des Monitors
                self._antwort(TV_SEITE, "text/html; charset=utf-8")
            else:
                self._antwort("nicht gefunden", "text/plain", 404)

        def do_POST(self):
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            try:
                laenge = min(4096, int(self.headers.get("Content-Length") or 0))  # nie riesige Bodies lesen
                body = {k: v[0] for k, v in parse_qs(self.rfile.read(laenge).decode("utf-8", "replace")).items()}
                if u.path == "/join":
                    self._json(show.api_join(body.get("name", ""), body.get("art", "web"), body.get("kennung", "")))
                elif u.path == "/act":
                    self._json(show.api_act(q.get("id", "") or body.get("id", ""), body.get("action", ""),
                                            body.get("value", ""), body))
                else:
                    self._antwort("nicht gefunden", "text/plain", 404)
            except (ValueError, KeyError) as e:  # kaputte Anfrage -> 400, Server laeuft weiter
                self._antwort(f"falsche Anfrage: {e}", "text/plain", 400)

    class Server(ThreadingHTTPServer):
        daemon_threads = True
        request_queue_size = 128  # 30 Pis + Handys gleichzeitig
        allow_reuse_address = os.name != "nt"  # Windows wuerde sonst einen belegten Port still "teilen"

        def handle_error(self, request, client_address):
            if isinstance(sys.exc_info()[1], (ConnectionError, TimeoutError)):
                return  # Handy/Pi mitten in einer Anfrage weg -> normal, kein Traceback
            super().handle_error(request, client_address)

    try:
        srv = Server(("0.0.0.0", PORT), H)
    except OSError as e:
        raise PortBelegt(f"Port {PORT} ist belegt ({e}).\n"
                         f"  Laeuft PiArena schon (anderes Terminal, Thonny, Autostart)? Dann dort beenden\n"
                         f"  (Strg+C bzw. Stop) und nochmal starten. Pruefen am Pi: ss -ltnp | grep {PORT}") from None
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


class PortBelegt(Exception):
    """Der Host kann auf seinem Port nicht lauschen - ohne Webserver kann niemand mitspielen."""
