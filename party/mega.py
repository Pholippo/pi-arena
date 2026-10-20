#!/usr/bin/env python3
"""MEGA-PARTY - Host fuer das Klassen-Battle mit der geloeteten Raspberry-Pi-Platine.

WAS MACHT DIE DATEI?
  Jede/r in der Klasse hat einen eigenen Pi mit derselben Platine und spielt JEDER GEGEN JEDEN.
    - Host   = dieses Programm auf dem Pi mit Monitor/Beamer: Lobby mit QR-Code + Client-Befehl,
               Rundenansage, Countdown, Live-Rangliste, Siegerehrung und eine "Live-GPIO"-Ecke,
               die den echten Pin-Zustand (LEDs, Taster, Buzzer) als Schaltbild zeigt.
    - Client = mega_client.py auf jedem Schueler-Pi (liefert der Host selbst aus, siehe /j):
               3 Taster = Eingabe, Buzzer = Rueckmeldung, 10 LEDs = eigener Score.
    - Ohne Pi: Handy-Browser als virtuelle Platine (QR-Code scannen).
    - Browser-Runden (NINJA/FLAPPY/AUTO) laufen auf webspiele.py (Port 8082) - startet der Host selbst mit.

  Ablauf: Lobby -> Ansage + Countdown -> alle spielen gleichzeitig dasselbe Minispiel ->
  Auswertung (Platz 1/2/3 = 3/2/1 Punkte, Finale doppelt) -> ... bis jemand ZIEL_PUNKTE hat
  oder alle Runden gespielt sind -> Siegerehrung.

  Der Moderator (wer am Host sitzt) spielt selbst mit. Seine Taster steuern, solange keine Board-Runde laeuft:
    MITTE = Start / Weiter    RECHTS = Runde ueberspringen (auch Browser-Runden)    LINKS = Demo-Bots an/aus (Lobby)
  Tastatur am Host: Leertaste = Mitte, Pfeil links/rechts, N = Runde ueberspringen, A S D = eigene Taster, ESC.

WIE STARTEN?
  python3 mega.py                    am Pi (Vollbild, Moderator spielt mit, Name = Hostname)
  python3 mega.py --name Max         eigener Name fuer den Moderator
  python3 mega.py --zuschauer        Moderator spielt nicht mit (nur Zuschauer-Ansicht in Browser-Runden)
  python3 mega.py --ohne-web         ohne Browser-Runden (webspiele.py wird nicht gestartet)
  python3 mega.py --sim --fenster    am Laptop ohne GPIO, im Fenster
  python3 mega.py --selbsttest --sim Host + 5 echte Client-Prozesse + Handy + Bot spielen eine ganze Partie
  Schueler-Pis: curl http://<HOST-IP>:8081/j | python3   (steht gross in der Lobby)

NEUES MINISPIEL DAZUBAUEN:
  Board-Spiel   -> in mega_client.py (Anleitung oben dort), hier nur Farbe in SPIEL_FARBE.
  Browser-Spiel -> xyz.html + Eintrag in webspiele.SPIELE (Anleitung dort) und hier in WEB_SPIELE + SPIEL_FARBE.
  Spiel voruebergehend raus: Key in DEAKTIVIERT eintragen (Code bleibt).

AUFBAU DIESER DATEI (von oben nach unten):
  Einstellungen -> Rundentypen -> Netzwerk -> Browser-Spiele (webspiele.py) -> Show (Spielablauf, ohne Grafik)
  -> HTTP-Server (Port 8081) -> Grafik-Helfer -> App (Monitor, Moderator, Bots) -> Selbsttest -> main()
"""
import argparse
import json
import math
import os
import queue
import random
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import pygame  # noqa: E402

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HIER)
import mega_client as mc  # noqa: E402  (Platine, Minispiele, Client-Logik - alles an einer Stelle)

# ================================================================ EINSTELLUNGEN (hier anpassen)

PORT = mc.HOST_PORT           # 8081: Handy-Seite, Client-Download /j, Spiel-API fuer die Pis
WEB_PORT = mc.WEB_PORT        # 8082: Browser-Spiele (webspiele.py)
MAX_RUNDEN = 10               # letzte Runde = Finale mit doppelten Punkten (--runden)
ZIEL_PUNKTE = 10              # wer das zuerst hat, gewinnt (10 LEDs) (--ziel)
WEB_DAUER_S = 90              # Spielzeit einer Browser-Runde in s (--web-dauer)
WEB_BASIS = f"http://127.0.0.1:{WEB_PORT}"  # wo webspiele.py laeuft; None = Browser-Runden aus (--ohne-web)
DEAKTIVIERT = {"binaer", "simon"}  # aus der Rotation genommen (Code bleibt, Keys bleiben fuer alte Clients)
PLATZ_PUNKTE = [3, 2, 1]      # Punkte fuer Platz 1/2/3
MAX_SPIELER = 60
HOST_BROWSER_VORLAUF_S = 10   # so viele s vor Spielstart geht am Host der Browser auf (vorher: QR/URL sichtbar)

B, H = 1280, 720
WEISS, GRAU, DUNKEL = (240, 244, 255), (130, 130, 160), (60, 60, 85)
ROT, GRUEN, GELB, GOLD = (255, 60, 60), (60, 230, 120), (255, 220, 40), (255, 190, 40)
CYAN, PINK = (0, 229, 255), (255, 43, 214)
SPIEL_FARBE = {"reaktion": GELB, "lauflicht": CYAN, "simon": GRUEN, "tap": (255, 130, 40),
               "piep": PINK, "binaer": (170, 120, 255),
               "ninja": (255, 90, 60), "flappy": (255, 210, 63), "auto": (80, 200, 255)}

# ================================================================ Rundentypen
# Board-Spiele stehen in mc.SPIELE (mega_client.py). Browser-Spiele laufen auf webspiele.py.
# Pi-Clients bekommen in Browser-Runden KEINE "runde" (nur die Phase) -> sie zeigen ihren Score
# und oeffnen den Browser (alte Clients ohne Browser-Funktion warten einfach).
WEB_SPIELE = {
    "ninja": {"name": "NINJA-RACE", "kurz": "Im Browser: wer ist am schnellsten im Ziel / kommt am weitesten?"},
    "flappy": {"name": "FLAPPY-PARTY", "kurz": "Im Browser: flattern! Wer am weitesten fliegt, gewinnt."},
    "auto": {"name": "AUTO-PARTY", "kurz": "Im Browser: Rennen fahren! Wer am weitesten kommt, gewinnt."},
}
for _v in WEB_SPIELE.values():  # Wertung: Platz in der Browser-Rangliste (0 = bester) -> "tief" ist besser
    _v.update(handy=True, besser="tief", trost=0, tasten=("", "", ""), web=True)


def info_von(key):
    """Spiel-Info fuer Board- und Browser-Runden."""
    return WEB_SPIELE.get(key) or mc.SPIELE[key]


def ist_web(r):
    return bool(r) and r["spiel"] in WEB_SPIELE


def rotation():
    """Spiele, die der Host auswaehlt: alle Board-Spiele ausser DEAKTIVIERT + Browser-Spiele mit .html-Datei."""
    keys = [k for k in mc.SPIELE if k not in DEAKTIVIERT]
    if WEB_BASIS:
        keys += [k for k in WEB_SPIELE if k not in DEAKTIVIERT and os.path.exists(os.path.join(HIER, f"{k}.html"))]
    return keys


# ================================================================ Browser-Spiele (webspiele.py, Port 8082)


