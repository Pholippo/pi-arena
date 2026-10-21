#!/usr/bin/env python3
"""BROWSERSPIELE - Server fuer die Browser-Spiele von PiArena (NINJA-RACE, FLAPPY-PARTY, AUTO-PARTY).

WAS MACHT DIE DATEI?
  Liefert das gerade aktive Spiel (web/ninja.html / web/flappy.html / web/auto.html) aus und haelt die
  gemeinsame Welt: wer spielt mit, wie weit ist jede/r, wer ist im Ziel. Alle spielen gleichzeitig,
  die anderen sieht man als Geister mit Namen. Kein Befehl, nix installieren - nur eine Webseite:
      http://<HOST>:8082            (Pi-Browser, Laptop oder Handy; ?name=Max traegt den Namen ein)
      http://<HOST>:8082/tv         (Zuschauer-Ansicht + START-Knopf fuer Monitor/Beamer)

WIE STARTEN?
  Normalerweise gar nicht: arena/host.py startet diese Datei selbst mit (ausser mit --ohne-web) und
  steuert sie: POST /spiel (welches Spiel), /start (Countdown + Runde), /lobby (Abbruch/Ende).
  Allein (ohne Host):        python3 arena/browserspiele.py [--spiel ninja|flappy|auto]
  Test ohne Netz:            python3 arena/browserspiele.py --selbsttest

NEUES BROWSER-SPIEL DAZUBAUEN:
  1. web/xyz.html anlegen (Vorlage: tools/web-vorlagen/, siehe MITMACHEN.md). Gleiche API: POST /join (name) -> id,
     POST /upd (id, x, y, lebt, ziel) -> Zustand, GET /state. "best" = Weite, "ziel" = Zielzeit in s.
  2. "xyz" in SPIELE unten eintragen und in arena/ablauf.py in WEB_SPIELE (Name + Kurztext) und arena/monitor.py in SPIEL_FARBE.
"""
import json
import os
import random
import secrets
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

# ---------------------------------------------------------------- Einstellungen

PORT = 8082
RUNDE_S = 180          # Standard-Spielzeit (3 Minuten); der Host schickt bei /start ihre eigene Dauer
COUNTDOWN_S = 5        # Countdown nach /start, bevor alle losspielen
SPIELE = ("ninja", "flappy", "auto")  # erlaubte Spiele = Dateinamen ohne .html
FARBEN = ["#ffd23f", "#ff5d8f", "#3bceac", "#4ea8de", "#f77f00", "#a06cd5", "#90be6d",
          "#ef476f", "#06d6a0", "#ffb4a2", "#f9c74f", "#43aa8b"]


