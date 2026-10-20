#!/usr/bin/env python3
"""Ende-zu-Ende-Test Browser-Runden MIT Moderator: Host (mega.py ohne Monitor, Moderator spielt mit,
startet webspiele.py selbst) + 3 echte Client-Prozesse + Ersatz-Browser (MEGA_BROWSER) fuer Host und Clients.

Geprueft wird:
  - Host startet webspiele.py selbst mit (ein Startbefehl)
  - Browser-Runde: Host UND Clients oeffnen den Browser selbst mit ?name=<MEGA-Name>, nach der Runde zu
  - Wertung: Moderator 3, Ben 2, Anna 1, Carl 0, "Fremder" ignoriert; Namens-Zuordnung (exakt/Gross-Klein/Praefix)
  - RECHTS am Moderator-Taster ueberspringt eine LAUFENDE Browser-Runde und eine Browser-ANSAGE:
    8082 geht auf /lobby (und bleibt dort), Browser gehen zu, es geht mit der naechsten Runde weiter
  - danach laufen normale Taster-Runden weiter

Aufruf (vom Repo-Ordner):  python3 tests/webtest_moderator.py      (Ports 8081 und 8082 muessen frei sein)
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request

os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"
PARTY = os.environ.get("MEGA_PARTY_DIR") or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "party")
sys.path.insert(0, PARTY)
import pygame  # noqa: E402
import mega  # noqa: E402

WEB = "http://127.0.0.1:8082"
LOGS = tempfile.mkdtemp(prefix="mega_webtest_mod_")
HOSTNAME = mega.sauberer_name(socket.gethostname())
TEMPO = {HOSTNAME: 5, "Ben": 4, "Anna": 3, "Carl": 2}

# Ersatz-Browser: tut, was die echte Spielseite mit ?name= macht (beitreten + laufend /upd), plus Herzschlag-Datei
ERSATZ_BROWSER = r'''
import json, os, sys, time, urllib.parse, urllib.request
url = sys.argv[-1]
u = urllib.parse.urlparse(url)
name = urllib.parse.parse_qs(u.query).get("name", [""])[0]
logs = os.environ["FAKE_LOGS"]
tempo = json.loads(os.environ["FAKE_TEMPO"]).get(name, 1)
basis = u.scheme + "://" + u.netloc
with open(os.path.join(logs, "browser.log"), "a", encoding="utf-8") as f:
    f.write("AUF " + name + " " + url + "\n")
def post(p, **d):
    return json.loads(urllib.request.urlopen(basis + p, data=urllib.parse.urlencode(d).encode(), timeout=3).read())
sid = post("/join", name=name)["id"]
t0 = None
while True:
    with open(os.path.join(logs, "hb_" + name + ".txt"), "w") as f:
        f.write(str(time.time()))
    try:
        x = 0.0 if t0 is None else (time.time() - t0) * 50 * tempo
        st = post("/upd", id=sid, x="%.1f" % x, y="300", lebt="1")
        if st["phase"] == "spiel" and t0 is None:
            t0 = time.time()
        elif st["phase"] != "spiel":
            t0 = None
    except Exception:
        pass
    time.sleep(0.2)
'''


def post(p, **d):
    return json.loads(urllib.request.urlopen(WEB + p, data=urllib.parse.urlencode(d).encode(), timeout=3).read())


def web_phase():
    try:
        return json.loads(urllib.request.urlopen(WEB + "/state", timeout=1).read())["phase"]
    except Exception:
        return None


def browser_offen(name):
    """Herzschlag juenger als 1 s -> der Ersatz-Browser von <name> laeuft."""
    try:
        return time.time() - os.path.getmtime(os.path.join(LOGS, f"hb_{name}.txt")) < 1.0
    except OSError:
        return False


def main():
    fehler = []
    # Namens-Zuordnung Browser -> MEGA-Spieler (reine Logik)
    spieler = {i: mega.Spieler(i, n, "pi", i) for i, n in (("a", "Anna"), ("b", "Ben"), ("c", "Carl"))}
    liste = [{"name": "BEN", "best": 9}, {"name": " anna ", "best": 5}, {"name": "Carlxyz", "best": 3},
             {"name": "Fremder", "best": 99}, {"name": "", "best": 1}]
    if [sid for sid, _ in mega.web_zuordnung(liste, spieler)] != ["b", "a", "c"]:
        fehler.append("web_zuordnung: exakt/Gross-Klein/Praefix/Fremder falsch")

    fake = os.path.join(LOGS, "ersatz_browser.py")
    with open(fake, "w", encoding="utf-8") as f:
        f.write(ERSATZ_BROWSER)
    os.environ["MEGA_BROWSER"] = f'"{sys.executable.replace(os.sep, "/")}" "{fake.replace(os.sep, "/")}"'
    os.environ["FAKE_LOGS"] = LOGS
    os.environ["FAKE_TEMPO"] = json.dumps(TEMPO)

    mega.WEB_DAUER_S = 20
    app = mega.App(sim=True, spielt=True, schnell=True, max_runden=6, ziel=99, headless=True)  # Name = Hostname
    if not app.webspiele:
        fehler.append("Host hat webspiele.py nicht selbst gestartet (Port 8082 schon belegt?)")
    procs, logs = [], []
    for n in ("Anna", "Ben", "Carl"):
        log = open(os.path.join(LOGS, n + ".log"), "w", encoding="utf-8")
        logs.append(log)
        procs.append(subprocess.Popen([sys.executable, "-X", "utf8", "-u", os.path.join(PARTY, "mega_client.py"),
                                       "--sim", "--bot", "--leise", "--name", n, "--host", "127.0.0.1"],
                                      stdout=log, stderr=subprocess.STDOUT))
    uhr = pygame.time.Clock()

    def tick():
        app.schritt(0.033, zeichnen=True)
        uhr.tick(30)

    def ticke_bis(bedingung, sekunden):
        ende = time.time() + sekunden
        while not bedingung() and time.time() < ende:
            tick()
        return bedingung()

    ticke_bis(lambda: len(app.show.spieler) >= 4 and app.show.web_ok, 25)
    print("Spieler:", [s.name for s in app.show.spieler.values()], "web_ok:", app.show.web_ok, flush=True)
    if app.spieler_client.name != HOSTNAME:
        fehler.append(f"Moderator-Name {app.spieler_client.name!r} statt Hostname {HOSTNAME!r}")
    app.show.plan = ["ninja", "tap", "flappy", "auto", "reaktion"]
    app.show.moderator("mitte")

    fremd = {"stop": False}

    def fremder():  # jemand mit einem Namen, den es in der MEGA-PARTY nicht gibt -> wird ignoriert
        sid = post("/join", name="Fremder")["id"]
        while not fremd["stop"]:
            try:
                post("/upd", id=sid, x="99999", y="300", lebt="1")
            except Exception:
                pass
            time.sleep(0.3)

    threading.Thread(target=fremder, daemon=True).start()
    gesehen = {}

    def auswertung_von(nr):
        sh = app.show
        if sh.zustand == "auswertung" and sh.nr == nr and nr not in gesehen:
            gesehen[nr] = ([(e["name"], e["pkt"]) for e in sh.rangliste], sh.uebersprungen)
            print("Runde", nr, sh.runde["spiel"], gesehen[nr], flush=True)
        return nr in gesehen

    # Runde 1 NINJA: alle Browser gehen von selbst auf, Wertung nach Weite
    ticke_bis(lambda: app.show.zustand == "laeuft", 20)
    alle = [HOSTNAME, "Anna", "Ben", "Carl"]
    if not ticke_bis(lambda: all(browser_offen(n) for n in alle), 10):
        fehler.append("Runde 1: nicht alle Browser offen: " + str({n: browser_offen(n) for n in alle}))
    ticke_bis(lambda: auswertung_von(1), 40)
    erwartet = [(HOSTNAME, 3), ("Ben", 2), ("Anna", 1), ("Carl", 0)]
    if gesehen.get(1, ([], 0))[0] != erwartet:
        fehler.append(f"Runde 1 Wertung {gesehen.get(1)} statt {erwartet}")
    if not ticke_bis(lambda: not any(browser_offen(n) for n in alle), 4):
        fehler.append("Runde 1: Browser nach der Runde nicht zu")

    # Runde 2 TAP (Board)
    ticke_bis(lambda: auswertung_von(2), 40)

    # Runde 3 FLAPPY: laeuft schon, Moderator drueckt RECHTS an seiner Platine
    ticke_bis(lambda: app.show.nr == 3 and app.show.zustand == "laeuft" and web_phase() == "spiel", 30)
    ticke_bis(lambda: browser_offen(HOSTNAME), 3)
    print("Runde 3 laeuft, 8082:", web_phase(), "- RECHTS", flush=True)
    app.brett.druck("rechts")
    if not ticke_bis(lambda: auswertung_von(3), 3) or not gesehen[3][1]:
        fehler.append("Runde 3: RECHTS hat die laufende Browser-Runde nicht uebersprungen")
    if not ticke_bis(lambda: web_phase() == "lobby", 3):
        fehler.append(f"Runde 3: 8082 nicht auf /lobby ({web_phase()})")
    if not ticke_bis(lambda: not any(browser_offen(n) for n in alle), 4):
        fehler.append("Runde 3: Browser nach Ueberspringen nicht zu")

    # Runde 4 AUTO: schon in der Ansage ueberspringen; 8082 darf danach NICHT doch noch starten
    ticke_bis(lambda: app.show.nr == 4 and app.show.zustand == "ansage", 15)
    ticke_bis(lambda: False, 2)
    app.brett.druck("rechts")
    if not ticke_bis(lambda: auswertung_von(4), 3) or not gesehen[4][1]:
        fehler.append("Runde 4: RECHTS hat die Browser-Ansage nicht uebersprungen")
    ende = time.time() + 6
    while time.time() < ende and app.show.nr == 4:
        tick()
        if web_phase() in ("countdown", "spiel"):
            fehler.append("Runde 4: 8082 startet nach dem Ueberspringen trotzdem")
            break

    # Runde 5 REAKTION: normale Taster-Runde laeuft weiter
    if not ticke_bis(lambda: auswertung_von(5), 40) or gesehen[5][1] or not gesehen[5][0]:
        fehler.append(f"Runde 5 (Board nach Ueberspringen) kaputt: {gesehen.get(5)}")
    fremd["stop"] = True
    for _ in range(30):
        tick()
    pkt = {s.name: (s.punkte, s.runden) for s in app.show.spieler.values()}
    print("Punkte (Punkte, Runden):", pkt, flush=True)
    alive = [p.poll() is None for p in procs]
    if not all(alive):
        fehler.append(f"Client-Prozess gestorben: {alive}")
    for p in procs:
        p.kill()
        p.wait()
    for log in logs:
        log.close()
    web_proc = app.webspiele
    app.beenden()
    if web_proc and web_proc.poll() is None:
        fehler.append("webspiele.py laeuft nach app.beenden() noch")
    for n in ("Anna", "Ben", "Carl"):
        with open(os.path.join(LOGS, n + ".log"), encoding="utf-8", errors="replace") as f:
            log = f.read()
        if "Traceback" in log or "Spielfehler" in log:
            fehler.append(f"{n}: Fehler im Client-Log")
        if "Browser-Runde: Spiel geht gleich von selbst auf" not in log:
            fehler.append(f"{n}: Browser nicht selbst geoeffnet")
    with open(os.path.join(LOGS, "browser.log"), encoding="utf-8") as f:
        geoeffnet = f.read()
    if f"?name={urllib.parse.quote(HOSTNAME)}" not in geoeffnet:
        fehler.append("Host-Browser nicht mit ?name=<Hostname> geoeffnet")
    print(geoeffnet.strip())
    if fehler:
        print("WEBTEST-MODERATOR FEHLER:", "; ".join(fehler), f"(Logs: {LOGS})")
        return 1
    print(f"WEBTEST-MODERATOR OK: webspiele.py vom Host gestartet+beendet, Browser fuer Host '{HOSTNAME}' + 3 Clients "
          f"selbst auf/zu, Wertung {erwartet}, RECHTS in laufender Runde und in Ansage -> /lobby + weiter")
    return 0


if __name__ == "__main__":
    sys.exit(main())