def web_anfrage(pfad, body=None, timeout=1.5):
    """GET (body None) / POST an webspiele.py. -> dict oder None (nie Exception)."""
    if not WEB_BASIS:
        return None
    try:
        daten = urllib.parse.urlencode(body).encode() if body is not None else None
        with urllib.request.urlopen(WEB_BASIS + pfad, data=daten, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


_WEB_AUFTRAEGE = queue.Queue()


def _web_sender():
    """Arbeitet die POSTs der Reihe nach ab: /spiel, /start, /lobby kommen nie vertauscht an
    (sonst koennte ein /start NACH dem /lobby des Ueberspringens ankommen und das Spiel laeuft weiter)."""
    while True:
        pfad, body = _WEB_AUFTRAEGE.get()
        if web_anfrage(pfad, body, timeout=3) is None:
            print(f"Browser-Spiel: POST {pfad} {body} fehlgeschlagen", flush=True)


threading.Thread(target=_web_sender, daemon=True).start()


def web_post_hinten(pfad, body):
    """POST im Hintergrund, damit Monitor/Lock nie auf das Netz warten."""
    _WEB_AUFTRAEGE.put((pfad, body))


def port_frei(port):
    """Kann dieser Rechner auf dem TCP-Port lauschen (also: laeuft dort noch nichts)?"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("0.0.0.0", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def starte_webspiele():
    """Startet webspiele.py als Unterprozess, falls WEB_BASIS lokal ist und dort noch nichts laeuft.
    -> Popen oder None. Klappt es nicht, gibt es eben keine Browser-Runden (nie ein Absturz)."""
    ziel = urlparse(WEB_BASIS or "")
    if ziel.hostname not in ("127.0.0.1", "localhost") or ziel.port != WEB_PORT:
        return None  # fremder Server per --web-server -> der laeuft woanders
    if web_anfrage("/state") is not None:
        print(f"Browser-Spiele: webspiele.py laeuft schon auf Port {WEB_PORT}, wird mitbenutzt.")
        return None
    pfad = os.path.join(HIER, "webspiele.py")
    if not os.path.exists(pfad):
        print(f"Browser-Spiele aus: {pfad} fehlt -> nur Board-Runden.")
        return None
    if not port_frei(WEB_PORT):
        print(f"Browser-Spiele aus: Port {WEB_PORT} ist von einem anderen Programm belegt -> nur Board-Runden.")
        return None
    try:
        proc = subprocess.Popen([sys.executable, pfad], cwd=HIER, stdin=subprocess.DEVNULL)
    except OSError as e:
        print(f"Browser-Spiele aus: webspiele.py startet nicht ({e}).")
        return None
    print(f"Browser-Spiele: webspiele.py gestartet (Port {WEB_PORT}).")
    return proc


def _norm(name):
    return " ".join(str(name).split()).lower()


def web_zuordnung(browser, spieler):
    """Browser-Ergebnisliste (sortiert) -> [(sid, eintrag)] in Platz-Reihenfolge.
    Exakt (case-insensitive, getrimmt), sonst eindeutiger Praefix-Match. Unbekannte Namen fallen raus."""
    namen = {sid: _norm(sp.name) for sid, sp in spieler.items()}
    vergeben, out = set(), []
    for e in browser:
        if e.get("ziel") is None and not e.get("best"):
            continue  # nicht gespielt
        n = _norm(e.get("name", ""))
        if not n:
            continue
        frei = {sid: m for sid, m in namen.items() if sid not in vergeben}
        treffer = [sid for sid, m in frei.items() if m == n]
        if not treffer:
            treffer = [sid for sid, m in frei.items() if m.startswith(n) or n.startswith(m)]
        if len(treffer) == 1:
            vergeben.add(treffer[0])
            out.append((treffer[0], e))
    return out
ART_FARBE = {"pi": WEISS, "sim": WEISS, "web": (120, 200, 255), "bot": GRAU}
BOT_NAMEN = ["Bot Ohm", "Bot Volt", "Bot Ampere", "Bot Tesla", "Bot Watt", "Bot Hertz"]
MENU_LIED = mc.lied("C4 E4 G4 E4 A3 C4 E4 C4 F3 A3 C4 A3 G3 B3 D4 G4", 0.17)
T_ANSAGE = mc.lied("C5 E5 G5 C6 G5 C6:2", 0.08)
T_RUNDE = mc.lied("C6 E6 G6 C7:3", 0.06)


def sauberer_name(name):
    name = "".join(c for c in str(name) if c.isalnum() or c in " _-.").strip()
    return name[:12] or "Spieler"


# ---------------------------------------------------------------- QR-Code (Baustein qrgen.py, zur Laufzeit geladen)


def qr_bild(text, groesse):
    """QR-Code als pygame-Surface (weiss mit 4 Modulen Rand). Fehlt qrgen.py -> Exception -> URL-Text."""
    import qrgen
    m = qrgen.qr_matrix(text)
    n = len(m) + 8
    px = max(2, groesse // n)
    s = pygame.Surface((n * px, n * px))
    s.fill((255, 255, 255))
    for r, zeile in enumerate(m):
        for c, an in enumerate(zeile):
            if an:
                s.fill((0, 0, 0), ((c + 4) * px, (r + 4) * px, px, px))
    return s


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
    """Ruft jede Sekunde 'MEGA-PARTY 8081' per UDP in alle Netze -> Clients finden den Host von selbst."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    nachricht = f"MEGA-PARTY {PORT}".encode()
    ziele = ["255.255.255.255", "127.0.0.1"] + [b for b in broadcasts if b]
    while not stop.is_set():
        for z in ziele:
            try:
                s.sendto(nachricht, (z, mc.SUCH_PORT))
            except OSError:
                pass  # z.B. kein Netz -> naechste Sekunde nochmal
        stop.wait(1.0)
    s.close()


# ---------------------------------------------------------------- Spiel-Logik (ohne Grafik, thread-sicher)


class Spieler:
    def __init__(self, sid, name, art, kennung):
        self.id, self.name, self.art, self.kennung = sid, name, art, kennung
        self.punkte = 0
        self.gewinn = 0  # Punkte aus der letzten Runde
        self.platz = None
        self.runden = 0  # Runden mit abgegebenem Ergebnis
        self.kontakt = time.monotonic()

    def aktiv(self):
        return time.monotonic() - self.kontakt < 5


class Show:
    """Lobby -> ansage -> laeuft -> auswertung -> ... -> sieger. Alle API-Aufrufe kommen aus Fremd-Threads."""

    def __init__(self, schnell=False, max_runden=MAX_RUNDEN, ziel=ZIEL_PUNKTE):
        self.lock = threading.RLock()
        self.spieler = {}
        self.ANSAGE = 5.0 if schnell else 8.0
        self.WEB_ANSAGE = 10.0 if schnell else 25.0  # Zeit, um die Browser-Seite zu oeffnen + Namen einzugeben
        self.web_stand, self.web_ok, self.web_kontakt = None, False, 0.0
        self.web_hinweis, self.web_hinweis_t = "", 0.0
        self.web_adressen = []  # fuer den Text auf der Handy-Seite
        self.web_aufgeraeumt = 0.0  # letztes Nachschicken von /lobby
        self.AUSWERTUNG = 3.5 if schnell else 10.0
        self.max_runden, self.ziel = max_runden, ziel
        self.rng = random.Random()
        self.ereignis = None  # Rueckruf fuer Monitor/Sound bei Zustandswechsel
        self.bots_umschalten = None
        self.reset()

    def reset(self):
        with self.lock:
            if getattr(self, "zustand", "") in ("ansage", "laeuft") and ist_web(getattr(self, "runde", None)):
                web_post_hinten("/lobby", {})  # ESC mitten in einer Browser-Runde
            self.zustand, self.seit = "lobby", time.monotonic()
            self.nr = 0
            self.runde = None
            self.ergebnisse = {}
            self.web = {}
            self.teilnehmer = set()
            self.rangliste = []
            self.sieger_id = None
            self.plan = []
            self.gespielt = []
            self.uebersprungen = False
            for sp in self.spieler.values():
                sp.punkte, sp.gewinn, sp.platz = 0, 0, None
            if self.ereignis:
                self.ereignis("lobby")

    def _wechsel(self, z):
        self.zustand, self.seit = z, time.monotonic()
        if self.ereignis:
            self.ereignis(z)

    # ---- API (HTTP-Clients, Handy- und Bot-Clients)
    def api_join(self, name, art, kennung):
        name = sauberer_name(name)
        art = art if art in ("pi", "web", "bot", "sim") else "web"
        kennung = str(kennung)[:80]
        with self.lock:
            for sp in self.spieler.values():
                if kennung and sp.kennung == kennung:  # gleicher Pi kommt zurueck -> Score bleibt
                    sp.kontakt = time.monotonic()
                    return {"id": sp.id, "name": sp.name}
            if len(self.spieler) >= MAX_SPIELER:
                return {"fehler": "Spiel ist voll"}
            vergeben = {sp.name.lower() for sp in self.spieler.values()}
            basis, i = name, 2
            while name.lower() in vergeben:
                name = f"{basis[:10]}{i}"
                i += 1
            sid = secrets.token_hex(4)
            self.spieler[sid] = Spieler(sid, name, art, kennung)
            return {"id": sid, "name": name}

    PHASE = {"lobby": "lobby", "ansage": "countdown", "laeuft": "round", "auswertung": "result", "sieger": "done"}

    def api_state(self, sid):
        """GET /state - Format der Handy-Seite; Pi-Clients bekommen unter "pi" die Spieldaten dazu."""
        with self.lock:
            sp = self.spieler.get(sid)
            if sp is None:
                return {"neu": 1, "error": "unbekannte id - bitte neu beitreten"}
            jetzt = time.monotonic()
            sp.kontakt = jetzt
            z, r = self.zustand, self.runde
            if sp.art == "web" and z == "laeuft":
                self._web_abschluss(jetzt)
            frist = {"ansage": r["start"] if r else 0, "laeuft": r["start"] + r["dauer"] if r else 0,
                     "auswertung": self.seit + self.AUSWERTUNG}.get(z, 0)
            d = {"phase": self.PHASE[z], "round": self.nr,
                 "round_name": info_von(r["spiel"])["name"] if r and z != "lobby" else "",
                 "instruction": self._text(sp), "your_score": sp.punkte, "max_score": self.ziel,
                 "board": [{"name": s.name, "score": s.punkte} for s in
                           sorted(self.spieler.values(), key=lambda s: -s.punkte)[:30]],
                 "server_ms": int(jetzt * 1000), "deadline_ms": int(frist * 1000)}
            if r and r["spiel"] == "reaktion" and z in ("ansage", "laeuft"):
                d["flash"] = self._blitz_jetzt(jetzt) if z == "laeuft" else False
            if sp.art != "web":
                pi = {"text": d["instruction"], "punkte": sp.punkte, "platz": sp.platz, "nr": self.nr,
                      "gewinn": sp.gewinn if z in ("auswertung", "sieger") else 0, "sieger": self.sieger_id == sid}
                # Browser-Runde: KEINE "runde" an die Pis - alte Clients kennen den Key nicht; ohne "runde"
                # bleiben sie im Warte-Modus und zeigen ihren Score (geprueft mit dem echten mega_client.py).
                if r and z in ("ansage", "laeuft") and not ist_web(r):
                    pi["runde"] = {k: r[k] for k in ("rid", "nr", "spiel", "seed", "param", "finale")}
                    pi["runde"]["start_in"] = round(r["start"] - jetzt, 3)
                d["pi"] = pi
            return d

    def api_act(self, sid, action, value, extra):
        """POST /act - Pi: action=answer mit rid/ok/text = fertiges Ergebnis. Handy: tap/press/answer."""
        with self.lock:
            sp = self.spieler.get(sid)
            if sp is None:
                return {"ok": False, "error": "unbekannte id"}
            if sp.art != "web":
                if action == "answer" and "rid" in extra:
                    self.api_ergebnis(sid, int(extra["rid"]), float(value), str(extra.get("ok")) in ("1", "True"),
                                      extra.get("text", ""))
                return {"ok": True}
            self._web_aktion(sp, action, str(value))
            return {"ok": True}

    def api_ergebnis(self, sid, rid, wert, ok, text):
        """Fertiges Ergebnis eines Pi-Clients (am Board gemessen, ohne Netzwerk-Verzoegerung)."""
        if not math.isfinite(wert):
            raise ValueError("wert")
        with self.lock:
            r = self.runde
            if r and rid == r["rid"] and self.zustand in ("ansage", "laeuft") and sid not in self.ergebnisse:
                text = "".join(c for c in str(text) if c.isprintable())[:60]
                self.ergebnisse[sid] = {"wert": wert, "ok": bool(ok), "text": text, "t": time.monotonic()}
                self.teilnehmer.add(sid)

    # ---- Handy-Spieler: Wertung am Host (gleiche Regeln wie am Board)
    def _blitze(self):
        """Blitz-Zeitpunkte fuer Handy-Spieler im Reaktions-Spiel (aus dem Runden-Seed)."""
        r = self.runde
        rr = random.Random(r["seed"] ^ 0x5EED)
        t, out = r["start"], []
        for _ in range(3):
            t += rr.uniform(1.0, 2.8)
            out.append(t)
            t += 1.5 + 0.8
        return out

    def _blitz_jetzt(self, jetzt):
        r = self.runde
        return bool(r and r["spiel"] == "reaktion" and any(f <= jetzt < f + 1.5 for f in self._blitze()))

    def _web_aktion(self, sp, action, value):
        r, jetzt = self.runde, time.monotonic()
        if self.zustand != "laeuft" or not r or sp.id in self.ergebnisse or jetzt < r["start"] or ist_web(r):
            return
        if not mc.SPIELE[r["spiel"]]["handy"]:
            return
        w = self.web.setdefault(sp.id, {"versuche": {}, "taps": 0})
        key = r["spiel"]
        self.teilnehmer.add(sp.id)
        if key == "reaktion" and action in ("press", "tap"):
            blitze = self._blitze()
            for i, f in enumerate(blitze):
                if f <= jetzt < f + 1.5 and value != "early":
                    w["versuche"].setdefault(i, int((jetzt - f) * 1000))
                    break
            else:  # vor dem naechsten Blitz gedrueckt = Fruehstart
                naechster = next((i for i, f in enumerate(blitze) if f > jetzt), None)
                if naechster is not None:
                    w["versuche"].setdefault(naechster, 1000)
        elif key == "tap" and action in ("tap", "press") and jetzt <= r["start"] + 10:
            try:
                w["taps"] += max(1, min(20, int(value or 1)))
            except ValueError:
                w["taps"] += 1
        elif key in ("piep", "binaer") and action == "answer":
            try:
                zahl = int(value.strip())
            except ValueError:
                return
            soll = bin(r["param"]["zahl"]).count("1") if key == "binaer" else r["param"]["n"]
            dt = round(jetzt - r["start"], 2)
            if zahl == soll:  # es gilt die erste Antwort
                self.ergebnisse[sp.id] = {"wert": dt, "ok": True, "text": f"richtig ({soll}) in {dt:.1f} s", "t": jetzt}
            else:
                self.ergebnisse[sp.id] = {"wert": 99, "ok": False, "text": f"{zahl} statt {soll}", "t": jetzt}
        self._web_abschluss(jetzt)

    def _web_abschluss(self, jetzt, alles=False):
        """Fertige Handy-Ergebnisse eintragen (Reaktion nach 3 Blitzen, Tap nach 10 s)."""
        r = self.runde
        if not r:
            return
        for sid, w in self.web.items():
            if sid in self.ergebnisse or sid not in self.spieler:
                continue
            if r["spiel"] == "reaktion" and (alles or jetzt > self._blitze()[-1] + 1.5 or len(w["versuche"]) == 3):
                zeiten = [w["versuche"].get(i, 1500) for i in range(3)]
                schnitt = sum(zeiten) / 3
                self.ergebnisse[sid] = {"wert": round(schnitt), "ok": True, "t": jetzt,
                                        "text": f"{schnitt:.0f} ms (" + "/".join(map(str, zeiten)) + ")"}
            elif r["spiel"] == "tap" and (alles or jetzt > r["start"] + 10.2):
                self.ergebnisse[sid] = {"wert": w["taps"], "ok": w["taps"] > 0, "t": jetzt,
                                        "text": f"{w['taps']} Taps"}

    def _text(self, sp):
        z, r = self.zustand, self.runde
        if z == "lobby":
            return f"Warte auf den Start ({len(self.spieler)} Spieler)"
        if z in ("ansage", "laeuft") and r and ist_web(r):
            adr = self.web_adressen[0] if self.web_adressen else f"Port {WEB_PORT}"
            return f"{info_von(r['spiel'])['name']} im Browser: {adr} - gib deinen MEGA-Namen ein!"
        if z in ("ansage", "laeuft") and r:
            info = mc.SPIELE[r["spiel"]]
            if sp.art == "web":
                if not info["handy"]:
                    return "Diese Runde geht nur mit der Platine - du setzt kurz aus."
                anleitung = {"reaktion": "Reaktion: wenn der Knopf gruen leuchtet, sofort druecken! 3 Blitze.",
                             "tap": "10 Sekunden lang so oft TAPPEN wie moeglich!",
                             "piep": "Wie viele Pieptoene machen die Buzzer im Raum?",
                             "binaer": "Wie viele Einsen hat die Zahl vom Monitor als Binaerzahl?"}
                text = anleitung[r["spiel"]]
                if z == "laeuft" and r["spiel"] == "binaer":
                    text = f"Wie viele Einsen hat {r['param']['zahl']} als Binaerzahl?"
                if z == "laeuft" and r["spiel"] == "tap" and sp.id in self.web:
                    text += f"  ({self.web[sp.id]['taps']} Taps)"
                return text
            if z == "ansage":
                return f"Gleich: {info['name']} - {info['kurz']}"
            return info["name"] + (f"  ZAHL: {r['param']['zahl']}" if r["spiel"] == "binaer" else "")
        if z == "auswertung":
            if self.uebersprungen:
                return "Runde uebersprungen"
            return f"Platz {sp.platz}: +{sp.gewinn} -> {sp.punkte} Punkte" if sp.gewinn else \
                f"Diesmal keine Punkte ({sp.punkte} gesamt)"
        if z == "sieger":
            s = self.spieler.get(self.sieger_id)
            return f"{s.name} gewinnt mit {s.punkte} Punkten!" if s else "Spielende"
        return ""

    # ---- Moderator (Taster am Host / Tastatur)
    def moderator(self, k):
        """MITTE = Start/Weiter, RECHTS = Runde ueberspringen (Board- UND Browser-Runde), LINKS = Demo-Bots."""
        with self.lock:
            z = self.zustand
            if z == "lobby":
                if k == "mitte" and self.spieler:
                    self.starte_runde()
                elif k == "links" and self.bots_umschalten:
                    self.bots_umschalten()
            elif z in ("ansage", "laeuft") and k == "rechts":
                if ist_web(self.runde):
                    web_post_hinten("/lobby", {})
                self.uebersprungen = True
                self.rangliste = []
                for sp in self.spieler.values():
                    sp.gewinn, sp.platz = 0, None
                self._wechsel("auswertung")
            elif z == "auswertung" and k == "mitte":
                self.weiter()
            elif z == "sieger" and k == "mitte":
                self.reset()

    # ---- Ablauf
    def hinweis(self, txt):
        self.web_hinweis, self.web_hinweis_t = txt, time.monotonic()
        print("Hinweis:", txt, flush=True)

    def starte_runde(self):
        with self.lock:
            for _ in range(2):
                if not self.plan:  # jede Runde ein anderes Spiel, alle kommen dran
                    self.plan = rotation()
                    self.rng.shuffle(self.plan)
                    if self.gespielt and self.plan and self.plan[0] == self.gespielt[-1]:
                        self.plan.append(self.plan.pop(0))
                for k in [k for k in self.plan if k in DEAKTIVIERT]:
                    self.plan.remove(k)
                # Browser-Spiele nur, wenn webspiele.py (8082) antwortet - sonst mit Hinweis ueberspringen
                for k in [k for k in self.plan if k in WEB_SPIELE and not self.web_ok]:
                    self.plan.remove(k)
                    self.hinweis(f"{WEB_SPIELE[k]['name']} uebersprungen: Browser-Spiel (Port {WEB_PORT}) nicht erreichbar")
                if self.plan:
                    break
            handys = any(sp.art == "web" and sp.aktiv() for sp in self.spieler.values())
            # Lauflicht/Simon brauchen echte LEDs -> mit Handy-Spielern nur die Handy-tauglichen Spiele
            key = next((k for k in self.plan if info_von(k)["handy"] or not handys), None)
            if key is None:
                key = self.rng.choice([k for k in mc.SPIELE if mc.SPIELE[k]["handy"] and k not in DEAKTIVIERT])
            else:
                self.plan.remove(key)
            info = info_von(key)
            self.nr += 1
            if key in WEB_SPIELE:
                self._starte_web_runde(key, info)
                return
            param = {"dauer": info["dauer"]}
            if key == "binaer":
                param["zahl"] = self.rng.randint(17, 254)
            elif key == "piep":
                param["n"] = self.rng.randint(4, 10)
            self.runde = {"rid": self.nr * 1000 + self.rng.randint(0, 999), "nr": self.nr, "spiel": key,
                          "seed": self.rng.randint(1, 10 ** 9), "param": param, "finale": self.nr == self.max_runden,
                          "start": time.monotonic() + self.ANSAGE, "dauer": info["dauer"]}
            self.ergebnisse = {}
            self.web = {}
            self.teilnehmer = {sid for sid, sp in self.spieler.items() if sp.aktiv()
                               and (sp.art != "web" or info["handy"])}
            self.uebersprungen = False
            self.gespielt.append(key)
            for sp in self.spieler.values():
                sp.gewinn, sp.platz = 0, None
            self._wechsel("ansage")

    def _starte_web_runde(self, key, info):
        """Browser-Runde: webspiele.py auf das Spiel umschalten; /start kommt 5 s vor Ende der Ansage
        (webspiele.py zaehlt selbst 5 s runter) -> Spielstart = Ende der Ansage."""
        dauer = max(20, min(600, int(WEB_DAUER_S)))
        self.runde = {"rid": self.nr * 1000 + self.rng.randint(0, 999), "nr": self.nr, "spiel": key,
                      "seed": self.rng.randint(1, 10 ** 9), "param": {"dauer": dauer}, "finale": self.nr == self.max_runden,
                      "start": time.monotonic() + max(6.0, self.WEB_ANSAGE), "dauer": dauer,
                      "gestartet": False, "lief": False}
        self.ergebnisse, self.web, self.teilnehmer = {}, {}, set()
        self.web_stand = None  # alten Stand vergessen
        self.uebersprungen = False
        self.gespielt.append(key)
        for sp in self.spieler.values():
            sp.gewinn, sp.platz = 0, None
        web_post_hinten("/spiel", {"name": key})
        self._wechsel("ansage")

    def _web_update(self, z, r, jetzt):
        """Ablauf einer Browser-Runde (aus update(), unter Lock). Netz-Aufrufe nur im Hintergrund."""
        if not self.web_ok and jetzt - max(self.web_kontakt, self.seit) > 6:
            web_post_hinten("/lobby", {})
            self.hinweis(f"{info_von(r['spiel'])['name']} abgebrochen: Port {WEB_PORT} antwortet nicht")
            self.uebersprungen = True
            self.rangliste = []
            self._wechsel("auswertung")
            return
        st = self.web_stand or {}
        if z == "ansage":
            if not r["gestartet"] and jetzt >= r["start"] - 5.0:
                r["gestartet"] = True
                web_post_hinten("/start", {"dauer": r["dauer"]})
            if jetzt >= r["start"]:
                self._wechsel("laeuft")
            return
        if r["gestartet"] and st.get("phase") in ("countdown", "spiel"):
            r["lief"] = True
        if (r["lief"] and st.get("phase") == "ende") or jetzt > r["start"] + r["dauer"] + 10:
            self.ergebnisse = {}
            for i, (sid, e) in enumerate(web_zuordnung(st.get("spieler", []), self.spieler)):
                txt = f"Ziel in {e['ziel']:.1f} s" if e.get("ziel") is not None else f"{e.get('best', 0)} m"
                self.ergebnisse[sid] = {"wert": i, "ok": True, "text": txt + f"  ({e.get('name', '')})"[:40],
                                        "t": jetzt}
                self.teilnehmer.add(sid)
            self.werte_aus()

    def web_poller(self, stop):
        """Holt laufend GET /state von webspiele.py (Hintergrund-Thread, App startet ihn)."""
        while not stop.is_set():
            with self.lock:
                aktiv = ist_web(self.runde) and self.zustand in ("ansage", "laeuft")
            st = web_anfrage("/state", timeout=1.5)
            with self.lock:
                if isinstance(st, dict) and "phase" in st:
                    self.web_stand, self.web_ok, self.web_kontakt = st, True, time.monotonic()
                else:
                    self.web_ok = False
            stop.wait(0.5 if aktiv else 2.0)

    def werte_aus(self):
        r = self.runde
        self._web_abschluss(time.monotonic(), alles=True)
        info = info_von(r["spiel"])
        faktor = 2 if r["finale"] else 1
        gueltig = [(sid, e) for sid, e in self.ergebnisse.items() if e["ok"] and sid in self.spieler]
        gueltig.sort(key=lambda x: (x[1]["wert"] if info["besser"] == "tief" else -x[1]["wert"], x[1]["t"]))
        self.rangliste = []
        for i, (sid, e) in enumerate(gueltig):
            sp = self.spieler[sid]
            pkt = (PLATZ_PUNKTE[i] if i < len(PLATZ_PUNKTE) else info["trost"]) * faktor
            sp.punkte += pkt
            sp.gewinn, sp.platz = pkt, i + 1
            sp.runden += 1
            self.rangliste.append({"name": sp.name, "art": sp.art, "text": e["text"], "pkt": pkt, "platz": i + 1})
        for sid, e in self.ergebnisse.items():
            if not e["ok"] and sid in self.spieler:
                sp = self.spieler[sid]
                sp.runden += 1
                self.rangliste.append({"name": sp.name, "art": sp.art, "text": e["text"], "pkt": 0, "platz": None})
        self._wechsel("auswertung")

    def weiter(self):
        with self.lock:
            beste = max(self.spieler.values(), key=lambda s: (s.punkte, -(s.platz or 999)), default=None)
            if beste and (beste.punkte >= self.ziel or self.nr >= self.max_runden):
                self.sieger_id = beste.id
                self._wechsel("sieger")
            else:
                self.starte_runde()

    def update(self):
        with self.lock:
            jetzt = time.monotonic()
            z, r = self.zustand, self.runde
            if z in ("ansage", "laeuft") and ist_web(r):
                self._web_update(z, r, jetzt)
            elif z == "ansage" and jetzt >= r["start"]:
                self._wechsel("laeuft")
            elif z == "laeuft":
                self._web_abschluss(jetzt)
                offen = [t for t in self.teilnehmer if t not in self.ergebnisse and t in self.spieler
                         and self.spieler[t].aktiv()]
                if (not offen and jetzt > r["start"] + 1.0) or jetzt > r["start"] + r["dauer"] + 4:
                    self.werte_aus()
            elif z == "auswertung" and jetzt - self.seit >= self.AUSWERTUNG:
                self.weiter()
            elif z == "auswertung" and ist_web(r) and (self.web_stand or {}).get("phase") in ("countdown", "spiel") \
                    and jetzt - self.web_aufgeraeumt > 2:
                # Browser-Spiel laeuft nach Ueberspringen/Zeitende noch? -> nochmal /lobby (falls ein POST verloren ging)
                self.web_aufgeraeumt = jetzt
                web_post_hinten("/lobby", {})
            elif z == "lobby":  # wer laenger weg ist, fliegt aus der Lobby
                for sid in [s for s, sp in self.spieler.items() if jetzt - sp.kontakt > 60]:
                    del self.spieler[sid]

    def rangfolge(self):
        with self.lock:
            return sorted(self.spieler.values(), key=lambda s: (-s.punkte, s.name.lower()))


class DirektVerbindung:
    """Wie mc.HttpVerbindung, aber ohne Netzwerk - fuer das Board des Moderators am Host und die Demo-Bots."""

    def __init__(self, show):
        self.show = show

    def join(self, name, art, kennung):
        return self.show.api_join(name, art, kennung)

    def poll(self, sid):
        return self.show.api_state(sid)

    def ergebnis(self, sid, rid, res):
        return self.show.api_act(sid, "answer", res["wert"], {"rid": rid, "ok": int(bool(res["ok"])),
                                                              "text": res["text"]})


# ---------------------------------------------------------------- Handy-Seite (Baustein web_client.html)

ERSATZ_SEITE = """<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width">
<body style="font-family:sans-serif;background:#111;color:#eee;padding:20px"><h1>MEGA-PARTY</h1>
<p>web_client.html fehlt am Host - Handy-Spiel gerade nicht moeglich.</p></body>"""


# /live = Spiegel des Monitors im Browser (z.B. Beamer). Das JPEG wird nur gebaut, solange jemand zuschaut.
TV = {"jpg": b"", "t": 0.0, "gefragt": 0.0}
TV_SEITE = """<!doctype html><html lang=de><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>MEGA-PARTY Live</title>
<style>html,body{margin:0;height:100%;background:#000}img{width:100vw;height:100vh;object-fit:contain;display:block}</style>
</head><body><img id=b alt="MEGA-PARTY live"><script>
const b=document.getElementById('b');let n=0;
function lade(){const i=new Image();i.onload=()=>{b.src=i.src;setTimeout(lade,350)};
i.onerror=()=>setTimeout(lade,1000);i.src='/tv.jpg?'+(n++)}lade();
b.onclick=()=>document.documentElement.requestFullscreen&&document.documentElement.requestFullscreen();
</script></body></html>"""


# /tv = Weiterleitung zum Browser-Spiel (aeltere Anleitung/Lesezeichen zeigen auf :8081/tv)
TV_WEITER = """<!doctype html><html lang=de><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>MEGA-PARTY Spiel</title></head>
<body style="font-family:sans-serif;background:#111;color:#eee;padding:20px">
<script>location.replace(location.protocol+'//'+location.hostname+':WEBPORT/')</script>
<p>Weiter zum Spiel: <a id=l href="/" style="color:#ffd23f">Port WEBPORT</a> (Live-Bild: <a href="/live" style="color:#aaa">/live</a>)</p>
<script>var l=document.getElementById('l');l.href=location.protocol+'//'+location.hostname+':WEBPORT/';l.textContent=l.href</script>
<noscript><p>Ohne JavaScript: Adresse dieses Hosts mit <b>:WEBPORT</b> statt :8081 oeffnen.</p></noscript>
</body></html>""".replace("WEBPORT", str(WEB_PORT))


def handy_seite():
    try:
        with open(os.path.join(HIER, "web_client.html"), encoding="utf-8") as f:
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
                         f"  Laeuft MEGA-PARTY schon (anderes Terminal, Thonny, Autostart)? Dann dort beenden\n"
                         f"  (Strg+C bzw. Stop) und nochmal starten. Pruefen am Pi: ss -ltnp | grep {PORT}") from None
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