class Party:
    def __init__(self):
        self.lock = threading.Lock()
        self.spieler = {}          # id -> dict
        self.phase = "lobby"       # lobby | countdown | spiel | ende
        self.seit = time.time()
        self.seed = random.randint(1, 10 ** 6)
        self.dauer = RUNDE_S       # pro Runde einstellbar (der Host startet z.B. 90 s)

    # ---- Ablauf
    def _tick(self):
        jetzt = time.time()
        if self.phase == "countdown" and jetzt - self.seit >= COUNTDOWN_S:
            self.phase, self.seit = "spiel", jetzt
        elif self.phase == "spiel" and jetzt - self.seit >= self.dauer:
            self.phase, self.seit = "ende", jetzt

    def start(self, dauer=None):
        with self.lock:
            self.dauer = dauer or RUNDE_S
            self.seed = random.randint(1, 10 ** 6)
            for s in self.spieler.values():
                s.update(x=0, y=0, lebt=True, best=0, tode=0, ziel=None)
            self.phase, self.seit = "countdown", time.time()

    def lobby(self):
        with self.lock:
            self.phase, self.seit = "lobby", time.time()

    def rest(self):
        if self.phase == "countdown":
            return max(0.0, COUNTDOWN_S - (time.time() - self.seit))
        if self.phase == "spiel":
            return max(0.0, self.dauer - (time.time() - self.seit))
        return 0.0

    # ---- API
    def join(self, name, sid=""):
        name = "".join(c for c in name if c.isalnum() or c in " _-.!?") .strip()[:14] or "Vogel"
        with self.lock:
            if sid in self.spieler:  # Reload -> gleicher Vogel
                self.spieler[sid]["name"] = name
                return sid
            sid = secrets.token_hex(4)
            self.spieler[sid] = {"name": name, "farbe": FARBEN[len(self.spieler) % len(FARBEN)],
                                 "x": 0.0, "y": 0.0, "lebt": True, "best": 0.0, "tode": 0,
                                 "ziel": None, "gesehen": time.time()}
            return sid

    def update(self, sid, d):
        with self.lock:
            self._tick()
            s = self.spieler.get(sid)
            if s is not None:
                s["gesehen"] = time.time()
                if self.phase == "spiel":
                    try:
                        x = max(0.0, min(10 ** 6, float(d.get("x", 0))))
                        y = max(-50.0, min(700.0, float(d.get("y", 0))))
                    except ValueError:
                        x, y = s["x"], s["y"]
                    lebt = d.get("lebt", "1") == "1"
                    if s["lebt"] and not lebt:
                        s["tode"] += 1
                    s.update(x=x, y=y, lebt=lebt, best=max(s["best"], x))
                    try:  # Ziel erreicht -> Zeit in Sekunden (nur die erste zaehlt)
                        z = float(d.get("ziel", "") or "nan")
                        if z == z and 0 < z <= self.dauer + 5 and s["ziel"] is None:
                            s["ziel"] = round(z, 2)
                    except ValueError:
                        pass
            return self.zustand(sid)

    def zustand(self, sid=""):
        self._tick()
        jetzt = time.time()
        aktiv = [(k, v) for k, v in self.spieler.items() if jetzt - v["gesehen"] < 20]
        liste = [{"id": k, "name": v["name"], "farbe": v["farbe"], "x": round(v["x"], 1),
                  "y": round(v["y"], 1), "lebt": v["lebt"], "best": int(v["best"] // 10), "tode": v["tode"], "ziel": v.get("ziel")}
                 for k, v in aktiv]
        # Wer im Ziel ist, steht vorne (schnellste Zeit), dann nach Weite
        liste.sort(key=lambda p: (p["ziel"] is None, p["ziel"] or 0, -p["best"]))
        return {"phase": self.phase, "rest": round(self.rest(), 2), "seed": self.seed,
                "ich": sid if sid in self.spieler else "", "spieler": liste, "runde_s": self.dauer, "spiel": AKTIV[0]}


HIER = os.path.dirname(os.path.abspath(__file__))
# --spiel ninja -> ninja.html, sonst flappy.html (gleicher Server, gleiche API)
SPIEL = sys.argv[sys.argv.index("--spiel") + 1] if "--spiel" in sys.argv[:-1] else "flappy"
AKTIV = [SPIEL if SPIEL in SPIELE else "flappy"]  # was "/" gerade ausliefert - Wechsel per POST /spiel


def starte_server(party, port=PORT):
    """HTTP-Server im Hintergrund. Port belegt -> OSError (Aufrufer gibt eine klare Meldung aus)."""
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, body, typ="application/json", code=200):
            daten = body if isinstance(body, bytes) else body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", typ)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(daten)))
            self.end_headers()
            try:
                self.wfile.write(daten)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_GET(self):
            u = urlparse(self.path)
            if u.path in ("/", "/tv", "/index.html"):
                try:
                    with open(os.path.join(HIER, "web", f"{AKTIV[0]}.html"), encoding="utf-8") as f:
                        self._send(f.read(), "text/html; charset=utf-8")
                except OSError as e:
                    self._send(f"{AKTIV[0]}.html fehlt: {e}", "text/plain", 500)
            elif u.path == "/state":
                with party.lock:
                    self._send(json.dumps(party.zustand()))
            else:
                self._send("nicht gefunden", "text/plain", 404)

        def do_POST(self):
            u = urlparse(self.path)
            try:
                laenge = min(2048, int(self.headers.get("Content-Length") or 0))
                d = {k: v[0] for k, v in parse_qs(self.rfile.read(laenge).decode("utf-8", "replace")).items()}
            except ValueError:
                return self._send("falsch", "text/plain", 400)
            if u.path == "/join":
                sid = party.join(d.get("name", ""), d.get("id", ""))
                self._send(json.dumps({"id": sid}))
            elif u.path == "/upd":
                self._send(json.dumps(party.update(d.get("id", ""), d)))
            elif u.path == "/start":
                try:
                    dauer = max(20, min(600, int(d.get("dauer", 0)))) if d.get("dauer") else None
                except ValueError:
                    dauer = None
                party.start(dauer)
                self._send('{"ok":true}')
            elif u.path == "/lobby":
                party.lobby()
                self._send('{"ok":true}')
            elif u.path == "/spiel" and d.get("name") in SPIELE:
                AKTIV[0] = d["name"]
                party.lobby()
                self._send('{"ok":true}')
            else:
                self._send("nicht gefunden", "text/plain", 404)

    class Server(ThreadingHTTPServer):
        daemon_threads = True
        request_queue_size = 128
        allow_reuse_address = os.name != "nt"  # Windows wuerde sonst einen belegten Port still "teilen"

        def handle_error(self, request, client_address):
            if isinstance(sys.exc_info()[1], (ConnectionError, TimeoutError)):
                return  # Browser mitten in einer Anfrage zugemacht -> normal, kein Traceback
            super().handle_error(request, client_address)

    srv = Server(("0.0.0.0", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def eigene_ips():
    """IPv4-Adressen dieses Rechners (nur fuer die Startmeldung)."""
    try:
        out = subprocess.run(["hostname", "-I"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=2).stdout
        ips = [ip for ip in out.split() if "." in ip]
        if ips:
            return ips
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        return [ip for ip in socket.gethostbyname_ex(socket.gethostname())[2] if not ip.startswith("127.")]
    except OSError:
        return []


def selbsttest():
    """Server + 8 simulierte Spieler ueber echtes HTTP, verkuerzte Runde."""
    import urllib.request
    global RUNDE_S, COUNTDOWN_S
    RUNDE_S, COUNTDOWN_S = 4, 1
    p = Party()
    srv = starte_server(p, 8092)
    url = "http://127.0.0.1:8092"

    def post(pfad, **d):
        body = "&".join(f"{k}={v}" for k, v in d.items()).encode()
        with urllib.request.urlopen(url + pfad, data=body, timeout=3) as r:
            return json.loads(r.read())

    with urllib.request.urlopen(url + "/", timeout=3) as r:
        assert b"<canvas" in r.read(), "Seite fehlt"
    ids = [post("/join", name=f"Bot{i}")["id"] for i in range(8)]
    assert post("/join", name="Bot0neu", id=ids[0])["id"] == ids[0], "Reload-Join kaputt"
    post("/start")
    t0 = time.time()
    while True:
        for i, sid in enumerate(ids):
            x = max(0.0, (time.time() - t0 - 1) * 100 * (i + 1))
            st = post("/upd", id=sid, x=f"{x:.1f}", y="300", lebt="0" if i == 3 else "1")
        if st["phase"] == "ende":
            break
        time.sleep(0.1)
    assert st["spieler"][0]["name"] == "Bot7", st["spieler"][:2]
    assert len(st["spieler"]) == 8
    for spiel in SPIELE:  # so schaltet der Host um ...
        post("/spiel", name=spiel)
        with urllib.request.urlopen(url + "/", timeout=3) as r:
            assert b"<canvas" in r.read(), spiel + ".html fehlt"
    post("/start", dauer=30)
    assert post("/upd", id=ids[0])["phase"] == "countdown"
    post("/lobby")  # ... und so bricht er ab (Moderator ueberspringt)
    assert post("/upd", id=ids[0])["phase"] == "lobby", "/lobby bricht nicht ab"
    srv.shutdown()
    srv.server_close()
    print(f"SELBSTTEST OK: 8 Spieler, Sieger {st['spieler'][0]['name']} mit {st['spieler'][0]['best']} m, "
          f"Phasen lobby->countdown->spiel->ende, Umschalten {'/'.join(SPIELE)}, Abbruch per /lobby")


def main():
    if "--selbsttest" in sys.argv:
        return selbsttest()
    p = Party()
    try:
        starte_server(p)
    except OSError as e:
        print(f"FEHLER: Port {PORT} ist belegt ({e}).\n"
              f"  Laeuft browserspiele.py schon (z.B. vom Host oder in Thonny)? Dann ist alles gut,\n"
              f"  sonst das andere Programm beenden und nochmal starten.")
        return 2
    print(f"BROWSERSPIELE laufen (aktiv: {AKTIV[0]}):")
    for ip in eigene_ips() or ["127.0.0.1"]:
        print(f"  Spielen:  http://{ip}:{PORT}      Monitor: http://{ip}:{PORT}/tv")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    sys.exit(main() or 0)
