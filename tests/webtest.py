#!/usr/bin/env python3
"""Ende-zu-Ende-Test Browser-Runde: Host (arena/host.py, ohne Monitor) + Browser-Spielserver (browserspiele.py)
+ 3 echte Client-Prozesse (arena/spieler.py --sim --bot) + 4 simulierte Browser-Spieler.

Geprueft wird: die Browser-Namen werden den Arena-Spielern richtig zugeordnet
(" anna " exakt, "BEN" Gross/Klein, "Carlxyz" Praefix, "Fremder" ignoriert), die Punkte stimmen
(Ben 3, Anna 2, Carl 1) und danach laeuft eine normale Taster-Runde weiter.

Aufruf (vom Repo-Ordner):  python3 tests/webtest.py
Braucht die Ports 8081 und 8082 frei (vorher ./stop.sh, falls PiArena laeuft).
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request

os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARENA = os.path.join(REPO, "arena")
sys.path.insert(0, ARENA)
import pygame  # noqa: E402
import einstellungen  # noqa: E402
from monitor import App  # noqa: E402

WEB = "http://127.0.0.1:8082"
LOGS = tempfile.mkdtemp(prefix="arena_webtest_")


def post(p, **d):
    daten = urllib.parse.urlencode(d).encode()
    return json.loads(urllib.request.urlopen(WEB + p, data=daten, timeout=3).read())


def web_lebt():
    try:
        urllib.request.urlopen(WEB + "/state", timeout=1).read()
        return True
    except Exception:
        return False


def main():
    einstellungen.WEB_DAUER_S = 20  # kurze Browser-Runde (20 s) fuer den Test
    app = App(sim=True, spielt=False, schnell=True, max_runden=5, ziel=99, headless=True)
    # Startet der Host den Browser-Spielserver selbst mit? Sonst starten wir ihn hier.
    eigener_web = None
    ende = time.time() + 3
    while not web_lebt() and time.time() < ende:
        time.sleep(0.2)
    if not web_lebt():
        eigener_web = subprocess.Popen([sys.executable, "-X", "utf8", os.path.join(ARENA, "browserspiele.py")],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        ende = time.time() + 5
        while not web_lebt() and time.time() < ende:
            time.sleep(0.2)
    print("Browser-Spielserver:", "vom Host gestartet" if eigener_web is None else "vom Test gestartet",
          "- erreichbar" if web_lebt() else "- NICHT erreichbar", flush=True)

    app.show.plan = ["ninja", "tap", "reaktion"]
    procs, logs = [], []
    for n in ("Anna", "Ben", "Carl"):
        log = open(os.path.join(LOGS, n + ".log"), "w", encoding="utf-8")
        logs.append(log)
        procs.append(subprocess.Popen([sys.executable, "-X", "utf8", "-u", os.path.join(ARENA, "spieler.py"),
                                       "--sim", "--bot", "--leise", "--name", n, "--host", "127.0.0.1"],
                                      stdout=log, stderr=subprocess.STDOUT))
    uhr = pygame.time.Clock()

    def tick():
        app.schritt(0.033, zeichnen=True)
        uhr.tick(30)

    ende = time.time() + 20
    while len(app.show.spieler) < 3 and time.time() < ende:
        tick()
    print("Spieler:", [s.name for s in app.show.spieler.values()], flush=True)
    ende = time.time() + 8  # der Host fragt den Spielserver nur alle 2 s ab -> warten, bis er ihn kennt
    while not app.show.web_ok and time.time() < ende:
        tick()
    app.show.moderator("mitte")

    web = {}

    def browser():
        while app.show.zustand == "ansage" and not web:
            time.sleep(0.2)
        time.sleep(2)
        for n in (" anna ", "BEN", "Carlxyz", "Fremder"):
            web[n] = post("/join", name=n)["id"]
        t0 = time.time()
        tempo = {"BEN": 4, " anna ": 3, "Carlxyz": 2, "Fremder": 9}
        while app.show.nr == 1 and app.show.zustand in ("ansage", "laeuft"):
            for n, sid in web.items():
                x = (time.time() - t0) * 50 * tempo[n]
                post("/upd", id=sid, x=f"{x:.1f}", y="300", lebt="1")
            time.sleep(0.2)

    threading.Thread(target=browser, daemon=True).start()
    gesehen, ende = {}, time.time() + 120
    while time.time() < ende and app.show.nr < 3:
        tick()
        sh = app.show
        if sh.zustand == "auswertung" and sh.nr not in gesehen:
            gesehen[sh.nr] = [(e["name"], e["pkt"]) for e in sh.rangliste]
            print("Runde", sh.nr, sh.runde["spiel"], gesehen[sh.nr], "uebersprungen" if sh.uebersprungen else "",
                  flush=True)
    for _ in range(60):
        tick()
    pkt = {s.name: (s.punkte, s.runden) for s in app.show.spieler.values()}
    print("Punkte (Punkte, Runden):", pkt)
    alive = [p.poll() is None for p in procs]
    print("Clients leben:", alive)
    for p in procs:
        p.kill()
        p.wait()
    for log in logs:
        log.close()
    if eigener_web:
        eigener_web.kill()
        eigener_web.wait()
    app.beenden()
    for n in ("Anna", "Ben", "Carl"):
        with open(os.path.join(LOGS, n + ".log"), encoding="utf-8", errors="replace") as f:
            log = f.read()
        print(f"  {n}: Traceback={'Traceback' in log} Spielfehler={'Spielfehler' in log}")
    ok = gesehen.get(1) == [("Ben", 3), ("Anna", 2), ("Carl", 1)] and 2 in gesehen and all(alive) and \
        all(n in pkt and pkt[n][1] >= 2 for n in ("Anna", "Ben", "Carl"))
    print("WEBTEST", "OK" if ok else f"FEHLER (Logs: {LOGS})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