class PortBelegt(Exception):
    """Der Host kann auf seinem Port nicht lauschen - ohne Webserver kann niemand mitspielen."""


# ---------------------------------------------------------------- Grafik-Helfer

_FONTS, _TEXT, _GLOW = {}, {}, {}


def font(groesse, mono=False):
    k = (groesse, mono)
    if k not in _FONTS:
        _FONTS[k] = pygame.font.SysFont("dejavusansmono,liberationmono,consolas,couriernew", groesse, bold=True) if mono \
            else pygame.font.Font(None, groesse)
    return _FONTS[k]


def _render(txt, groesse, farbe, mono=False):
    k = (txt, groesse, farbe, mono)
    b = _TEXT.get(k)
    if b is None:
        if len(_TEXT) > 1500:
            _TEXT.clear()
        b = _TEXT[k] = font(groesse, mono).render(txt, True, farbe)
    return b


def text(s, txt, groesse, farbe, pos, anker="center", schatten=True, mono=False):
    txt = str(txt)
    bild = _render(txt, groesse, farbe, mono)
    rect = bild.get_rect(**{anker: (int(pos[0]), int(pos[1]))})
    if schatten:
        s.blit(_render(txt, groesse, (0, 0, 0), mono), rect.move(2, 2))
    s.blit(bild, rect)
    return rect


