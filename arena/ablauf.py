"""ABLAUF - die Spielregeln des Hosts (PiArena), ganz ohne Grafik.

WAS MACHT DIE DATEI?
  Show = der Spielablauf:  Lobby -> Ansage + Countdown -> alle spielen dasselbe Minispiel ->
  Auswertung (Platz 1/2/3 = 3/2/1 Punkte, Finale doppelt) -> ... -> Siegerehrung.
  Spieler = eine Person (Pi, Handy oder Bot) mit Punktestand.
  Dazu die Verbindung zu den Browser-Spielen (arena/browserspiele.py, Port 8082).

WER BENUTZT SIE?  arena/monitor.py (zeigt den Zustand an) und arena/webserver.py (Anfragen der Pis/Handys).

WICHTIGSTE TEILE
  WEB_SPIELE       die Browser-Spiele (Name + Kurztext)
  rotation()       welche Spiele der Host auswaehlt (DEAKTIVIERT / --nur beachten)
  Show.starte_runde, Show.werte_aus, Show.weiter   der eigentliche Ablauf
  Show.moderator   was die 3 Taster am Host machen (Start / Ueberspringen / Bots)
"""
import json
import math
import os
import queue
import random
import secrets
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from urllib.parse import urlparse

import einstellungen as E
import minispiele
from einstellungen import DEAKTIVIERT, MAX_RUNDEN, MAX_SPIELER, PLATZ_PUNKTE, WEB_PORT, ZIEL_PUNKTE

HIER = os.path.dirname(os.path.abspath(__file__))

# ================================================================ Rundentypen
# Board-Spiele stehen in SPIELE in minispiele.py. Browser-Spiele laufen auf browserspiele.py (Port 8082).
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
    return WEB_SPIELE.get(key) or minispiele.SPIELE[key]


def erlaubt(key):
    """Darf der Host dieses Spiel auswaehlen? Mit --nur: nur die genannten, sonst alle ausser DEAKTIVIERT."""
    return key in E.NUR if E.NUR else key not in DEAKTIVIERT


def ist_web(r):
    return bool(r) and r["spiel"] in WEB_SPIELE


def rotation():
    """Spiele, die der Host auswaehlt: Board-Spiele + Browser-Spiele mit .html-Datei in arena/web/."""
    keys = [k for k in minispiele.SPIELE if erlaubt(k)]
    if E.WEB_BASIS:
        keys += [k for k in WEB_SPIELE if erlaubt(k) and os.path.exists(os.path.join(HIER, "web", f"{k}.html"))]
    return keys


# ================================================================ Browser-Spiele (browserspiele.py, Port 8082)


def web_anfrage(pfad, body=None, timeout=1.5):
    """GET (body None) / POST an browserspiele.py. -> dict oder None (nie Exception)."""
    if not E.WEB_BASIS:
        return None
    try:
        daten = urllib.parse.urlencode(body).encode() if body is not None else None
        with urllib.request.urlopen(E.WEB_BASIS + pfad, data=daten, timeout=timeout) as r:
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
    """Startet browserspiele.py als Unterprozess, falls E.WEB_BASIS lokal ist und dort noch nichts laeuft.
    -> Popen oder None. Klappt es nicht, gibt es eben keine Browser-Runden (nie ein Absturz)."""
    ziel = urlparse(E.WEB_BASIS or "")
    if ziel.hostname not in ("127.0.0.1", "localhost") or ziel.port != WEB_PORT:
        return None  # fremder Server per --web-server -> der laeuft woanders
    if web_anfrage("/state") is not None:
        print(f"Browser-Spiele: browserspiele.py laeuft schon auf Port {WEB_PORT}, wird mitbenutzt.")
        return None
    pfad = os.path.join(HIER, "browserspiele.py")
    if not os.path.exists(pfad):
        print(f"Browser-Spiele aus: {pfad} fehlt -> nur Board-Runden.")
        return None
    if not port_frei(WEB_PORT):
        print(f"Browser-Spiele aus: Port {WEB_PORT} ist von einem anderen Programm belegt -> nur Board-Runden.")
        return None
    try:
        proc = subprocess.Popen([sys.executable, pfad], cwd=HIER, stdin=subprocess.DEVNULL)
    except OSError as e:
        print(f"Browser-Spiele aus: browserspiele.py startet nicht ({e}).")
        return None
    print(f"Browser-Spiele: browserspiele.py gestartet (Port {WEB_PORT}).")
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


def sauberer_name(name):
    name = "".join(c for c in str(name) if c.isalnum() or c in " _-.").strip()
    return name[:12] or "Spieler"


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
                # bleiben sie im Warte-Modus und zeigen ihren Score (geprueft mit dem echten spieler.py).
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
        if not minispiele.SPIELE[r["spiel"]]["handy"]:
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
            return f"{info_von(r['spiel'])['name']} im Browser: {adr} - gib deinen Arena-Namen ein!"
        if z in ("ansage", "laeuft") and r:
            info = minispiele.SPIELE[r["spiel"]]
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
                for k in [k for k in self.plan if not erlaubt(k)]:
                    self.plan.remove(k)
                # Browser-Spiele nur, wenn browserspiele.py (8082) antwortet - sonst mit Hinweis ueberspringen
                for k in [k for k in self.plan if k in WEB_SPIELE and not self.web_ok]:
                    self.plan.remove(k)
                    self.hinweis(f"{WEB_SPIELE[k]['name']} uebersprungen: Browser-Spiel (Port {WEB_PORT}) nicht erreichbar")
                if self.plan:
                    break
            handys = any(sp.art == "web" and sp.aktiv() for sp in self.spieler.values())
            # Lauflicht/Simon brauchen echte LEDs -> mit Handy-Spielern nur die Handy-tauglichen Spiele
            key = next((k for k in self.plan if info_von(k)["handy"] or not handys), None)
            if key is None:
                key = self.rng.choice([k for k in minispiele.SPIELE if minispiele.SPIELE[k]["handy"] and erlaubt(k)]
                                     or rotation() or list(minispiele.SPIELE))
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
        """Browser-Runde: browserspiele.py auf das Spiel umschalten; /start kommt 5 s vor Ende der Ansage
        (browserspiele.py zaehlt selbst 5 s runter) -> Spielstart = Ende der Ansage."""
        dauer = max(20, min(600, int(E.WEB_DAUER_S)))
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
        """Holt laufend GET /state von browserspiele.py (Hintergrund-Thread, App startet ihn)."""
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
    """Wie schueler_pi.HttpVerbindung, aber ohne Netzwerk - fuer das Board des Moderators am Host und die Demo-Bots."""

    def __init__(self, show):
        self.show = show

    def join(self, name, art, kennung):
        return self.show.api_join(name, art, kennung)

    def poll(self, sid):
        return self.show.api_state(sid)

    def ergebnis(self, sid, rid, res):
        return self.show.api_act(sid, "answer", res["wert"], {"rid": rid, "ok": int(bool(res["ok"])),
                                                              "text": res["text"]})
