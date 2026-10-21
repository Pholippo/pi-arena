"""SELBSTTEST des Hosts (PiArena): eine ganze Partie ohne Menschen.

Host + 5 echte Spieler-Prozesse (so geladen wie am Schueler-Pi: curl .../j) + Handy + Bot spielen
eine ganze Partie, mit Reconnect, Last-Test (30 Clients) und kaputten Anfragen.
Start:  python3 arena/host.py --selbsttest --sim     (oder alle Tests: python3 tests/run_all.py)
"""
import json
import os
import random
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request

import pygame

import ablauf
import einstellungen as E
import minispiele
import spieler as schueler_pi
from ablauf import WEB_SPIELE, info_von
from einstellungen import DEAKTIVIERT, PORT
from monitor import App
from webserver import PortBelegt, starte_web

HIER = os.path.dirname(os.path.abspath(__file__))


def pruefe_nur(fehler):
    """--nur: nur die genannten Spiele, auch wenn sie in DEAKTIVIERT stehen; falscher Name -> klare Meldung."""
    alt = E.NUR
    try:
        E.NUR = {"morse"}
        if ablauf.rotation() != ["morse"]:
            fehler.append(f"--nur morse: Rotation {ablauf.rotation()}")
        E.NUR = None
        if "morse" in ablauf.rotation():
            fehler.append("morse ist nicht DEAKTIVIERT")
    finally:
        E.NUR = alt
    p = subprocess.run([sys.executable, "-X", "utf8", os.path.join(HIER, "host.py"), "--sim", "--nur", "gibtsnicht"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    if p.returncode != 2 or "morse" not in (p.stdout + p.stderr):
        fehler.append(f"--nur gibtsnicht: Code {p.returncode}, keine Liste der Spiele")
    # Uebungsspiel MORSE-ZAEHLER mit einem Bot (drueckt genau richtig) -> muss "ok" sein
    brett = schueler_pi.Brett(sim=True, bot=True)
    res = minispiele.spiel_morse(brett, {}, random.Random(7))
    if not res["ok"] or not 0 < res["wert"] < 4:
        fehler.append(f"spiel_morse mit Bot: {res}")


def selbsttest(sim):
    """Host + 5 echte Client-Prozesse (per /j geladen) + Handy (Web-API) + Bot spielen eine ganze Partie.
    Browser-Runden testet tests/webtest.py (mit echtem browserspiele.py)."""
    t0 = time.monotonic()
    fehler = []
    pruefe_nur(fehler)
    E.WEB_BASIS = "http://127.0.0.1:9"  # Browser-Spielserver absichtlich nicht erreichbar
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
    schueler_pi.Brett(sim=False).schliessen()  # ohne GPIO (Laptop) bzw. mit belegten Pins: darf nie abstuerzen
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
    tmp = tempfile.mkdtemp(prefix="arena_test_")
    pfad = os.path.join(tmp, "spieler.py")
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
    board_spiele = {k for k in minispiele.SPIELE if k not in DEAKTIVIERT}
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
          f"({len(set(sh.gespielt))} Board-Spiele, Binaer+Simon+Morse aus, --nur ok, NINJA ohne Server uebersprungen), 5 Client-Prozesse + Handy + Bot, "
          f"Reconnect ok, UDP-Suche {'ok' if udp else 'NICHT gehoert (Fallback --host)'}, "
          f"Handy {handy['ok']} /state + {handy['aktionen']} /act ({web.runden} Runden gewertet), Last 30 Clients x 30: 900/900 ok, p95 {p95:.0f} ms, "
          f"{time.monotonic() - t0:.0f} s")
    return 0