def umbruch(txt, groesse, breite):
    f, zeilen, zeile = font(groesse), [], ""
    for wort in txt.split():
        probe = (zeile + " " + wort).strip()
        if f.size(probe)[0] <= breite:
            zeile = probe
        else:
            zeilen.append(zeile)
            zeile = wort
    return zeilen + ([zeile] if zeile else [])


def glow(s, x, y, r, farbe, kern=True):
    r = max(2, int(r))
    g = _GLOW.get((r, farbe))
    if g is None:
        rand = r * 3
        g = pygame.Surface((rand * 2, rand * 2), pygame.SRCALPHA)
        for i in range(12):
            pygame.draw.circle(g, (*farbe, min(255, int(8 + i * i * 1.1))), (rand, rand), max(1, int(rand * (1 - i / 12))))
        _GLOW[(r, farbe)] = g
    s.blit(g, (int(x) - g.get_width() // 2, int(y) - g.get_height() // 2))
    if kern:
        pygame.draw.circle(s, farbe, (int(x), int(y)), r)
        pygame.draw.circle(s, (255, 255, 255), (int(x), int(y)), max(1, r // 2))


def mische(a, b, t):
    t = max(0.0, min(1.0, t))
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


# ---------------------------------------------------------------- Monitor + Spieler-Verwaltung


class App:
    """Der Host: Monitor (pygame), Webserver 8081, webspiele.py-Unterprozess, Moderator-Board, Demo-Bots."""

    def __init__(self, sim=False, fenster=False, name=None, spielt=True, schnell=False, max_runden=MAX_RUNDEN,
                 ziel=ZIEL_PUNKTE, headless=False, web_starten=True):
        name = sauberer_name(name or socket.gethostname())
        self.show = Show(schnell, max_runden, ziel)
        self.adressen = netz_adressen()  # [(WLAN/KABEL/NETZ, ip, broadcast)]
        self.ips = [ip for _, ip, _ in self.adressen]
        self.web = starte_web(self)  # zuerst: Port belegt -> PortBelegt, bevor irgendein Fenster aufgeht
        self.webspiele = starte_webspiele() if web_starten and WEB_BASIS else None
        pygame.init()
        self.screen = self._bildschirm(fenster or headless)
        pygame.display.set_caption("MEGA-PARTY")
        pygame.mouse.set_visible(False)
        self.hintergrund = pygame.Surface((B, H))
        for y in range(H):
            self.hintergrund.fill(mische((8, 4, 24), (24, 6, 36), y / H), (0, y, B, 1))
        self.url = f"http://{self.ips[0]}:{PORT}/"
        self.befehle = [(art, f"curl http://{ip}:{PORT}/j | python3") for art, ip, _ in self.adressen]
        try:
            self.qr = qr_bild(self.url, 250)
        except Exception as e:  # Fallback: nur die URL gross
            print("QR-Code nicht moeglich (qrgen.py?) -> URL als Text:", e)
            self.qr = None
        self.ereignisse = queue.Queue()
        self.show.ereignis = self.ereignisse.put
        self.show.bots_umschalten = self.bots_umschalten
        self.brett = mc.Brett(sim=sim)  # Platine des Moderators am Host
        self.bots = []
        self.partikel = []
        self.zeit = 0.0
        self.laeuft = True
        self.chip = None
        try:
            import chiptune  # HDMI-Sound fuer Jingles (braucht numpy), sonst stumm
            c = chiptune.Chiptune()
            self.chip = c if c.ok else None
        except Exception as e:
            print("HDMI-Sound aus:", e)
        self.stop = threading.Event()
        self.web_urls = [f"http://{ip}:{WEB_PORT}" for ip in self.ips]
        self.show.web_adressen = list(self.web_urls)
        self.web_qr = None
        try:
            self.web_qr = qr_bild(self.web_urls[0], 230)
        except Exception as e:
            print("QR fuer Browser-Spiel nicht moeglich:", e)
        threading.Thread(target=self.show.web_poller, args=(self.stop,), daemon=True).start()
        threading.Thread(target=leuchtfeuer, args=([b for _, _, b in self.adressen], self.stop), daemon=True).start()
        self.spieler_client = None
        self.host_browser = None
        if spielt:  # der Moderator spielt selbst mit - seine Taster sind ausserhalb der Board-Runden Moderator
            self.spieler_client = mc.Client(self.brett, DirektVerbindung(self.show), name, "pi",
                                            kennung="host/" + name, moderator=self.show.moderator)
            threading.Thread(target=self.spieler_client.lauf, args=(self.stop,), daemon=True).start()
            if WEB_BASIS:  # Browser-Runden: das Spiel geht auch am Host auf (wie bei den Clients)
                ziel = urlparse(WEB_BASIS)
                self.host_browser = mc.Browser(ziel.hostname, print, ziel.port or WEB_PORT)
        self._musik(MENU_LIED)
        print(f"MEGA-PARTY Host laeuft. Moderator: {name if spielt else '(Zuschauer)'}. Handy: {self.url}")
        for art, befehl in self.befehle:
            print(f"  Schueler-Pi ({art}):  {befehl}")

    def _bildschirm(self, fenster):
        try:
            if fenster:
                return pygame.display.set_mode((B, H))
            return pygame.display.set_mode((B, H), pygame.FULLSCREEN | pygame.SCALED)
        except pygame.error as e:  # kein Monitor -> Host laeuft trotzdem (Clients/Handys gehen weiter)
            print("Kein Monitor nutzbar, laufe ohne Bild:", e)
            pygame.display.quit()
            os.environ["SDL_VIDEODRIVER"] = "dummy"
            pygame.display.init()
            return pygame.display.set_mode((B, H))

    def _musik(self, lied):
        if self.chip:
            self.chip.musik(lied) if lied else self.chip.stop()

    def _jingle(self, lied):
        if self.chip:
            self.chip.effekt(lied, "pulse", 0.4)

    def client_hosts(self, adresse=""):
        """Host-Adressen fuer den ausgelieferten Client: zuerst die aus dem curl-Befehl, dann alle anderen."""
        erste = [adresse] if re.fullmatch(r"[A-Za-z0-9.-]{1,64}", adresse or "") else []
        return list(dict.fromkeys(erste + self.ips))[:6]

    def client_code(self, adresse=""):
        """mega_client.py fuer /j - mit eingetragenen Host-Adressen, damit der Client sofort verbindet."""
        with open(os.path.join(HIER, "mega_client.py"), encoding="utf-8") as f:
            code = f.read()
        return code.replace("STANDARD_HOSTS = []", f"STANDARD_HOSTS = {self.client_hosts(adresse)!r}", 1)

    # ---- Demo-Bots (LINKS in der Lobby)
    def bots_umschalten(self):
        if self.bots:
            for client, stop in self.bots:
                stop.set()
                with self.show.lock:
                    self.show.spieler.pop(client.id, None)
            self.bots = []
        else:
            self.bots_an(4)

    def bots_an(self, anzahl):
        for name in BOT_NAMEN[:anzahl]:
            stop = threading.Event()
            c = mc.Client(mc.Brett(sim=True, bot=True), DirektVerbindung(self.show), name, "bot",
                          kennung="bot/" + name, log=False)
            self.bots.append((c, stop))
            threading.Thread(target=c.lauf, args=(stop,), daemon=True).start()

    # ---- Hauptschleife
    def schritt(self, dt, zeichnen=True):
        self.zeit += dt
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                self.laeuft = False
            elif e.type == pygame.KEYDOWN:
                k = e.key
                if k == pygame.K_ESCAPE:
                    if self.show.zustand == "lobby":
                        self.laeuft = False
                    else:
                        self.show.reset()
                elif k in (pygame.K_SPACE, pygame.K_RETURN):
                    self.show.moderator("mitte")
                elif k == pygame.K_LEFT:
                    self.show.moderator("links")
                elif k in (pygame.K_RIGHT, pygame.K_n):
                    self.show.moderator("rechts")
                elif k in (pygame.K_a, pygame.K_s, pygame.K_d):  # eigene Taster per Tastatur (Laptop/Test)
                    self.brett.druck({pygame.K_a: "links", pygame.K_s: "mitte", pygame.K_d: "rechts"}[k])
        if self.spieler_client is None:  # Zuschauer-Modus: Taster sind nur Moderator
            while not self.brett.events.empty():
                self.show.moderator(self.brett.events.get_nowait()[0])
        self.show.update()
        self._host_browser()
        while not self.ereignisse.empty():
            self._ereignis(self.ereignisse.get_nowait())
        for t in self.partikel:
            t[0] += t[2] * dt
            t[1] += t[3] * dt
            t[3] += 400 * dt
            t[4] -= dt
        self.partikel = [t for t in self.partikel if t[4] > 0]
        if self.show.zustand == "sieger" and random.random() < dt * 5:
            self.funken(random.randint(80, 800), random.randint(120, 380), random.choice([GOLD, CYAN, PINK, WEISS]), 40)
        if zeichnen:
            self.zeichne()

    def _host_browser(self):
        """Moderator spielt Browser-Runden mit: kurz vor Spielstart geht das Spiel auf diesem Bildschirm auf
        (mit seinem Namen), nach der Runde/beim Ueberspringen wieder zu -> zurueck auf den Party-Monitor."""
        if not self.host_browser:
            return
        sh = self.show
        with sh.lock:
            r, z = sh.runde, sh.zustand
            name = self.spieler_client.name if self.spieler_client.id else None
            dran = ist_web(r) and name and (z == "laeuft" or (z == "ansage" and
                                                               time.monotonic() >= r["start"] - HOST_BROWSER_VORLAUF_S))
        if dran:
            self.host_browser.auf(name, r["rid"])
        elif self.host_browser.offen_fuer is not None:
            self.host_browser.zu()

    def _ereignis(self, z):
        if z == "lobby":
            self._musik(MENU_LIED)
        elif z == "ansage":
            self._musik(None)
            self._jingle(T_ANSAGE)
        elif z == "auswertung":
            self._jingle(T_RUNDE)
            self.funken(440, 300, GOLD, 70)
        elif z == "sieger":
            self._jingle(mc.FANFARE)

    def funken(self, x, y, farbe, anzahl):
        for _ in range(anzahl):
            w, v = random.uniform(0, math.tau), random.uniform(80, 420)
            leben = random.uniform(0.4, 1.0)
            self.partikel.append([x, y, math.cos(w) * v, math.sin(w) * v - 100, leben, leben, farbe])
        del self.partikel[:-500]

    def lauf(self):
        uhr = pygame.time.Clock()
        while self.laeuft:
            self.schritt(min(0.05, uhr.tick(30) / 1000.0))

    def beenden(self):
        self.stop.set()
        for _, stop in self.bots:
            stop.set()
        if self.host_browser:
            self.host_browser.zu()
        time.sleep(0.1)
        self.brett.schliessen()
        if self.web:
            self.web.shutdown()
            self.web.server_close()
        if self.webspiele and self.webspiele.poll() is None:  # selbst gestartetes webspiele.py mit beenden
            self.webspiele.terminate()
            try:
                self.webspiele.wait(3)
            except subprocess.TimeoutExpired:
                self.webspiele.kill()
        pygame.quit()

    # ---- Zeichnen
    def zeichne(self):
        s = self.screen
        s.blit(self.hintergrund, (0, 0))
        sh = self.show
        with sh.lock:  # Momentaufnahme, damit kein anderer Thread mitten im Zeichnen etwas aendert
            z = sh.zustand
            rang = sh.rangfolge()
            r = dict(sh.runde) if sh.runde else None
            fertig = [sh.spieler[i].name for i in sh.ergebnisse if i in sh.spieler]
            teilnehmer = len(sh.teilnehmer)
            rangliste = list(sh.rangliste)
            sieger = sh.spieler.get(sh.sieger_id)
            web_stand = dict(sh.web_stand) if sh.web_stand else {}
            zuordnung = {}
            if ist_web(r) and z == "laeuft":
                zuordnung = {id(e): sh.spieler[sid].name for sid, e in web_zuordnung(web_stand.get("spieler", []), sh.spieler)}
            hinweis = sh.web_hinweis if time.monotonic() - sh.web_hinweis_t < 20 else ""
        self._kopf(s, z, len(rang))
        if hinweis:
            text(s, hinweis, 24, ROT, (440, 70))
        if z == "lobby":
            self._lobby(s, len(rang))
        elif z == "ansage" and ist_web(r):
            self._web_ansage(s, r)
        elif z == "laeuft" and ist_web(r):
            self._web_laeuft(s, r, web_stand, zuordnung)
        elif z == "ansage":
            self._ansage(s, r)
        elif z == "laeuft":
            self._laeuft(s, r, fertig, teilnehmer)
        elif z == "auswertung":
            self._auswertung(s, r, rangliste)
        else:
            self._sieger(s, rang, sieger)
        self._rangliste(s, rang, z)
        self._gpio(s)
        for x, y, vx, vy, leben, voll, farbe in self.partikel:
            pygame.draw.circle(s, mische((0, 0, 0), farbe, leben / voll + 0.3), (int(x), int(y)),
                               max(1, int(5 * leben / voll)))
        text(s, "Taster: MITTE Start/Weiter  -  RECHTS Runde ueberspringen  -  LINKS Demo-Bots"
             "      Tastatur: Leertaste, Pfeile, N, ESC", 19, GRAU, (16, H - 6), "bottomleft", False)
        pygame.display.flip()
        jetzt = time.monotonic()
        if jetzt - TV["t"] > 0.4 and jetzt - TV["gefragt"] < 5:  # Monitorbild fuer /live, nur wenn jemand zuschaut
            TV["t"] = jetzt
            try:
                import io
                puffer = io.BytesIO()
                pygame.image.save(s, puffer, "tv.jpg")
                TV["jpg"] = puffer.getvalue()
            except Exception as e:  # Bild ist nur Zusatz, das Spiel laeuft weiter
                if not TV.get("fehler"):
                    print("TV-Bild aus:", e)
                TV["fehler"] = True

    def _kopf(self, s, z, anzahl):
        puls = 0.5 + 0.5 * math.sin(self.zeit * 2.5)
        text(s, "MEGA-PARTY", 58, mische(CYAN, PINK, puls), (20, 34), "midleft")
        sh = self.show
        mitte = {"lobby": "LOBBY", "sieger": "SIEGEREHRUNG"}.get(z, f"RUNDE {sh.nr} / {sh.max_runden}")
        text(s, mitte, 36, WEISS, (560, 34))
        text(s, f"{anzahl} Spieler", 32, GRAU, (B - 16, 34), "midright")

    def _lobby(self, s, anzahl):
        text(s, "MIT DEINEM PI - EIN BEFEHL IM TERMINAL:", 34, WEISS, (24, 88), "midleft")
        befehle = self.befehle[:3]  # mehr passt nicht auf den Monitor (alle stehen im Terminal)
        zeile = 80 if len(befehle) <= 2 else 64
        for i, (netz, befehl) in enumerate(befehle):  # riesig, damit niemand ':' und '.' verwechselt
            box = pygame.Rect(20, 108 + i * zeile, 840, zeile - 10)
            pygame.draw.rect(s, (10, 14, 12), box, border_radius=12)
            pygame.draw.rect(s, GRUEN, box, 3, border_radius=12)
            text(s, netz, 24, GRAU, (box.x + 14, box.centery), "midleft", False)
            groesse = 46 if zeile == 80 else 40
            while groesse > 16 and font(groesse, True).size(befehl)[0] > 720:
                groesse -= 1
            text(s, befehl, groesse, (120, 255, 150), (box.x + 110, box.centery), "midleft", False, mono=True)
        y0 = 108 + len(befehle) * zeile + 12
        if self.qr:
            s.blit(self.qr, (20, y0))
            text(s, "Ohne Pi: Handy scannen", 24, WEISS, (20 + self.qr.get_width() // 2, y0 + self.qr.get_height() + 16))
            x = 40 + self.qr.get_width()
        else:  # qrgen.py fehlt -> URL riesig
            text(s, "Ohne Pi: Handy-Browser", 34, WEISS, (24, y0 + 30), "midleft")
            text(s, self.url, 54, GELB, (24, y0 + 90), "midleft")
            x = 24
            y0 += 130
        if self.qr:
            text(s, "Handy: " + self.url, 30, GELB, (x, y0 + 16), "midleft")
        regeln = ["Deine 10 LEDs = dein Score.", "Alle spielen gleichzeitig am eigenen Board.",
                  "Platz 1/2/3 = 3/2/1 Punkte, Finale doppelt.", "Wer zuerst 10 LEDs hat, gewinnt!"]
        for i, zeile in enumerate(regeln):
            text(s, zeile, 26, WEISS, (x, y0 + 56 + i * 30), "midleft")
        for i, key in enumerate(rotation()):
            r = pygame.Rect(x + (i % 3) * 172, y0 + 180 + (i // 3) * 40, 164, 34)
            farbe = SPIEL_FARBE.get(key, WEISS)
            pygame.draw.rect(s, mische((15, 10, 30), farbe, 0.25), r, border_radius=10)
            pygame.draw.rect(s, farbe, r, 2, border_radius=10)
            text(s, info_von(key)["name"], 19, farbe, r.center, schatten=False)
        puls = 1 + 0.05 * math.sin(self.zeit * 5)
        mitte = (x + 860) // 2
        if anzahl:
            text(s, f"{anzahl} verbunden - MITTE startet!", int(34 * puls), GELB, (mitte, 668))
        else:
            text(s, "Warte auf Spieler ... (LINKS = Demo-Bots)", 30, GELB, (mitte, 668))

    def _web_ansage(self, s, r):
        info, farbe = info_von(r["spiel"]), SPIEL_FARBE.get(r["spiel"], WEISS)
        rest = r["start"] - time.monotonic()
        if r["finale"]:
            text(s, "FINALE - DOPPELTE PUNKTE!", 40, GOLD, (440, 100))
        text(s, f"{info['name']} im Browser!", 74, farbe, (440, 150))
        y = 205
        for url in self.web_urls[:2]:
            groesse = 64
            while groesse > 20 and font(groesse, True).size(url)[0] > 820:
                groesse -= 2
            text(s, url, groesse, GELB, (440, y), mono=True)
            y += groesse + 8
        if self.web_qr:
            q = pygame.transform.smoothscale(self.web_qr, (210, 210)) if self.web_qr.get_width() > 210 else self.web_qr
            s.blit(q, (40, y + 4))
            tx = 40 + q.get_width() + 24
        else:
            tx = 60
        f = 2 if r["finale"] else 1
        zeilen = ["Pis: das Spiel geht von selbst auf.", "Laptop/Handy: Adresse oeffnen und den",
                  "MEGA-Namen eingeben (wie rechts in der Rangliste)!",
                  f"Spielzeit {r['dauer']} s. Platz 1/2/3 = {3 * f}/{2 * f}/{f} Punkte"]
        for i, zeile in enumerate(zeilen):
            text(s, zeile, 30, WEISS if i < 3 else GOLD, (tx, y + 30 + i * 38), "midleft")
        if rest <= 5.2:
            text(s, str(max(1, math.ceil(rest))), 120, GELB, (440, 630))
        else:
            text(s, f"Start in {math.ceil(rest)} s", 40, GRAU, (440, 640))

    def _web_laeuft(self, s, r, st, zuordnung):
        info, farbe = info_von(r["spiel"]), SPIEL_FARBE.get(r["spiel"], WEISS)
        rest = st.get("rest", 0) if st.get("phase") in ("countdown", "spiel") else max(0, r["start"] + r["dauer"] - time.monotonic())
        text(s, info["name"], 60, farbe, (440, 104))
        anteil = max(0.0, min(1.0, rest / max(1, r["dauer"])))
        pygame.draw.rect(s, DUNKEL, (60, 140, 760, 14), border_radius=7)
        pygame.draw.rect(s, mische(ROT, GRUEN, anteil), (60, 140, int(760 * anteil), 14), border_radius=7)
        phase = {"countdown": "GLEICH GEHT'S LOS", "spiel": "LAEUFT", "ende": "FERTIG", "lobby": "warte ..."}.get(st.get("phase"), "Verbinde ...")
        text(s, f"{phase}   {math.ceil(rest)} s", 40, WEISS, (440, 186))
        text(s, self.web_urls[0] if self.web_urls else "", 30, GELB, (440, 226), mono=True)
        liste = st.get("spieler", [])
        for i, e in enumerate(liste[:12]):
            y = 270 + i * 34
            mega = zuordnung.get(id(e))
            wert = f"Ziel {e['ziel']:.1f} s" if e.get("ziel") is not None else f"{e.get('best', 0)} m"
            text(s, f"{i + 1}.", 28, GRAU, (110, y), "midright")
            text(s, str(e.get("name", ""))[:14], 28, WEISS if mega else GRAU, (125, y), "midleft")
            text(s, f"= {mega}" if mega else "(kein MEGA-Name)", 22, GRUEN if mega else DUNKEL, (390, y), "midleft")
            text(s, wert, 28, GOLD if e.get("ziel") is not None else WEISS, (820, y), "midright")
        if not liste:
            text(s, "Noch niemand im Browser-Spiel", 36, GRAU, (440, 400))

    def _ansage(self, s, r):
        info = mc.SPIELE[r["spiel"]]
        farbe = SPIEL_FARBE[r["spiel"]]
        rest = r["start"] - time.monotonic()
        if r["finale"]:
            glow(s, 440, 112, 40, GOLD, kern=False)
            text(s, "FINALE - DOPPELTE PUNKTE!", 46, GOLD, (440, 112))
        text(s, info["name"], 100, farbe, (440, 190))
        for i, zeile in enumerate(umbruch(info["kurz"], 32, 780)):
            text(s, zeile, 32, WEISS, (440, 262 + i * 34))
        for i, lbl in enumerate(info["tasten"]):  # die 3 Taster mit ihrer Bedeutung
            x = 260 + i * 180
            aktiv = bool(lbl)
            pygame.draw.circle(s, (40, 40, 55), (x, 410), 38)
            pygame.draw.circle(s, farbe if aktiv else DUNKEL, (x, 410), 28)
            text(s, ("LINKS", "MITTE", "RECHTS")[i], 20, GRAU, (x, 462))
            text(s, lbl or "-", 24, farbe if aktiv else DUNKEL, (x, 488))
        f = 2 if r["finale"] else 1
        pkt = f"Platz 1: {3 * f}  -  Platz 2: {2 * f}  -  Platz 3: {f}"
        if info["trost"]:
            pkt += f"  -  alle anderen mit Erfolg: {info['trost'] * f}"
        text(s, pkt, 28, GOLD, (440, 535))
        if rest <= 3.2:
            text(s, str(max(1, math.ceil(rest))), 140, GELB, (440, 625))
        else:
            text(s, f"Start in {math.ceil(rest)} s - Finger auf die Taster!", 34, GRAU, (440, 620))

    def _laeuft(self, s, r, fertig, teilnehmer):
        key, info = r["spiel"], mc.SPIELE[r["spiel"]]
        farbe = SPIEL_FARBE[key]
        vergangen = time.monotonic() - r["start"]
        text(s, info["name"], 64, farbe, (440, 100))
        pygame.draw.rect(s, DUNKEL, (60, 138, 760, 14), border_radius=7)
        anteil = max(0.0, 1 - vergangen / r["dauer"])
        pygame.draw.rect(s, mische(ROT, GRUEN, anteil), (60, 138, int(760 * anteil), 14), border_radius=7)
        puls = 0.5 + 0.5 * math.sin(self.zeit * 8)
        if key == "binaer":
            zahl = r["param"]["zahl"]
            text(s, "STELLT DIESE ZAHL BINAER EIN:", 34, WEISS, (440, 200))
            glow(s, 440, 320, 60, (90, 60, 160), kern=False)
            text(s, zahl, 200, GELB, (440, 320))
            for i, w in enumerate((128, 64, 32, 16, 8, 4, 2, 1)):
                text(s, w, 26, GRAU, (205 + i * 67, 440))
                text(s, f"LED{i + 3}", 16, DUNKEL, (205 + i * 67, 462), schatten=False)
        elif key == "piep":
            text(s, "ZAEHLT DIE PIEPS!", 80, PINK, (440, 250))
            if self.brett.f_jetzt:  # Buzzer am Host piept gerade -> Schallwellen
                for i in range(3):
                    pygame.draw.circle(s, PINK, (440, 380), 30 + i * 28, 3)
            pygame.draw.circle(s, WEISS, (440, 380), 22)
            text(s, "Antwort: RECHTS +1, LINKS -1, MITTE fertig", 28, GRAU, (440, 470))
        elif key == "reaktion":
            text(s, "AUGEN AUF EURE LEDs!", 76, mische(GELB, WEISS, puls), (440, 280))
            text(s, "3 Blitze - wer zu frueh drueckt, kassiert +1000 ms", 30, GRAU, (440, 380))
        elif key == "tap":
            text(s, "TAP! TAP! TAP!", int(110 + 20 * puls), (255, 130, 40), (440, 300))
        elif key == "lauflicht":
            text(s, "Stoppt in der Mitte!", 60, CYAN, (440, 230))
            for i in range(mc.N):
                x = 215 + i * 50
                ziel = i in (4, 5)
                pygame.draw.circle(s, GOLD if ziel else DUNKEL, (x, 340), 18 if ziel else 14)
            text(s, "ZIEL", 26, GOLD, (440, 385))
        elif key == "simon":
            text(s, "Merken ... und nachdruecken!", 58, GRUEN, (440, 230))
            for i, f in enumerate((ROT, GELB, GRUEN)):
                pygame.draw.circle(s, mische((20, 20, 30), f, 0.6 + 0.4 * puls), (290 + i * 150, 360), 50)
        text(s, f"Fertig: {len(fertig)} / {teilnehmer}", 36, WEISS, (440, 520))
        x, y = 40, 560
        for name in fertig[-24:]:
            w = font(22).size(name)[0] + 22
            if x + w > 850:
                x, y = 40, y + 32
            pygame.draw.rect(s, (30, 70, 45), (x, y, w, 26), border_radius=13)
            text(s, name, 22, WEISS, (x + w // 2, y + 13), schatten=False)
            x += w + 8

    def _auswertung(self, s, r, rangliste):
        if self.show.uebersprungen:
            text(s, "RUNDE UEBERSPRUNGEN", 70, GRAU, (440, 300))
            return
        info = info_von(r["spiel"])
        text(s, f"ERGEBNIS: {info['name']}", 50, SPIEL_FARBE.get(r["spiel"], WEISS), (440, 95))
        podest = [(440, 170, 0), (260, 125, 1), (620, 90, 2)]
        for x, hoehe, i in podest:
            if i >= len(rangliste) or rangliste[i]["platz"] is None:
                continue
            e = rangliste[i]
            rect = pygame.Rect(x - 80, 420 - hoehe, 160, hoehe)
            farbe = (GOLD, (200, 200, 215), (205, 127, 50))[i]
            pygame.draw.rect(s, mische((20, 20, 30), farbe, 0.5), rect, border_radius=8)
            pygame.draw.rect(s, farbe, rect, 3, border_radius=8)
            text(s, f"+{e['pkt']}", 54, WEISS, (x, rect.centery))
            text(s, e["name"], 32, farbe, (x, rect.top - 44))
            text(s, e["text"], 19, GRAU, (x, rect.top - 18))
        for j, e in enumerate(rangliste[3:10]):
            y = 450 + j * 29
            platz = f"{e['platz']}." if e["platz"] else "-"
            text(s, platz, 24, GRAU, (70, y), "midleft")
            text(s, e["name"], 24, ART_FARBE.get(e["art"], WEISS), (115, y), "midleft")
            text(s, e["text"], 22, GRAU, (330, y), "midleft")
            text(s, f"+{e['pkt']}" if e["pkt"] else "", 24, GRUEN, (840, y), "midright")
        if not rangliste:
            text(s, "Niemand hat ein Ergebnis abgegeben", 40, GRAU, (440, 300))
        rest = self.show.AUSWERTUNG - (time.monotonic() - self.show.seit)
        text(s, f"weiter in {max(0, math.ceil(rest))} s  (MITTE = sofort)", 24, GRAU, (440, 670))

    def _sieger(self, s, rang, sieger):
        if sieger:
            puls = 1 + 0.06 * math.sin(self.zeit * 7)
            text(s, f"{sieger.name} GEWINNT!", int(92 * puls), GOLD, (440, 150))
            text(s, f"mit {sieger.punkte} Punkten", 40, WEISS, (440, 220))
        for x, hoehe, i in ((440, 200, 0), (240, 150, 1), (640, 110, 2)):
            if i >= len(rang):
                continue
            sp = rang[i]
            rect = pygame.Rect(x - 90, 600 - hoehe, 180, hoehe)
            farbe = (GOLD, (200, 200, 215), (205, 127, 50))[i]
            pygame.draw.rect(s, mische((20, 20, 30), farbe, 0.5), rect, border_radius=8)
            pygame.draw.rect(s, farbe, rect, 3, border_radius=8)
            text(s, str(i + 1), 80, WEISS, rect.center)
            text(s, sp.name, 34, farbe, (x, rect.top - 40))
            text(s, f"{sp.punkte} Punkte", 24, GRAU, (x, rect.top - 14))
        text(s, "MITTE = neues Spiel (Spieler bleiben verbunden)", 26, GRAU, (440, 650))

    def _rangliste(self, s, rang, z):
        x0 = 878
        pygame.draw.rect(s, (14, 10, 30), (x0, 66, 394, 432), border_radius=12)
        text(s, "RANGLISTE  (LEDs = Score)", 26, WEISS, (x0 + 12, 84), "midleft")
        for i, sp in enumerate(rang[:13]):
            y = 112 + i * 29
            aktiv = sp.aktiv()
            farbe = ART_FARBE.get(sp.art, WEISS) if aktiv else DUNKEL
            text(s, f"{i + 1}.", 22, GRAU, (x0 + 30, y), "midright", False)
            name = sp.name if len(sp.name) <= 10 else sp.name[:9] + "."
            text(s, name, 24, farbe, (x0 + 36, y), "midleft", False)
            for j in range(mc.N):  # Mini-Platine: so leuchtet es gerade auf dem Board des Spielers
                lx = x0 + 168 + j * 13
                if j < min(10, sp.punkte):
                    pygame.draw.circle(s, (255, 60, 60), (lx, y), 5)
                else:
                    pygame.draw.circle(s, (60, 20, 25), (lx, y), 5)
            if z in ("auswertung", "sieger") and sp.gewinn:
                text(s, f"+{sp.gewinn}", 22, GRUEN, (x0 + 340, y), "midright", False)
            text(s, sp.punkte, 26, WEISS, (x0 + 384, y), "midright", False)
        if len(rang) > 13:
            text(s, f"... und {len(rang) - 13} weitere", 20, GRAU, (x0 + 197, 487))

    def _gpio(self, s):
        """Live-Schaltbild der Host-Platine: echter Zustand von LEDs, Tastern und Buzzer."""
        b = self.brett
        x0, y0 = 878, 504
        pygame.draw.rect(s, (8, 22, 14), (x0, y0, 394, 196), border_radius=12)
        pygame.draw.rect(s, (40, 110, 70), (x0, y0, 394, 196), 2, border_radius=12)
        text(s, "LIVE-GPIO  (Host-Platine)", 22, (120, 230, 160), (x0 + 12, y0 + 14), "midleft", False)
        gnd = y0 + 104
        pygame.draw.line(s, GRAU, (x0 + 14, gnd), (x0 + 370, gnd), 2)
        text(s, "GND", 16, GRAU, (x0 + 374, gnd), "midleft", False)
        for i, pin in enumerate(mc.LED_PINS):  # GPIO -> Widerstand -> LED -> GND
            x = x0 + 26 + i * 35
            an = b.zustand[i]
            text(s, pin, 17, WEISS if an else GRAU, (x, y0 + 34), schatten=False)
            pygame.draw.line(s, GRAU, (x, y0 + 42), (x, y0 + 50), 2)
            pygame.draw.rect(s, (200, 170, 110), (x - 4, y0 + 50, 8, 14), 1)
            pygame.draw.line(s, GRAU, (x, y0 + 64), (x, y0 + 72), 2)
            dreieck = [(x - 7, y0 + 72), (x + 7, y0 + 72), (x, y0 + 84)]
            if an:
                glow(s, x, y0 + 78, 8, (255, 50, 50), kern=False)
                pygame.draw.polygon(s, (255, 70, 70), dreieck)
            else:
                pygame.draw.polygon(s, GRAU, dreieck, 1)
            pygame.draw.line(s, (255, 90, 90) if an else GRAU, (x - 7, y0 + 85), (x + 7, y0 + 85), 2)
            pygame.draw.line(s, GRAU, (x, y0 + 85), (x, gnd), 1)
        for j, (name, pin) in enumerate(mc.TASTER.items()):  # Pull-up: gedrueckt = LOW
            x = x0 + 16 + j * 126
            y = y0 + 132
            gedrueckt = b.gedrueckt(name)
            text(s, f"GPIO{pin} {name}", 16, WEISS, (x, y - 12), "midleft", False)
            pygame.draw.circle(s, GRAU, (x + 4, y + 8), 3)
            pygame.draw.circle(s, GRAU, (x + 34, y + 8), 3)
            ende = (x + 34, y + 8) if gedrueckt else (x + 30, y - 4)
            pygame.draw.line(s, GELB if gedrueckt else GRAU, (x + 4, y + 8), ende, 2)
            text(s, "LOW" if gedrueckt else "HIGH", 18, GELB if gedrueckt else GRAU, (x + 44, y + 8), "midleft", False)
        f = b.f_jetzt
        y = y0 + 176
        text(s, f"GPIO{mc.BUZZER_PIN} Buzzer (PWM)", 16, WEISS, (x0 + 16, y), "midleft", False)
        if f:
            punkte, periode = [], max(4, int(6000 / f))
            for k in range(0, 120):
                punkte.append((x0 + 170 + k, y - 7 if (k // periode) % 2 else y + 7))
            pygame.draw.lines(s, PINK, False, punkte, 2)
            text(s, f"{f:.0f} Hz", 20, PINK, (x0 + 300, y), "midleft", False)
        else:
            text(s, "aus", 18, GRAU, (x0 + 170, y), "midleft", False)


# ---------------------------------------------------------------- Selbsttest


def selbsttest(sim):
    """Host + 5 echte Client-Prozesse (per /j geladen) + Handy (Web-API) + Bot spielen eine ganze Partie.
    Browser-Runden testet tests/webtest.py (mit echtem webspiele.py)."""
    global WEB_BASIS
    t0 = time.monotonic()
    fehler = []
    WEB_BASIS = "http://127.0.0.1:9"  # Browser-Spielserver absichtlich nicht erreichbar
    try:
        app = App(sim=sim, spielt=False, schnell=True, max_runden=6, ziel=99, headless=True, web_starten=False)
    except PortBelegt as e:
        print("SELBSTTEST FEHLER:", e)
        return 1
    try:  # zweiter Host auf demselben Port -> klare Meldung statt stillem Doppelbetrieb
        starte_web(app).server_close()
        fehler.append(f"Port {PORT} doppelt belegbar - keine Meldung")
    except PortBelegt:
        pass
    mc.Brett(sim=False).schliessen()  # ohne GPIO (Laptop) bzw. mit belegten Pins: darf nie abstuerzen
    basis = f"http://127.0.0.1:{PORT}"
    uhr = pygame.time.Clock()
    frame = [0]

    def tick():
        frame[0] += 1
        app.schritt(min(0.05, uhr.tick(30) / 1000.0), zeichnen=frame[0] % 2 == 0)

    def post(pfad, **body):
        daten = urllib.parse.urlencode(body).encode()
        return json.loads(urllib.request.urlopen(basis + pfad, data=daten, timeout=5).read())

    def get(pfad):
        return json.loads(urllib.request.urlopen(basis + pfad, timeout=5).read())

    # SIMON ist DEAKTIVIERT -> muss rausfliegen; Pi-only-Spiele zuerst;
    # NINJA mit absichtlich totem Spielserver -> muss mit Hinweis uebersprungen werden
    app.show.plan = ["simon", "lauflicht", "ninja", "reaktion", "tap", "piep"]
    # 1) Client so laden, wie es die Mitschueler machen (curl http://HOST:8081/j | python3)
    code = urllib.request.urlopen(basis + "/j", timeout=5).read().decode("utf-8")
    if not code.startswith("#!/usr/bin/env python3"):
        fehler.append("/j liefert kein Python-Skript")
    if f"STANDARD_HOSTS = {app.client_hosts('127.0.0.1')!r}" not in code or app.ips[0] not in code:
        fehler.append("Host-IPs nicht im ausgelieferten Client")
    compile(code, "client.py", "exec")
    tmp = tempfile.mkdtemp(prefix="mega_test_")
    pfad = os.path.join(tmp, "mega_client.py")
    with open(pfad, "w", encoding="utf-8") as f:
        f.write(code)

    prozesse = {}

    def starte(name, extra=()):
        log = open(os.path.join(tmp, name + ".log"), "w", encoding="utf-8")
        prozesse[name] = (subprocess.Popen([sys.executable, "-X", "utf8", "-u", pfad, "--sim", "--bot", "--leise",
                                            "--name", name, "--host", "127.0.0.1", *extra],
                                           stdout=log, stderr=subprocess.STDOUT), log)

    starte("Sim1", ["--suche"])  # sucht per UDP, --host nur als Ersatz
    for i in range(2, 6):
        starte(f"Sim{i}")
    app.bots_an(1)  # Host-interner Bot (Direkt-Verbindung)

    # 2) ein Handy-Spieler ueber genau die Web-API der Handy-Seite (kommt ab Runde 3 dazu)
    handy = {"ok": 0, "fehler": 0, "aktionen": 0, "phasen": set()}
    stop, handy_los = threading.Event(), threading.Event()

    def handy_lauf():
        handy_los.wait()
        try:
            j = post("/join", name="Handy<b>")
            sid = j["id"]
        except Exception:
            handy["fehler"] += 1
            return
        erledigt, blitz_vorher = set(), False
        while not stop.is_set():
            try:
                st = get(f"/state?id={sid}")
                handy["ok"] += 1
                handy["phasen"].add(st["phase"])
                name, nr = st["round_name"], st["round"]
                if st["phase"] == "round":
                    aktion = None
                    if name == "TAP-MARATHON":
                        aktion = {"action": "tap", "value": 3}
                    elif name == "REAKTIONS-BLITZ" and st.get("flash") and not blitz_vorher:
                        aktion = {"action": "tap", "value": ""}
                    elif name == "ZAEHL DIE PIEPS" and nr not in erledigt and time.monotonic() * 1000 > st["server_ms"]:
                        erledigt.add(nr)
                        aktion = {"action": "answer", "value": random.randint(4, 10)}
                    elif name == "BINAER-BLITZ" and nr not in erledigt and st["instruction"].split()[4].isdigit():
                        erledigt.add(nr)
                        zahl = int(st["instruction"].split()[4])
                        aktion = {"action": "answer", "value": bin(zahl).count("1")}
                    if aktion:
                        post(f"/act?id={sid}", client_ms=int(time.monotonic() * 1000), **aktion)
                        handy["aktionen"] += 1
                    blitz_vorher = st.get("flash", False)
            except Exception:
                handy["fehler"] += 1
            time.sleep(0.1)

    threading.Thread(target=handy_lauf, daemon=True).start()

    # 3) Lobby: warten bis alle da sind, dann startet der "Moderator"
    def eigene():  # weitere Clients (z.B. vom Laptop) duerfen zusaetzlich mitspielen
        return sum(1 for sp in app.show.rangfolge() if sp.name.startswith(("Sim", "Bot Ohm")))

    ende = time.monotonic() + 30
    while eigene() < 6 and time.monotonic() < ende:
        tick()
    for _ in range(30):  # kurz warten, falls gerade noch jemand beitritt
        tick()
    print(f"Lobby: {len(app.show.spieler)} Spieler: " + ", ".join(sp.name for sp in app.show.rangfolge()), flush=True)
    if eigene() < 6:
        fehler.append("nicht alle Clients sind beigetreten")
    app.show.moderator("mitte")

    # 4) Partie laufen lassen; nach Runde 2 wird Sim3 hart beendet und neu gestartet (Reconnect-Test)
    neustart = None
    letzte_runde = 0
    ende = time.monotonic() + 420
    while app.show.zustand != "sieger" and time.monotonic() < ende:
        tick()
        sh = app.show
        if sh.zustand == "auswertung" and sh.nr != letzte_runde:
            letzte_runde = sh.nr
            print(f"Runde {sh.nr}: {info_von(sh.runde['spiel'])['name']:<16} " +
                  ", ".join(f"{e['name']} +{e['pkt']}" for e in sh.rangliste if e["pkt"]), flush=True)
            if sh.nr == 2 and neustart is None:
                sp = next(s for s in sh.spieler.values() if s.name == "Sim3")
                neustart = (sp.id, sp.punkte, sp.runden)
                p, log = prozesse["Sim3"]
                p.kill()
                p.wait()
                log.close()
                starte("Sim3")
                handy_los.set()  # ab jetzt spielt ein Handy mit -> nur noch Handy-taugliche Spiele
    for _ in range(40):
        tick()
    stop.set()

    sh = app.show
    if sh.zustand != "sieger":
        fehler.append(f"Partie nicht fertig (Zustand {sh.zustand}, Runde {sh.nr})")
    board_spiele = {k for k in mc.SPIELE if k not in DEAKTIVIERT}
    if not board_spiele <= set(sh.gespielt) or set(sh.gespielt) & (DEAKTIVIERT | set(WEB_SPIELE)):
        fehler.append(f"falsche Spielauswahl: {sh.gespielt}")
    if "uebersprungen: Browser-Spiel" not in sh.web_hinweis:
        fehler.append(f"kein Hinweis fuer toten Browser-Spielserver: {sh.web_hinweis!r}")
    rang = sh.rangfolge()
    for sp in rang:
        if sp.art == "bot" and sp.name.startswith("Sim") and sp.runden < 4:
            fehler.append(f"{sp.name} hat nur {sp.runden} Ergebnisse abgegeben")
    if neustart:
        sp3 = sh.spieler.get(neustart[0])
        if not sp3 or sp3.punkte < neustart[1] or sp3.runden <= neustart[2]:
            fehler.append("Reconnect: Sim3 hat Score/Platz verloren")
    web = next((sp for sp in rang if sp.art == "web"), None)
    if handy["ok"] < 50 or handy["fehler"] or not handy["aktionen"] or not web or web.runden < 3 \
            or not {"round", "result", "done"} <= handy["phasen"]:
        fehler.append(f"Handy-Schnittstelle: {handy}")
    with open(os.path.join(tmp, "Sim1.log"), encoding="utf-8") as f:
        sim1 = f.read()
    udp = "per UDP gefunden" in sim1
    if "Verbunden als" not in sim1:
        fehler.append("Sim1 nicht verbunden")

    # 5) Last: 30 Clients pollen gleichzeitig (Klasse mit 30 Pis)
    zeiten, last_fehler = [], [0]
    ids = [post("/join", name=f"Last{i}", art="pi", kennung=f"last/{i}")["id"] for i in range(30)]

    def last(sid):
        for _ in range(30):
            a = time.monotonic()
            try:
                get(f"/state?id={sid}")
                zeiten.append(time.monotonic() - a)
            except Exception:
                last_fehler[0] += 1
            time.sleep(0.05)

    threads = [threading.Thread(target=last, args=(i,)) for i in ids]
    for t in threads:
        t.start()
    while any(t.is_alive() for t in threads):
        tick()
    zeiten.sort()
    p95 = zeiten[int(len(zeiten) * 0.95)] * 1000 if zeiten else 0
    if last_fehler[0] or len(zeiten) != 900:
        fehler.append(f"Last-Test: {last_fehler[0]} Fehler")
    # kaputte Anfragen duerfen den Server nicht stoeren
    for pfad, body in (("/act?id=x", "action=answer&rid=abc"), ("/act?id=" + ids[0], "action=answer&rid=1&value=nan"),
                       ("/gibtsnicht", "x=1"), ("/join", "name=%ff%fe")):
        try:
            urllib.request.urlopen(basis + pfad, data=body.encode(), timeout=3)
        except Exception:
            pass
    try:
        urllib.request.urlopen(basis + "/", timeout=3).read()
    except Exception:
        fehler.append("Server nach kaputter Anfrage tot")

    for p, log in prozesse.values():
        p.kill()
        p.wait()
        log.close()
    sieger = sh.spieler.get(sh.sieger_id)
    app.beenden()
    print("Endstand: " + ", ".join(f"{sp.name} {sp.punkte}" for sp in rang if not sp.name.startswith("Last")))
    if fehler:
        print("SELBSTTEST FEHLER:", "; ".join(fehler), f"(Logs: {tmp})")
        return 1
    print(f"SELBSTTEST OK: Sieger {sieger.name} mit {sieger.punkte} Punkten nach {sh.nr} Runden "
          f"({len(set(sh.gespielt))} Board-Spiele, Binaer+Simon aus, NINJA ohne Server uebersprungen), 5 Client-Prozesse + Handy + Bot, "
          f"Reconnect ok, UDP-Suche {'ok' if udp else 'NICHT gehoert (Fallback --host)'}, "
          f"Handy {handy['ok']} /state + {handy['aktionen']} /act ({web.runden} Runden gewertet), Last 30 Clients x 30: 900/900 ok, p95 {p95:.0f} ms, "
          f"{time.monotonic() - t0:.0f} s")
    return 0


def main():
    global WEB_DAUER_S, WEB_BASIS
    ap = argparse.ArgumentParser(description="MEGA-PARTY Host")
    ap.add_argument("--name", default=None, help="Name des Moderators als Mitspieler (Standard: Hostname)")
    ap.add_argument("--zuschauer", action="store_true", help="nicht mitspielen, nur moderieren")
    ap.add_argument("--sim", action="store_true", help="ohne GPIO")
    ap.add_argument("--fenster", action="store_true")
    ap.add_argument("--runden", type=int, default=MAX_RUNDEN, help="maximale Rundenzahl (letzte = Finale x2)")
    ap.add_argument("--ziel", type=int, default=ZIEL_PUNKTE, help="Punkte zum Sieg")
    ap.add_argument("--schnell", action="store_true", help="kurze Ansagen/Auswertungen")
    ap.add_argument("--selbsttest", action="store_true")
    ap.add_argument("--web-dauer", type=int, default=WEB_DAUER_S, help="Spielzeit der Browser-Runden in s")
    ap.add_argument("--web-server", default=f"127.0.0.1:{WEB_PORT}",
                    help="webspiele.py-Server (host:port); lokal wird er automatisch mitgestartet")
    ap.add_argument("--ohne-web", action="store_true", help="keine Browser-Runden, webspiele.py nicht starten")
    a = ap.parse_args()
    WEB_DAUER_S = max(20, min(600, a.web_dauer))
    WEB_BASIS = None if a.ohne_web else "http://" + a.web_server
    if a.selbsttest:
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        sys.exit(selbsttest(a.sim))
    # per SSH gestartet? -> trotzdem auf den Pi-Monitor (labwc/Wayland)
    if sys.platform.startswith("linux") and not os.environ.get("WAYLAND_DISPLAY") and not os.environ.get("DISPLAY"):
        laufzeit = f"/run/user/{os.getuid()}"
        if os.path.exists(os.path.join(laufzeit, "wayland-0")):
            os.environ["WAYLAND_DISPLAY"] = "wayland-0"
            os.environ.setdefault("XDG_RUNTIME_DIR", laufzeit)
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
